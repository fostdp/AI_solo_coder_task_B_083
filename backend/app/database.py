import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from clickhouse_driver import Client
from .config import settings

logger = logging.getLogger(__name__)


class ClickHouseManager:
    """
    ClickHouse数据库管理器
    负责连接管理、数据写入、查询
    """

    def __init__(self):
        self.client: Optional[Client] = None
        self._env_buffer: List[Dict] = []
        self._ph_buffer: List[Dict] = []
        self._alert_buffer: List[Dict] = []

    def connect(self):
        """建立连接"""
        try:
            self.client = Client(
                host=settings.CLICKHOUSE_HOST,
                port=settings.CLICKHOUSE_PORT,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=settings.CLICKHOUSE_DATABASE
            )
            logger.info("ClickHouse连接成功")
            return True
        except Exception as e:
            logger.error(f"ClickHouse连接失败: {e}")
            return False

    def close(self):
        """关闭连接"""
        if self.client:
            self.client.disconnect()
            self.client = None

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
        """添加环境数据到缓冲区"""
        self._env_buffer.append(data)

    def add_ph_to_buffer(self, data: Dict):
        """添加pH数据到缓冲区"""
        self._ph_buffer.append(data)

    def add_alert_to_buffer(self, data: Dict):
        """添加告警到缓冲区"""
        self._alert_buffer.append(data)

    def flush_env_buffer(self) -> int:
        """刷环境数据缓冲区"""
        if not self._env_buffer:
            return 0
        count = len(self._env_buffer)
        self.batch_insert_env_data(self._env_buffer)
        self._env_buffer.clear()
        return count

    def flush_ph_buffer(self) -> int:
        """刷pH数据缓冲区"""
        if not self._ph_buffer:
            return 0
        count = len(self._ph_buffer)
        self.batch_insert_ph_data(self._ph_buffer)
        self._ph_buffer.clear()
        return count

    def flush_alert_buffer(self) -> int:
        """刷告警缓冲区"""
        if not self._alert_buffer:
            return 0
        count = len(self._alert_buffer)
        for alert in self._alert_buffer:
            self.insert_alert(alert)
        self._alert_buffer.clear()
        return count

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
                    "temperature": row[4] or 0,
                    "humidity": row[5] or 0,
                    "mold_spore": row[6] or 0,
                    "ph_value": row[7] or 7.0
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
