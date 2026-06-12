"""
ClickHouse 数据库连接与操作封装
"""
import logging
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
from clickhouse_driver import Client
from clickhouse_connect import get_client
from clickhouse_connect.driver.exceptions import ClickHouseError

from .config import settings

logger = logging.getLogger(__name__)


class ClickHouseManager:
    _instance: Optional["ClickHouseManager"] = None
    _client: Optional[Any] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connect()
        return cls._instance

    def _connect(self):
        try:
            self._client = get_client(
                host=settings.clickhouse_host,
                port=settings.clickhouse_port,
                username=settings.clickhouse_user,
                password=settings.clickhouse_password,
                database=settings.clickhouse_database,
                settings={"insert_deduplicate": 0},
            )
            logger.info(f"ClickHouse connected: {settings.clickhouse_host}:{settings.clickhouse_port}")
        except Exception as e:
            logger.error(f"ClickHouse connection failed: {e}")
            raise

    @property
    def client(self):
        if self._client is None:
            self._connect()
        return self._client

    def reconnect(self):
        self.close()
        self._connect()

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def query(self, sql: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        try:
            result = self.client.query(sql, parameters=params or {})
            columns = [col[0] for col in result.result_columns]
            return [dict(zip(columns, row)) for row in result.result_rows]
        except ClickHouseError as e:
            logger.error(f"ClickHouse query error: {e}, SQL: {sql}")
            self.reconnect()
            raise

    def query_one(self, sql: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, data: List[Dict[str, Any]], columns: Optional[List[str]] = None):
        if not data:
            return
        try:
            cols = columns or list(data[0].keys())
            rows = [[row[c] for c in cols] for row in data]
            self.client.insert(table, rows, column_names=cols)
            logger.debug(f"Inserted {len(data)} rows into {table}")
        except ClickHouseError as e:
            logger.error(f"ClickHouse insert error into {table}: {e}")
            raise

    def execute(self, sql: str, params: Optional[Dict] = None) -> int:
        try:
            return self.client.command(sql, parameters=params or {})
        except ClickHouseError as e:
            logger.error(f"ClickHouse execute error: {e}, SQL: {sql}")
            raise


def get_ch() -> ClickHouseManager:
    return ClickHouseManager()
