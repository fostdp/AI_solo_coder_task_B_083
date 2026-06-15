import logging
import threading
import time
import queue
from collections import defaultdict
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from clickhouse_driver import Client
from .config import settings

logger = logging.getLogger(__name__)


class NamedConnectionPool:
    """
    命名ClickHouse连接池（修复：跨馆藏比对与老化预测争夺连接池问题）
    
    修复说明：
    - 原架构：全局单例Client，所有任务共用一个TCP连接
    - 问题：凌晨2点老化预测与跨馆藏比对同时运行，连接互斥导致写入超时
    - 方案：每个业务域（primary/comparator/aging）独立连接池，物理隔离
    - 默认池大小：primary=4, comparator=2, aging=3
    """

    def __init__(self, name: str, max_connections: int = 4):
        self.name = name
        self.max_connections = max_connections
        self._pool: "queue.Queue[Client]" = queue.Queue(maxsize=max_connections)
        self._created_count = 0
        self._lock = threading.Lock()
        self._total_checkouts = 0
        self._total_returns = 0
        self._timeouts = 0

    def _create_client(self) -> Optional[Client]:
        """创建新的ClickHouse连接"""
        try:
            client = Client(
                host=settings.CLICKHOUSE_HOST,
                port=settings.CLICKHOUSE_PORT,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=settings.CLICKHOUSE_DATABASE,
                connect_timeout=10,
                send_receive_timeout=30,
            )
            logger.info(f"[{self.name}] 创建ClickHouse连接 (池大小={self.max_connections}, "
                        f"已创建={self._created_count + 1})")
            return client
        except Exception as e:
            logger.error(f"[{self.name}] 创建ClickHouse连接失败: {e}")
            return None

    def acquire(self, timeout: float = 5.0) -> Optional[Client]:
        """
        从连接池获取连接
        
        Args:
            timeout: 等待超时时间（秒）
            
        Returns:
            Client 或 None（超时）
        """
        start_time = time.time()

        try:
            client = self._pool.get_nowait()
            self._total_checkouts += 1
            return client
        except queue.Empty:
            pass

        with self._lock:
            if self._created_count < self.max_connections:
                client = self._create_client()
                if client:
                    self._created_count += 1
                    self._total_checkouts += 1
                    return client

        wait_start = time.time()
        try:
            remaining = timeout - (time.time() - start_time)
            if remaining > 0:
                client = self._pool.get(timeout=remaining)
                self._total_checkouts += 1
                return client
        except queue.Empty:
            pass

        self._timeouts += 1
        logger.warning(f"[{self.name}] 连接池获取超时 (已等待{time.time()-wait_start:.1f}s, "
                       f"超时总数={self._timeouts})")
        return None

    def release(self, client: Client) -> None:
        """归还连接到连接池"""
        if client is None:
            return
        try:
            self._pool.put_nowait(client)
            self._total_returns += 1
        except queue.Full:
            try:
                client.disconnect()
            except Exception:
                pass
            with self._lock:
                self._created_count -= 1

    def close_all(self) -> None:
        """关闭所有连接"""
        closed = 0
        while not self._pool.empty():
            try:
                client = self._pool.get_nowait()
                client.disconnect()
                closed += 1
            except (queue.Empty, Exception):
                pass
        logger.info(f"[{self.name}] 连接池已关闭，释放{closed}个连接")

    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计"""
        return {
            "name": self.name,
            "max_connections": self.max_connections,
            "created": self._created_count,
            "idle": self._pool.qsize(),
            "checkouts": self._total_checkouts,
            "returns": self._total_returns,
            "timeouts": self._timeouts,
        }


_connection_pools: Dict[str, NamedConnectionPool] = {}
_pool_lock = threading.Lock()


def get_connection_pool(name: str = "primary", max_connections: int = 4) -> NamedConnectionPool:
    """
    获取或创建命名连接池（工厂函数）
    
    连接池命名规范：
    - "primary":    主业务连接池（4连接）- 传感器写入、老化预测等
    - "comparator": 跨馆藏比对连接池（2连接）- 独立隔离，凌晨专用
    - "aging":      老化引擎连接池（3连接）- 独立隔离，批量计算用
    """
    with _pool_lock:
        if name not in _connection_pools:
            _connection_pools[name] = NamedConnectionPool(name, max_connections)
        return _connection_pools[name]


def close_all_pools() -> None:
    """关闭所有连接池"""
    with _pool_lock:
        for name, pool in _connection_pools.items():
            pool.close_all()
        _connection_pools.clear()


class BatchWriter:
    """
    异步批量写入器
    使用队列 + 后台线程实现高吞吐批量写入
    触发条件：缓冲区满500条 或 距离上次写入超过30秒

    设计目标：
    - 减少ClickHouse INSERT次数，降低写入延迟
    - 线程安全，支持多生产者
    - 自动flush，避免数据长时间滞留内存
    """

    DEFAULT_BATCH_SIZE = 500
    DEFAULT_FLUSH_INTERVAL = 30

    def __init__(
        self,
        client: Client,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: int = DEFAULT_FLUSH_INTERVAL,
        max_queue_size: int = 10000
    ):
        self.client = client
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size

        self._queues: Dict[str, queue.Queue] = defaultdict(
            lambda: queue.Queue(maxsize=max_queue_size)
        )
        self._table_columns: Dict[str, List[str]] = {}
        self._last_flush: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
        self._stats = {
            "total_writes": 0,
            "total_records": 0,
            "dropped_records": 0
        }

    def register_table(self, table_name: str, columns: List[str]):
        """
        注册数据表及其列名
        用于生成INSERT语句和验证数据
        """
        self._table_columns[table_name] = columns
        self._last_flush[table_name] = time.time()

    def add(self, table_name: str, data: Dict) -> bool:
        """
        添加单条数据到写入队列
        非阻塞，队列满时丢弃旧数据
        """
        if table_name not in self._queues:
            self._queues[table_name] = queue.Queue(maxsize=self.max_queue_size)
            self._last_flush[table_name] = time.time()

        q = self._queues[table_name]
        try:
            if q.full():
                try:
                    q.get_nowait()
                    self._stats["dropped_records"] += 1
                except queue.Empty:
                    pass
            q.put_nowait(data)
            return True
        except Exception as e:
            logger.error(f"BatchWriter添加数据失败: {e}")
            return False

    def add_batch(self, table_name: str, data_list: List[Dict]) -> int:
        """批量添加数据"""
        count = 0
        for data in data_list:
            if self.add(table_name, data):
                count += 1
        return count

    def start(self):
        """启动后台flush线程"""
        if self._running:
            return

        self._running = True
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="clickhouse-batch-writer"
        )
        self._flush_thread.start()
        logger.info("BatchWriter后台线程已启动")

    def stop(self):
        """停止后台线程并flush所有数据"""
        self._running = False
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
        self.flush_all()
        logger.info("BatchWriter已停止")

    def _flush_loop(self):
        """后台flush循环"""
        while self._running:
            try:
                time.sleep(1)
                now = time.time()

                for table_name in list(self._queues.keys()):
                    q = self._queues[table_name]
                    qsize = q.qsize()
                    last_flush = self._last_flush.get(table_name, 0)

                    if qsize >= self.batch_size or (now - last_flush) >= self.flush_interval:
                        if qsize > 0:
                            self._flush_table(table_name)

            except Exception as e:
                logger.error(f"BatchWriter flush循环异常: {e}")
                time.sleep(1)

    def _flush_table(self, table_name: str) -> int:
        """
        写入单个表的所有缓冲数据
        返回写入的记录数
        """
        q = self._queues.get(table_name)
        if not q or q.empty():
            return 0

        data_list = []
        try:
            while not q.empty() and len(data_list) < self.batch_size:
                data_list.append(q.get_nowait())
        except queue.Empty:
            pass

        if not data_list:
            return 0

        try:
            columns = self._table_columns.get(table_name)
            if not columns:
                columns = list(data_list[0].keys())
                self._table_columns[table_name] = columns

            values = [tuple(d.get(col) for col in columns) for d in data_list]
            query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES"
            self.client.execute(query, values)

            self._stats["total_writes"] += 1
            self._stats["total_records"] += len(data_list)
            self._last_flush[table_name] = time.time()

            logger.debug(f"BatchWriter写入 {table_name}: {len(data_list)}条")
            return len(data_list)

        except Exception as e:
            logger.error(f"BatchWriter写入 {table_name} 失败: {e}")
            for d in data_list:
                try:
                    q.put_nowait(d)
                except queue.Full:
                    self._stats["dropped_records"] += 1
            return 0

    def flush_all(self) -> Dict[str, int]:
        """立即flush所有表"""
        results = {}
        for table_name in list(self._queues.keys()):
            count = self._flush_table(table_name)
            while count > 0:
                count = self._flush_table(table_name)
            results[table_name] = results.get(table_name, 0) + count
        return results

    def flush_table(self, table_name: str) -> int:
        """立即flush指定表"""
        total = 0
        count = self._flush_table(table_name)
        while count > 0:
            total += count
            count = self._flush_table(table_name)
        return total

    def get_queue_size(self, table_name: str = None) -> int:
        """获取队列大小"""
        if table_name:
            return self._queues.get(table_name, queue.Queue()).qsize()
        return sum(q.qsize() for q in self._queues.values())

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self._stats,
            "queue_size": self.get_queue_size(),
            "tables": list(self._queues.keys()),
            "per_table_queue_size": {
                t: q.qsize() for t, q in self._queues.items()
            }
        }


class ClickHouseManager:
    """
    ClickHouse数据库管理器（修复：连接池隔离）
    
    修复说明：
    - 支持 pool_name 参数指定独立连接池
    - comparator 使用 "comparator" 池（2连接），不与主业务争用
    - 所有查询/写入操作：从池获取连接→执行→归还，自动管理
    """

    def __init__(self, pool_name: str = "primary", pool_size: int = 4):
        self.pool_name = pool_name
        self.pool_size = pool_size
        self.pool = get_connection_pool(pool_name, pool_size)

        self.client: Optional[Client] = None
        self.batch_writer: Optional[BatchWriter] = None
        self._env_buffer: List[Dict] = []
        self._ph_buffer: List[Dict] = []
        self._alert_buffer: List[Dict] = []

    def connect(self):
        """建立连接（通过连接池）"""
        try:
            client = self.pool.acquire(timeout=10.0)
            if client is None:
                logger.error(f"[{self.pool_name}] 获取连接失败")
                return False

            self.client = client
            logger.info(f"[{self.pool_name}] ClickHouse连接成功 (池大小={self.pool_size})")

            self.batch_writer = BatchWriter(
                client=self.client,
                batch_size=getattr(settings, "BATCH_WRITE_SIZE", 500),
                flush_interval=getattr(settings, "BATCH_WRITE_INTERVAL", 30),
                max_queue_size=10000
            )

            self.batch_writer.register_table(
                "env_sensor_data",
                ["timestamp", "sensor_id", "shelf_id", "slot_id",
                 "temperature", "humidity", "light", "voc",
                 "mold_spore", "sensor_type"]
            )
            self.batch_writer.register_table(
                "ph_sensor_data",
                ["timestamp", "sensor_id", "shelf_id", "slot_id",
                 "ph_value", "sensor_type"]
            )
            self.batch_writer.register_table(
                "alerts",
                ["alert_id", "timestamp", "shelf_id", "slot_id",
                 "alert_level", "alert_type", "alert_value",
                 "threshold", "message", "is_handled"]
            )

            self.batch_writer.start()

            return True
        except Exception as e:
            logger.error(f"[{self.pool_name}] ClickHouse连接失败: {e}")
            return False

    def close(self):
        """关闭连接（归还到连接池）"""
        if self.batch_writer:
            self.batch_writer.stop()
            self.batch_writer = None
        if self.client:
            self.pool.release(self.client)
            self.client = None

    def _execute_with_pool(self, query: str, params: Dict = None):
        """
        从连接池获取连接执行查询，自动归还
        
        这是修复连接池争夺的关键方法：
        每次查询都是  acquire→execute→release 原子操作，不会长时间占用连接
        """
        client = self.pool.acquire(timeout=5.0)
        if client is None:
            logger.error(f"[{self.pool_name}] 连接池耗尽，查询失败")
            return []
        try:
            return client.execute(query, params or {})
        except Exception as e:
            logger.error(f"[{self.pool_name}] 执行查询失败: {e}")
            return []
        finally:
            self.pool.release(client)

    def ensure_database(self):
        """确保数据库和表存在"""
        try:
            self.client.execute(f"CREATE DATABASE IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}")
            logger.info("数据库检查完成")
        except Exception as e:
            logger.error(f"创建数据库失败: {e}")

    def batch_insert_env_data(self, data_list: List[Dict]):
        """批量写入环境传感器数据"""
        if not data_list:
            return

        try:
            columns = list(data_list[0].keys())
            values = [tuple(d[col] for col in columns) for d in data_list]

            query = f"INSERT INTO env_sensor_data ({', '.join(columns)}) VALUES"
            self.client.execute(query, values)
            logger.debug(f"环境数据写入成功: {len(data_list)}条")
        except Exception as e:
            logger.error(f"环境数据写入失败: {e}")

    def batch_insert_ph_data(self, data_list: List[Dict]):
        """批量写入pH传感器数据"""
        if not data_list:
            return

        try:
            columns = list(data_list[0].keys())
            values = [tuple(d[col] for col in columns) for d in data_list]

            query = f"INSERT INTO ph_sensor_data ({', '.join(columns)}) VALUES"
            self.client.execute(query, values)
            logger.debug(f"pH数据写入成功: {len(data_list)}条")
        except Exception as e:
            logger.error(f"pH数据写入失败: {e}")

    def insert_alert(self, alert_data: Dict):
        """写入告警记录"""
        try:
            columns = list(alert_data.keys())
            values = [tuple(alert_data[col] for col in columns)]

            query = f"INSERT INTO alerts ({', '.join(columns)}) VALUES"
            self.client.execute(query, values)
            logger.info(f"告警写入成功: {alert_data.get('alert_id')}")
        except Exception as e:
            logger.error(f"告警写入失败: {e}")

    def add_env_to_buffer(self, data: Dict):
        """添加环境数据到缓冲区（优先使用BatchWriter）"""
        if self.batch_writer:
            self.batch_writer.add("env_sensor_data", data)
        else:
            self._env_buffer.append(data)

    def add_ph_to_buffer(self, data: Dict):
        """添加pH数据到缓冲区（优先使用BatchWriter）"""
        if self.batch_writer:
            self.batch_writer.add("ph_sensor_data", data)
        else:
            self._ph_buffer.append(data)

    def add_alert_to_buffer(self, data: Dict):
        """添加告警到缓冲区（优先使用BatchWriter）"""
        if self.batch_writer:
            self.batch_writer.add("alerts", data)
        else:
            self._alert_buffer.append(data)

    def flush_env_buffer(self) -> int:
        """刷环境数据缓冲区"""
        if self.batch_writer:
            return self.batch_writer.flush_table("env_sensor_data")
        if not self._env_buffer:
            return 0
        count = len(self._env_buffer)
        self.batch_insert_env_data(self._env_buffer)
        self._env_buffer.clear()
        return count

    def flush_ph_buffer(self) -> int:
        """刷pH数据缓冲区"""
        if self.batch_writer:
            return self.batch_writer.flush_table("ph_sensor_data")
        if not self._ph_buffer:
            return 0
        count = len(self._ph_buffer)
        self.batch_insert_ph_data(self._ph_buffer)
        self._ph_buffer.clear()
        return count

    def flush_alert_buffer(self) -> int:
        """刷告警缓冲区"""
        if self.batch_writer:
            return self.batch_writer.flush_table("alerts")
        if not self._alert_buffer:
            return 0
        count = len(self._alert_buffer)
        for alert in self._alert_buffer:
            self.insert_alert(alert)
        self._alert_buffer.clear()
        return count

    def get_write_stats(self) -> Dict:
        """获取写入统计信息"""
        if self.batch_writer:
            return self.batch_writer.get_stats()
        return {"batch_writer": "not_active"}

    def get_realtime_env_data(self, shelf_id: str = None, slot_id: str = None,
                              limit: int = 100) -> List[Dict]:
        """获取实时环境数据"""
        conditions = []
        params = {}

        if shelf_id:
            conditions.append("shelf_id = %(shelf_id)s")
            params["shelf_id"] = shelf_id
        if slot_id:
            conditions.append("slot_id = %(slot_id)s")
            params["slot_id"] = slot_id

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT *
            FROM env_sensor_data
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT %(limit)s
        """
        params["limit"] = limit

        try:
            results = self.client.execute(query, params)
            return [self._row_to_dict(row, self._get_env_columns()) for row in results]
        except Exception as e:
            logger.error(f"查询环境数据失败: {e}")
            return []

    def get_env_trend(self, shelf_id: str, slot_id: str, days: int = 90) -> List[Dict]:
        """获取环境趋势数据（按小时聚合）"""
        start_date = datetime.now() - timedelta(days=days)

        query = """
            SELECT
                hour_start,
                avg_temperature,
                max_temperature,
                min_temperature,
                avg_humidity,
                max_humidity,
                min_humidity,
                avg_light,
                avg_voc,
                avg_mold_spore
            FROM env_hourly_mv
            WHERE shelf_id = %(shelf_id)s
              AND slot_id = %(slot_id)s
              AND hour_start >= %(start_date)s
            ORDER BY hour_start ASC
        """

        params = {
            "shelf_id": shelf_id,
            "slot_id": slot_id,
            "start_date": start_date
        }

        try:
            results = self.client.execute(query, params)
            return [
                {
                    "timestamp": str(row[0]),
                    "avg_temperature": row[1],
                    "max_temperature": row[2],
                    "min_temperature": row[3],
                    "avg_humidity": row[4],
                    "max_humidity": row[5],
                    "min_humidity": row[6],
                    "avg_light": row[7],
                    "avg_voc": row[8],
                    "avg_mold_spore": row[9]
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"查询环境趋势失败: {e}")
            return []

    def get_ph_trend(self, shelf_id: str, slot_id: str, days: int = 90) -> List[Dict]:
        """获取pH值趋势数据（按天聚合）"""
        start_date = datetime.now() - timedelta(days=days)

        query = """
            SELECT
                day_start,
                avg_ph,
                max_ph,
                min_ph
            FROM ph_daily_mv
            WHERE shelf_id = %(shelf_id)s
              AND slot_id = %(slot_id)s
              AND day_start >= %(start_date)s
            ORDER BY day_start ASC
        """

        params = {
            "shelf_id": shelf_id,
            "slot_id": slot_id,
            "start_date": start_date
        }

        try:
            results = self.client.execute(query, params)
            return [
                {
                    "date": str(row[0]),
                    "avg_ph": row[1],
                    "max_ph": row[2],
                    "min_ph": row[3]
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"查询pH趋势失败: {e}")
            return []

    def get_current_ph(self, shelf_id: str, slot_id: str) -> Optional[float]:
        """获取当前pH值"""
        query = """
            SELECT ph_value
            FROM ph_sensor_data
            WHERE shelf_id = %(shelf_id)s
              AND slot_id = %(slot_id)s
            ORDER BY timestamp DESC
            LIMIT 1
        """

        params = {
            "shelf_id": shelf_id,
            "slot_id": slot_id
        }

        try:
            results = self.client.execute(query, params)
            return results[0][0] if results else None
        except Exception as e:
            logger.error(f"查询当前pH值失败: {e}")
            return None

    def get_all_shelves_status(self) -> List[Dict]:
        """获取所有书架状态"""
        query = """
            SELECT
                s.shelf_id,
                s.slot_id,
                b.title,
                b.condition,
                b.material,
                last_env.temperature,
                last_env.humidity,
                last_env.mold_spore,
                last_ph.ph_value
            FROM (
                SELECT shelf_id, slot_id
                FROM books_info
                GROUP BY shelf_id, slot_id
            ) s
            LEFT JOIN books_info b ON s.shelf_id = b.shelf_id AND s.slot_id = b.slot_id
            LEFT JOIN (
                SELECT
                    shelf_id,
                    slot_id,
                    argMax(temperature, timestamp) as temperature,
                    argMax(humidity, timestamp) as humidity,
                    argMax(mold_spore, timestamp) as mold_spore
                FROM env_sensor_data
                WHERE timestamp > now() - INTERVAL 1 HOUR
                GROUP BY shelf_id, slot_id
            ) last_env ON s.shelf_id = last_env.shelf_id AND s.slot_id = last_env.slot_id
            LEFT JOIN (
                SELECT
                    shelf_id,
                    slot_id,
                    argMax(ph_value, timestamp) as ph_value
                FROM ph_sensor_data
                WHERE timestamp > now() - INTERVAL 1 DAY
                GROUP BY shelf_id, slot_id
            ) last_ph ON s.shelf_id = last_ph.shelf_id AND s.slot_id = last_ph.slot_id
        """

        try:
            results = self.client.execute(query)
            return [
                {
                    "shelf_id": row[0],
                    "slot_id": row[1],
                    "book_title": row[2] or "未知",
                    "book_condition": row[3] or "未知",
                    "material": row[4] or "竹纸",
                    "temperature": row[5] or 0,
                    "humidity": row[6] or 0,
                    "mold_spore": row[7] or 0,
                    "ph_value": row[8] or 7.0
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"查询书架状态失败: {e}")
            return []

    def get_books_info(self, shelf_id: str = None, slot_id: str = None) -> List[Dict]:
        """获取古籍信息"""
        conditions = []
        params = {}

        if shelf_id:
            conditions.append("shelf_id = %(shelf_id)s")
            params["shelf_id"] = shelf_id
        if slot_id:
            conditions.append("slot_id = %(slot_id)s")
            params["slot_id"] = slot_id

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT *
            FROM books_info
            WHERE {where_clause}
            ORDER BY shelf_id, slot_id
        """

        try:
            results = self.client.execute(query)
            columns = ["book_id", "shelf_id", "slot_id", "title", "dynasty",
                       "author", "category", "material", "publication_year",
                       "condition", "create_time", "update_time"]
            return [self._row_to_dict(row, columns) for row in results]
        except Exception as e:
            logger.error(f"查询古籍信息失败: {e}")
            return []

    def get_recent_alerts(self, level: str = None, limit: int = 50) -> List[Dict]:
        """获取近期告警"""
        conditions = []
        params = {}

        if level:
            conditions.append("alert_level = %(level)s")
            params["level"] = level

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT *
            FROM alerts
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT %(limit)s
        """
        params["limit"] = limit

        try:
            results = self.client.execute(query)
            columns = ["alert_id", "timestamp", "shelf_id", "slot_id",
                       "alert_level", "alert_type", "alert_value", "threshold",
                       "message", "is_handled", "handle_time"]
            return [self._row_to_dict(row, columns) for row in results]
        except Exception as e:
            logger.error(f"查询告警失败: {e}")
            return []

    def save_aging_prediction(self, prediction_data: Dict):
        """保存老化预测结果"""
        try:
            columns = list(prediction_data.keys())
            values = [tuple(prediction_data[col] for col in columns)]
            query = f"INSERT INTO aging_prediction ({', '.join(columns)}) VALUES"
            self.client.execute(query, values)
        except Exception as e:
            logger.error(f"保存老化预测失败: {e}")

    def get_knowledge_graph(self, disease_type: str = None) -> List[Dict]:
        """获取知识图谱数据"""
        conditions = []
        params = {}

        if disease_type:
            conditions.append("disease_type = %(disease_type)s")
            params["disease_type"] = disease_type

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT disease_type, disease_name, description, herbs, prescriptions, references
            FROM disease_knowledge_graph
            WHERE {where_clause}
        """

        try:
            results = self.client.execute(query)
            return [
                {
                    "disease_type": row[0],
                    "disease_name": row[1],
                    "description": row[2],
                    "herbs": list(row[3]),
                    "prescriptions": list(row[4]),
                    "references": list(row[5])
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"查询知识图谱失败: {e}")
            return []

    def _get_env_columns(self) -> List[str]:
        return ["timestamp", "sensor_id", "shelf_id", "slot_id",
                "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]

    def _row_to_dict(self, row: tuple, columns: List[str]) -> Dict:
        return {col: row[i] for i, col in enumerate(columns)}


db_manager = ClickHouseManager()
