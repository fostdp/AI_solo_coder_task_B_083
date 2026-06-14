import logging
import threading
import time
from collections import defaultdict
from typing import List, Dict, Any, Optional

import requests

from .config import settings

logger = logging.getLogger(__name__)


class ClickHouseClient:
    def __init__(self):
        self._base_url = f"http://{settings.clickhouse_host}:{settings.clickhouse_port}"
        self._db = settings.clickhouse_database
        self._params = {
            "user": settings.clickhouse_user,
            "password": settings.clickhouse_password,
            "database": self._db,
        }

    def query(self, sql: str, params: Optional[Dict] = None) -> List[Dict]:
        formatted_sql = self._format_query(sql, params)
        formatted_sql += " FORMAT JSON"
        try:
            resp = requests.post(
                self._base_url, data=formatted_sql.encode("utf-8"), params=self._params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except Exception as e:
            logger.error(f"ClickHouse query error: {e}")
            return []

    def query_one(self, sql: str, params: Optional[Dict] = None) -> Optional[Dict]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Optional[Dict] = None) -> bool:
        formatted_sql = self._format_query(sql, params)
        try:
            resp = requests.post(
                self._base_url, data=formatted_sql.encode("utf-8"), params=self._params, timeout=15
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"ClickHouse execute error: {e}")
            return False

    def batch_insert(self, table: str, columns: List[str], rows: List[List[Any]]) -> bool:
        if not rows:
            return True
        col_def = ", ".join(columns)
        csv_lines = "\n".join(",".join(str(v) for v in row) for row in rows)
        sql = f"INSERT INTO {table} ({col_def}) FORMAT CSV"
        try:
            resp = requests.post(
                self._base_url, data=csv_lines.encode("utf-8"), params=self._params, timeout=30
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"ClickHouse batch insert error: {e}")
            return False

    def _format_query(self, sql: str, params: Optional[Dict] = None) -> str:
        if not params:
            return sql
        result = sql
        for k, v in params.items():
            placeholder = "{" + k + ":String}"
            if placeholder in result:
                result = result.replace(placeholder, f"'{v}'")
            placeholder_int = "{" + k + ":Int64}"
            if placeholder_int in result:
                result = result.replace(placeholder_int, str(v))
            placeholder_dt = "{" + k + ":DateTime64(3)}"
            if placeholder_dt in result:
                result = result.replace(placeholder_dt, f"'{v}'")
        return result


class BatchWriter:
    def __init__(
        self,
        client: ClickHouseClient,
        batch_size: int = 500,
        flush_interval_sec: float = 30.0,
        max_retries: int = 3,
    ):
        self._client = client
        self._batch_size = batch_size
        self._flush_interval = flush_interval_sec
        self._max_retries = max_retries
        self._buffers: Dict[str, Dict[str, List]] = defaultdict(lambda: {"cols": [], "rows": []})
        self._lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_flush = time.time()
        self._stats = {"total_inserted": 0, "total_batches": 0, "failed_batches": 0, "retry_count": 0}

    def start(self):
        if self._flush_thread and self._flush_thread.is_alive():
            return
        self._stop_event.clear()
        self._flush_thread = threading.Thread(target=self._flush_loop, name="ch_batch_writer", daemon=True)
        self._flush_thread.start()
        logger.info(f"BatchWriter started: batch_size=%d, flush_interval=%.1fs", self._batch_size, self._flush_interval)

    def stop(self, flush: bool = True):
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=10)
            self._flush_thread = None
        if flush:
            self.flush_all(force=True)
        logger.info(f"BatchWriter stopped. stats=%s", self._stats)

    def add(self, table: str, columns: List[str], row: List[Any]):
        with self._lock:
            buf = self._buffers[table]
            if not buf["cols"]:
                buf["cols"] = list(columns)
            buf["rows"].append(row)
            if len(buf["rows"]) >= self._batch_size:
                self._flush_table_locked(table)

    def add_many(self, table: str, columns: List[str], rows: List[List[Any]]):
        with self._lock:
            buf = self._buffers[table]
            if not buf["cols"]:
                buf["cols"] = list(columns)
            buf["rows"].extend(rows)
            if len(buf["rows"]) >= self._batch_size:
                self._flush_table_locked(table)

    def flush_all(self, force: bool = False) -> int:
        flushed = 0
        with self._lock:
            tables = list(self._buffers.keys())
        for table in tables:
            with self._lock:
                buf = self._buffers.get(table)
                if not buf or not buf["rows"]:
                    continue
                if not force and len(buf["rows"]) < self._batch_size:
                    continue
                rows = buf["rows"]
                cols = buf["cols"]
                buf["rows"] = []
            if self._insert_with_retry(table, cols, rows):
                flushed += len(rows)
                self._stats["total_inserted"] += len(rows)
                self._stats["total_batches"] += 1
            else:
                with self._lock:
                    buf = self._buffers.setdefault(table, {"cols": cols, "rows": []})
                    buf["rows"].extend(rows)
                self._stats["failed_batches"] += 1
        self._last_flush = time.time()
        return flushed

    def _flush_loop(self):
        while not self._stop_event.is_set():
            try:
                time.sleep(min(1.0, self._flush_interval / 3))
                elapsed = time.time() - self._last_flush
                if elapsed >= self._flush_interval:
                    self.flush_all(force=True)
            except Exception as e:
                logger.error(f"BatchWriter flush loop error: {e}")
        self.flush_all(force=True)

    def _flush_table_locked(self, table: str):
        buf = self._buffers.get(table)
        if not buf or len(buf["rows"]) < self._batch_size:
            return
        rows = buf["rows"]
        cols = buf["cols"]
        buf["rows"] = []
        if self._insert_with_retry(table, cols, rows):
            self._stats["total_inserted"] += len(rows)
            self._stats["total_batches"] += 1
        else:
            buf["rows"].extend(rows)
            self._stats["failed_batches"] += 1

    def _insert_with_retry(self, table: str, columns: List[str], rows: List[List[Any]]) -> bool:
        if not rows:
            return True
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            try:
                ok = self._client.batch_insert(table, columns, rows)
                if ok:
                    return True
            except Exception as e:
                last_err = e
            if attempt < self._max_retries:
                wait = 0.5 * (2 ** (attempt - 1))
                time.sleep(wait)
                self._stats["retry_count"] += 1
                logger.warning(f"Batch insert retry {attempt}/{self._max_retries} for table {table}: {last_err}")
        logger.error(f"Batch insert failed after {self._max_retries} retries for table {table} ({len(rows)} rows)")
        return False

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats, pending=sum(len(b["rows"]) for b in self._buffers.values()))

    def queue_size(self) -> int:
        with self._lock:
            return sum(len(b["rows"]) for b in self._buffers.values())


_ch_client: Optional[ClickHouseClient] = None
_batch_writer: Optional[BatchWriter] = None


def get_ch() -> ClickHouseClient:
    global _ch_client
    if _ch_client is None:
        _ch_client = ClickHouseClient()
    return _ch_client


def get_batch_writer() -> BatchWriter:
    global _batch_writer
    if _batch_writer is None:
        _batch_writer = BatchWriter(
            client=get_ch(),
            batch_size=settings.batch_size,
            flush_interval_sec=settings.batch_flush_interval,
            max_retries=settings.batch_max_retries,
        )
    return _batch_writer
