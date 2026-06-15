import pytest
import time
import threading
from unittest.mock import MagicMock, patch, call
from typing import Dict, Any, List

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.batch_writer import BatchWriter


class TestBatchWriterInitialization:
    def test_default_values(self):
        writer = BatchWriter()
        
        assert writer.batch_size == 500
        assert writer.flush_interval == 30
        assert writer.max_queue_size == 10000
        assert writer.max_retries == 3
        assert writer._running is False

    def test_custom_values(self, mock_clickhouse_client):
        writer = BatchWriter(
            client=mock_clickhouse_client,
            batch_size=100,
            flush_interval=5,
            max_queue_size=1000,
            max_retries=5,
        )
        
        assert writer.batch_size == 100
        assert writer.flush_interval == 5
        assert writer.max_queue_size == 1000
        assert writer.max_retries == 5
        assert writer.client is mock_clickhouse_client

    def test_default_constants(self):
        assert BatchWriter.DEFAULT_BATCH_SIZE == 500
        assert BatchWriter.DEFAULT_FLUSH_INTERVAL == 30
        assert BatchWriter.DEFAULT_MAX_QUEUE_SIZE == 10000
        assert BatchWriter.DEFAULT_MAX_RETRIES == 3


class TestBatchWriterRegisterTable:
    def test_register_table(self, batch_writer):
        columns = ["col1", "col2", "col3"]
        batch_writer.register_table("test_table", columns)
        
        assert "test_table" in batch_writer._table_columns
        assert batch_writer._table_columns["test_table"] == columns
        assert "test_table" in batch_writer._last_flush

    def test_register_multiple_tables(self, batch_writer):
        initial_count = len(batch_writer._table_columns)
        batch_writer.register_table("table1", ["col1", "col2"])
        batch_writer.register_table("table2", ["col3", "col4", "col5"])
        
        assert len(batch_writer._table_columns) == initial_count + 2
        assert batch_writer._table_columns["table1"] == ["col1", "col2"]
        assert batch_writer._table_columns["table2"] == ["col3", "col4", "col5"]


class TestBatchWriterAdd:
    def test_add_single_record(self, batch_writer):
        data = {"col1": "value1", "col2": "value2"}
        result = batch_writer.add("test_table", data)
        
        assert result is True
        assert batch_writer.get_queue_size("test_table") == 1

    def test_add_multiple_records(self, batch_writer):
        for i in range(5):
            batch_writer.add("test_table", {"id": i})
        
        assert batch_writer.get_queue_size("test_table") == 5

    def test_add_batch(self, batch_writer):
        data_list = [{"id": i} for i in range(10)]
        count = batch_writer.add_batch("test_table", data_list)
        
        assert count == 10
        assert batch_writer.get_queue_size("test_table") == 10

    def test_add_batch_partial_failure(self, batch_writer):
        with patch.object(batch_writer, 'add') as mock_add:
            mock_add.side_effect = [True, False, True, False, True]
            
            data_list = [{"id": i} for i in range(5)]
            count = batch_writer.add_batch("test_table", data_list)
            
            assert count == 3
            assert mock_add.call_count == 5

    def test_add_queue_full_drops_oldest(self):
        writer = BatchWriter(batch_size=10, max_queue_size=3)
        
        writer.add("test_table", {"id": 1})
        writer.add("test_table", {"id": 2})
        writer.add("test_table", {"id": 3})
        
        assert writer.get_queue_size("test_table") == 3
        
        writer.add("test_table", {"id": 4})
        
        assert writer.get_queue_size("test_table") == 3
        
        stats = writer.get_stats()
        assert stats["dropped_records"] == 1

    def test_add_exception_returns_false(self, batch_writer):
        with patch.object(batch_writer._queues['test_table'], 'put_nowait') as mock_put:
            mock_put.side_effect = Exception("Test error")
            
            result = batch_writer.add("test_table", {"id": 1})
            
            assert result is False

    def test_add_creates_new_table_queue(self, batch_writer):
        assert "new_table" not in batch_writer._queues
        
        batch_writer.add("new_table", {"id": 1})
        
        assert "new_table" in batch_writer._queues
        assert batch_writer.get_queue_size("new_table") == 1


class TestBatchWriterFlush:
    def test_flush_table_with_client(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table(
            "env_sensor_data",
            ["timestamp", "sensor_id", "temperature", "humidity"]
        )
        
        for i in range(5):
            writer.add("env_sensor_data", {
                "timestamp": f"2024-01-15T10:30:0{i}",
                "sensor_id": f"sensor_{i}",
                "temperature": 20.0 + i,
                "humidity": 50.0 + i,
            })
        
        count = writer.flush_table("env_sensor_data")
        
        assert count == 5
        assert mock_clickhouse_client.execute.called
        call_args = mock_clickhouse_client.execute.call_args
        assert "INSERT INTO env_sensor_data" in call_args[0][0]
        assert len(call_args[0][1]) == 5

    def test_flush_empty_table(self, batch_writer):
        count = batch_writer.flush_table("empty_table")
        
        assert count == 0

    def test_flush_all(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("table1", ["col1", "col2"])
        writer.register_table("table2", ["col3", "col4"])
        
        for i in range(3):
            writer.add("table1", {"col1": i, "col2": i * 2})
        for i in range(5):
            writer.add("table2", {"col3": i, "col4": i * 3})
        
        results = writer.flush_all()
        
        assert results["table1"] == 3
        assert results["table2"] == 5
        assert mock_clickhouse_client.execute.call_count == 2

    def test_flush_table_auto_infer_columns(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        
        writer.add("auto_table", {"col1": 1, "col2": 2, "col3": 3})
        writer.add("auto_table", {"col1": 4, "col2": 5, "col3": 6})
        
        count = writer.flush_table("auto_table")
        
        assert count == 2
        assert "auto_table" in writer._table_columns
        assert set(writer._table_columns["auto_table"]) == {"col1", "col2", "col3"}

    def test_flush_triggered_by_size(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=5, flush_interval=60)
        writer.register_table("test_table", ["col1", "col2"])
        
        for i in range(5):
            writer.add("test_table", {"col1": i, "col2": i * 2})
        
        writer._flush_table("test_table")
        
        assert mock_clickhouse_client.execute.called
        stats = writer.get_stats()
        assert stats["total_writes"] == 1
        assert stats["total_records"] == 5

    def test_flush_triggered_by_time(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=100, flush_interval=1)
        writer.register_table("test_table", ["col1", "col2"])
        
        writer.add("test_table", {"col1": 1, "col2": 2})
        
        writer._last_flush["test_table"] = time.time() - 2
        
        writer._flush_table("test_table")
        
        assert mock_clickhouse_client.execute.called
        stats = writer.get_stats()
        assert stats["total_writes"] == 1

    def test_flush_with_callback(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("test_table", ["col1", "col2"])
        
        callback_results = []
        
        def callback(table_name: str, count: int):
            callback_results.append((table_name, count))
        
        writer.add_write_callback(callback)
        
        for i in range(3):
            writer.add("test_table", {"col1": i, "col2": i * 2})
        
        writer.flush_table("test_table")
        
        assert len(callback_results) == 1
        assert callback_results[0] == ("test_table", 3)

    def test_flush_callback_exception(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("test_table", ["col1", "col2"])
        
        def bad_callback(table_name: str, count: int):
            raise Exception("Callback error")
        
        writer.add_write_callback(bad_callback)
        
        writer.add("test_table", {"col1": 1, "col2": 2})
        
        try:
            writer.flush_table("test_table")
        except Exception:
            pytest.fail("Callback exception should not propagate")

    def test_flush_large_batch(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("test_table", ["col1", "col2"])
        
        for i in range(25):
            writer.add("test_table", {"col1": i, "col2": i * 2})
        
        count = writer.flush_table("test_table")
        
        assert count == 25
        assert mock_clickhouse_client.execute.call_count == 3


class TestBatchWriterRetry:
    def test_successful_after_retry(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10, max_retries=3)
        writer.register_table("test_table", ["col1", "col2"])
        
        mock_clickhouse_client.execute.side_effect = [
            Exception("First failure"),
            Exception("Second failure"),
            None,
        ]
        
        writer.add("test_table", {"col1": 1, "col2": 2})
        
        count = writer.flush_table("test_table")
        
        assert count == 1
        assert mock_clickhouse_client.execute.call_count == 3
        stats = writer.get_stats()
        assert stats["retries"] == 2

    def test_exhaust_retries(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10, max_retries=2)
        writer.register_table("test_table", ["col1", "col2"])
        
        mock_clickhouse_client.execute.side_effect = Exception("Always fails")
        
        writer.add("test_table", {"col1": 1, "col2": 2})
        
        count = writer.flush_table("test_table")
        
        assert count == 0
        assert mock_clickhouse_client.execute.call_count == 3
        stats = writer.get_stats()
        assert stats["retries"] == 3
        assert stats["failed_writes"] == 1

    def test_retry_returns_data_to_queue(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10, max_retries=1)
        writer.register_table("test_table", ["col1", "col2"])
        
        mock_clickhouse_client.execute.side_effect = Exception("Always fails")
        
        for i in range(3):
            writer.add("test_table", {"col1": i, "col2": i * 2})
        
        initial_size = writer.get_queue_size("test_table")
        assert initial_size == 3
        
        count = writer.flush_table("test_table")
        
        assert count == 0
        final_size = writer.get_queue_size("test_table")
        assert final_size == 3


class TestBatchWriterThreading:
    def test_start_and_stop(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=5, flush_interval=1)
        writer.register_table("test_table", ["col1", "col2"])
        
        assert writer._running is False
        
        writer.start()
        
        assert writer._running is True
        assert writer._flush_thread is not None
        assert writer._flush_thread.is_alive()
        
        writer.stop()
        
        assert writer._running is False

    def test_start_already_running(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=5)
        
        writer.start()
        writer.start()
        
        writer.stop()

    def test_stop_not_running(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client)
        
        try:
            writer.stop()
        except Exception:
            pytest.fail("Stop should not raise exception")

    def test_concurrent_add(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=100, flush_interval=60)
        writer.register_table("test_table", ["col1", "col2"])
        
        def add_records(start: int, end: int):
            for i in range(start, end):
                writer.add("test_table", {"col1": i, "col2": i * 2})
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=add_records, args=(i * 100, (i + 1) * 100))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert writer.get_queue_size("test_table") == 500

    def test_background_flush(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10, flush_interval=1)
        writer.register_table("test_table", ["col1", "col2"])
        
        writer.start()
        
        for i in range(15):
            writer.add("test_table", {"col1": i, "col2": i * 2})
        
        time.sleep(2)
        
        stats = writer.get_stats()
        assert stats["total_records"] >= 10
        
        writer.stop()


class TestBatchWriterStats:
    def test_initial_stats(self, batch_writer):
        stats = batch_writer.get_stats()
        
        assert stats["total_writes"] == 0
        assert stats["total_records"] == 0
        assert stats["dropped_records"] == 0
        assert stats["failed_writes"] == 0
        assert stats["retries"] == 0
        assert stats["queue_size"] == 0
        assert stats["tables"] == []

    def test_stats_after_add(self, batch_writer):
        batch_writer.add("test_table", {"col1": 1})
        batch_writer.add("test_table", {"col1": 2})
        
        stats = batch_writer.get_stats()
        assert stats["queue_size"] == 2
        assert "test_table" in stats["tables"]
        assert stats["per_table_queue_size"]["test_table"] == 2

    def test_stats_after_flush(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("test_table", ["col1", "col2"])
        
        for i in range(5):
            writer.add("test_table", {"col1": i, "col2": i * 2})
        
        writer.flush_table("test_table")
        
        stats = writer.get_stats()
        assert stats["total_writes"] == 1
        assert stats["total_records"] == 5
        assert stats["queue_size"] == 0

    def test_stats_after_drop(self):
        writer = BatchWriter(max_queue_size=2)
        
        writer.add("test_table", {"col1": 1})
        writer.add("test_table", {"col1": 2})
        writer.add("test_table", {"col1": 3})
        
        stats = writer.get_stats()
        assert stats["dropped_records"] == 1

    def test_reset_stats(self, batch_writer):
        batch_writer.add("test_table", {"col1": 1})
        
        stats = batch_writer.get_stats()
        assert stats["queue_size"] == 1
        
        batch_writer.reset_stats()
        
        stats = batch_writer.get_stats()
        assert stats["total_writes"] == 0
        assert stats["total_records"] == 0
        assert stats["dropped_records"] == 0
        assert stats["failed_writes"] == 0
        assert stats["retries"] == 0

    def test_get_queue_size(self, batch_writer):
        batch_writer.add("table1", {"col1": 1})
        batch_writer.add("table1", {"col1": 2})
        batch_writer.add("table2", {"col1": 1})
        
        assert batch_writer.get_queue_size("table1") == 2
        assert batch_writer.get_queue_size("table2") == 1
        assert batch_writer.get_queue_size("nonexistent") == 0
        assert batch_writer.get_queue_size() == 3


class TestBatchWriterEdgeCases:
    def test_empty_data_list(self, batch_writer):
        count = batch_writer.add_batch("test_table", [])
        assert count == 0

    def test_none_values(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("test_table", ["col1", "col2", "col3"])
        
        writer.add("test_table", {"col1": None, "col2": "value", "col3": 123})
        
        count = writer.flush_table("test_table")
        assert count == 1
        
        call_args = mock_clickhouse_client.execute.call_args
        values = call_args[0][1]
        assert values[0][0] is None

    def test_special_characters(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10)
        writer.register_table("test_table", ["col1", "col2"])
        
        writer.add("test_table", {"col1": "special chars: 中文!@#$%", "col2": 123})
        
        count = writer.flush_table("test_table")
        assert count == 1

    def test_large_data_volume(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=1000, max_queue_size=10000)
        writer.register_table("test_table", ["id", "value"])
        
        for i in range(5000):
            writer.add("test_table", {"id": i, "value": f"data_{i}"})
        
        assert writer.get_queue_size("test_table") == 5000
        
        count = writer.flush_table("test_table")
        assert count == 5000
        assert mock_clickhouse_client.execute.call_count == 5

    def test_mock_client_none(self):
        writer = BatchWriter(client=None, batch_size=10)
        writer.register_table("test_table", ["col1", "col2"])
        
        writer.add("test_table", {"col1": 1, "col2": 2})
        
        count = writer.flush_table("test_table")
        assert count == 1

    def test_flush_loop_exception(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=10, flush_interval=1)
        writer.register_table("test_table", ["col1", "col2"])
        
        writer.start()
        
        with patch.object(writer, '_flush_table') as mock_flush:
            mock_flush.side_effect = Exception("Flush error")
            
            writer.add("test_table", {"col1": 1, "col2": 2})
            writer._last_flush["test_table"] = time.time() - 2
            
            time.sleep(1.5)
        
        writer.stop()

    def test_multiple_tables_concurrent(self, mock_clickhouse_client):
        writer = BatchWriter(client=mock_clickhouse_client, batch_size=50, flush_interval=60)
        
        tables = [f"table_{i}" for i in range(5)]
        for table in tables:
            writer.register_table(table, ["col1", "col2"])
        
        def add_to_table(table_name, count):
            for i in range(count):
                writer.add(table_name, {"col1": i, "col2": i * 2})
        
        threads = []
        for table in tables:
            t = threading.Thread(target=add_to_table, args=(table, 100))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        for table in tables:
            assert writer.get_queue_size(table) == 100
        
        results = writer.flush_all()
        for table in tables:
            assert results[table] == 100
