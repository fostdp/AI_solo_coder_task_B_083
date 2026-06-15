"""
批量写入模块
负责从队列读取数据，批量写入ClickHouse
"""
import asyncio
import logging
import time
import threading
import queue
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass

from clickhouse_driver import Client

from ..core.config import config
from ..core.messages import (
    Message,
    SensorData,
    EnvSensorData,
    PhSensorData,
    AlertMessage,
    AgingPredictionResult,
    MoldPredictionResult,
)
from ..core.queue_manager import queue_manager, AsyncQueueWrapper

logger = logging.getLogger(__name__)


@dataclass
class WriterStats:
    """写入统计"""
    total_writes: int = 0
    total_records: int = 0
    total_errors: int = 0
    total_retries: int = 0
    retries: int = 0
    failed_writes: int = 0
    dropped_records: int = 0
    last_write_time: Optional[str] = None


class BatchWriter:
    """
    ClickHouse批量写入器
    支持按表队列、双触发条件（数量/时间）、重试机制
    """

    DEFAULT_BATCH_SIZE = 500
    DEFAULT_FLUSH_INTERVAL = 30
    DEFAULT_MAX_QUEUE_SIZE = 10000
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_COUNT = 3
    DEFAULT_RETRY_DELAY = 1.0

    def __init__(
        self,
        client: Client = None,
        batch_size: int = None,
        flush_interval: int = None,
        max_queue_size: int = None,
        retry_count: int = None,
        max_retries: int = None,
        retry_delay: float = None,
    ):
        bw_config = config.batch_writer
        self.client = client
        self.batch_size = batch_size or bw_config.get("batch_size", self.DEFAULT_BATCH_SIZE)
        self.flush_interval = flush_interval or bw_config.get("flush_interval", self.DEFAULT_FLUSH_INTERVAL)
        self.max_queue_size = max_queue_size or bw_config.get("max_queue_size", self.DEFAULT_MAX_QUEUE_SIZE)
        self.retry_count = retry_count or max_retries or self.DEFAULT_MAX_RETRIES
        self.max_retries = self.retry_count
        self.retry_delay = retry_delay or self.DEFAULT_RETRY_DELAY

        self._queues: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}
        self._table_columns: Dict[str, List[str]] = {}
        self._last_flush: Dict[str, float] = {}
        self._locks: Dict[str, threading.Lock] = {}

        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
        self._stats = WriterStats()

        self._register_default_tables()
        self._on_flush_callback: Optional[Callable[[str, int], None]] = None

    def _register_default_tables(self):
        """从配置注册默认表"""
        tables_config = config.batch_writer.get("tables", [])
        for table_config in tables_config:
            table_name = table_config["name"]
            columns = table_config["columns"]
            self.register_table(table_name, columns)

    def register_table(self, table_name: str, columns: List[str]):
        """注册数据表及其列名"""
        self._table_columns[table_name] = columns
        self._last_flush[table_name] = time.time()
        self._locks[table_name] = threading.Lock()
        self._queues[table_name] = queue.Queue(maxsize=self.max_queue_size)
        logger.info(f"BatchWriter注册表: {table_name}, 列: {columns}")

    def set_flush_callback(self, callback: Callable[[str, int], None]):
        """设置flush回调"""
        self._on_flush_callback = callback

    def add_write_callback(self, callback: Callable[[str, int], None]):
        """添加写入回调（兼容API）"""
        self._on_flush_callback = callback

    def get_queue_size(self, table_name: str = None) -> int:
        """获取队列大小（兼容API）
        如果table_name为None，返回所有表队列的总大小
        """
        if table_name is None:
            return sum(q.qsize() for q in self._queues.values())
        q = self._queues.get(table_name)
        return q.qsize() if q else 0

    def add(self, table_name: str, data: Dict[str, Any]) -> bool:
        """添加单条数据到写入队列"""
        if table_name not in self._queues:
            self.register_table(table_name, list(data.keys()))

        q = self._queues[table_name]
        try:
            if q.full():
                try:
                    q.get_nowait()
                    self._stats.dropped_records += 1
                    logger.warning(f"队列 {table_name} 已满，丢弃最旧数据")
                except queue.Empty:
                    pass
            q.put_nowait(data)
            return True
        except Exception as e:
            logger.error(f"BatchWriter添加数据失败 {table_name}: {e}")
            return False

    def add_batch(self, table_name: str, data_list: List[Dict[str, Any]]) -> int:
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
        """写入单个表的所有缓冲数据"""
        q = self._queues.get(table_name)
        if not q or q.empty():
            return 0

        with self._locks.get(table_name, threading.Lock()):
            data_list = []
            try:
                while not q.empty() and len(data_list) < self.batch_size:
                    data_list.append(q.get_nowait())
            except queue.Empty:
                pass

            if not data_list:
                return 0

            total_written = 0
            retry_attempts = 0
            remaining_data = list(data_list)

            while remaining_data and retry_attempts <= self.retry_count:
                try:
                    columns = self._table_columns.get(table_name)
                    if not columns:
                        columns = list(remaining_data[0].keys())
                        self._table_columns[table_name] = columns

                    values = [tuple(d.get(col) for col in columns) for d in remaining_data]
                    query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES"

                    if self.client is None:
                        # 测试场景：模拟成功写入
                        logger.warning(f"BatchWriter client为None，模拟写入 {table_name}: {len(remaining_data)}条")
                        total_written = len(remaining_data)
                        self._stats.total_writes += 1
                        self._stats.total_records += total_written
                        self._stats.last_write_time = time.strftime("%Y-%m-%d %H:%M:%S")
                        self._last_flush[table_name] = time.time()
                        remaining_data = []
                    else:
                        self.client.execute(query, values)

                        total_written = len(remaining_data)
                        self._stats.total_writes += 1
                        self._stats.total_records += total_written
                        self._stats.last_write_time = time.strftime("%Y-%m-%d %H:%M:%S")
                        self._last_flush[table_name] = time.time()

                    logger.debug(f"BatchWriter写入 {table_name}: {total_written}条")

                    if self._on_flush_callback:
                        try:
                            self._on_flush_callback(table_name, total_written)
                        except Exception as e:
                            logger.error(f"flush回调异常: {e}")

                    return total_written

                except Exception as e:
                    retry_attempts += 1
                    self._stats.total_errors += 1
                    self._stats.total_retries += 1
                    self._stats.retries += 1

                    if retry_attempts <= self.retry_count:
                        logger.warning(
                            f"BatchWriter写入 {table_name} 失败 (重试 {retry_attempts}/{self.retry_count}): {e}"
                        )
                        time.sleep(self.retry_delay)
                    else:
                        logger.error(
                            f"BatchWriter写入 {table_name} 失败，已耗尽重试次数: {e}"
                        )
                        self._stats.failed_writes += 1
                        for d in remaining_data:
                            try:
                                q.put_nowait(d)
                            except queue.Full:
                                self._stats.dropped_records += 1

            return total_written

    def flush_all(self) -> Dict[str, int]:
        """立即flush所有表"""
        results = {}
        for table_name in list(self._queues.keys()):
            total = 0
            count = self._flush_table(table_name)
            while count > 0:
                total += count
                count = self._flush_table(table_name)
            results[table_name] = total
        return results

    def flush_table(self, table_name: str) -> int:
        """立即flush指定表"""
        total = 0
        count = self._flush_table(table_name)
        while count > 0:
            total += count
            count = self._flush_table(table_name)
        return total

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（同时兼容扁平格式和嵌套格式）"""
        queue_sizes = {name: q.qsize() for name, q in self._queues.items()}
        total_queue_size = sum(queue_sizes.values())
        tables_with_data = [name for name, size in queue_sizes.items() if size > 0]
        flat_stats = {
            "total_writes": self._stats.total_writes,
            "total_records": self._stats.total_records,
            "total_errors": self._stats.total_errors,
            "total_retries": self._stats.total_retries,
            "retries": self._stats.retries,
            "failed_writes": self._stats.failed_writes,
            "dropped_records": self._stats.dropped_records,
            "last_write_time": self._stats.last_write_time,
            "batch_size": self.batch_size,
            "flush_interval": self.flush_interval,
            "queue_size": total_queue_size,
            "tables": tables_with_data,
            "per_table_queue_size": {name: size for name, size in queue_sizes.items() if size > 0},
        }
        flat_stats.update({
            "writer": dict(flat_stats),
            "queues": queue_sizes,
        })
        return flat_stats

    def reset_stats(self):
        """重置统计信息"""
        self._stats = WriterStats()


class BatchWriterService:
    """
    批量写入服务
    监听多个队列，将消息转换为ClickHouse记录并批量写入
    """

    TABLE_MAP = {
        "environment": "env_sensor_data",
        "ph": "ph_sensor_data",
        "alert": "alerts",
    }

    def __init__(self, clickhouse_client: Client):
        self.writer = BatchWriter(clickhouse_client)
        self._input_queues: List[AsyncQueueWrapper] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._lock = threading.Lock()

    def register_input_queue(self, queue: AsyncQueueWrapper):
        """注册输入队列"""
        self._input_queues.append(queue)
        logger.info(f"BatchWriterService注册输入队列: {queue.name}")

    def _convert_message(self, msg: Message) -> Optional[Tuple[str, Dict[str, Any]]]:
        """将消息转换为ClickHouse记录"""
        if isinstance(msg, EnvSensorData):
            record = {
                "timestamp": msg.timestamp,
                "sensor_id": msg.sensor_id,
                "shelf_id": msg.shelf_id,
                "slot_id": msg.slot_id,
                "temperature": msg.temperature,
                "humidity": msg.humidity,
                "light": msg.light,
                "voc": msg.voc,
                "mold_spore": msg.mold_spore,
                "sensor_type": "environment",
            }
            return ("env_sensor_data", record)

        elif isinstance(msg, PhSensorData):
            record = {
                "timestamp": msg.timestamp,
                "sensor_id": msg.sensor_id,
                "shelf_id": msg.shelf_id,
                "slot_id": msg.slot_id,
                "ph_value": msg.ph_value,
                "sensor_type": "ph",
            }
            return ("ph_sensor_data", record)

        elif isinstance(msg, AlertMessage):
            record = {
                "alert_id": msg.alert_id,
                "timestamp": msg.timestamp,
                "shelf_id": msg.shelf_id,
                "slot_id": msg.slot_id,
                "alert_level": msg.alert_level,
                "alert_type": msg.alert_type,
                "alert_value": msg.alert_value,
                "threshold": msg.threshold,
                "message": msg.message,
                "is_handled": 0,
            }
            return ("alerts", record)

        elif isinstance(msg, AgingPredictionResult):
            record = {
                "timestamp": msg.timestamp,
                "shelf_id": msg.shelf_id,
                "slot_id": msg.slot_id,
                "paper_type": msg.paper_type,
                "ph_decay_rate": msg.ph_decay_rate,
                "predicted_lifetime_years": msg.predicted_lifetime_years,
                "ph_30d": msg.ph_predictions.get(30, 0),
                "ph_90d": msg.ph_predictions.get(90, 0),
                "ph_180d": msg.ph_predictions.get(180, 0),
                "ph_365d": msg.ph_predictions.get(365, 0),
                "severity": msg.severity,
            }
            return ("aging_prediction", record)

        elif isinstance(msg, MoldPredictionResult):
            record = {
                "timestamp": msg.timestamp,
                "shelf_id": msg.shelf_id,
                "slot_id": msg.slot_id,
                "risk_score": msg.risk_score,
                "risk_level": msg.risk_level,
                "growth_rate": msg.growth_rate,
                "predicted_spores_7d": msg.predicted_spores_7d,
                "predicted_spores_30d": msg.predicted_spores_30d,
                "is_active_mold": 1 if msg.is_active_mold else 0,
            }
            return ("mold_prediction", record)

        else:
            logger.debug(f"忽略未知消息类型: {msg.message_type}")
            return None

    async def _consume_queue(self, input_queue: AsyncQueueWrapper):
        """消费单个队列"""
        logger.info(f"开始消费队列: {input_queue.name}")
        while self._running:
            try:
                msg = await input_queue.get(timeout=1.0)
                if msg is None:
                    continue

                result = self._convert_message(msg)
                if result:
                    table_name, record = result
                    with self._lock:
                        self.writer.add(table_name, record)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"消费队列 {input_queue.name} 异常: {e}")
                await asyncio.sleep(0.1)
        logger.info(f"停止消费队列: {input_queue.name}")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        self.writer.start()

        for q in self._input_queues:
            task = asyncio.create_task(self._consume_queue(q))
            self._tasks.append(task)

        logger.info(f"BatchWriterService已启动，监听 {len(self._input_queues)} 个队列")

    async def stop(self):
        """停止服务"""
        self._running = False

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()
        self.writer.stop()

        await queue_manager.flush_all_async()
        logger.info("BatchWriterService已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.writer.get_stats()
