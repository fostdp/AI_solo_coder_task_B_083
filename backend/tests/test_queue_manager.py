import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import multiprocessing
import queue

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.core.queue_manager import (
        AsyncQueueWrapper,
        ProcessQueueWrapper,
        QueueManager,
        QueueStats,
    )
    from app.core.messages import SensorData, EnvSensorData


class TestAsyncQueueWrapper:
    @pytest.mark.asyncio
    async def test_put_and_get(self, async_queue):
        msg = EnvSensorData(sensor_id="test_001", temperature=22.5)
        
        result = await async_queue.put(msg)
        assert result is True
        assert async_queue.qsize() == 1
        
        retrieved = await async_queue.get()
        assert retrieved is not None
        assert retrieved.sensor_id == "test_001"
        assert retrieved.temperature == pytest.approx(22.5)
        assert async_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_put_with_timeout(self, async_queue):
        msg = EnvSensorData(sensor_id="test_001")
        result = await async_queue.put(msg, timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_with_timeout(self, async_queue):
        result = await async_queue.get(timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_put_nowait(self, async_queue):
        msg = EnvSensorData(sensor_id="test_001")
        result = async_queue.put_nowait(msg)
        assert result is True
        assert async_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_get_nowait(self, async_queue):
        msg = EnvSensorData(sensor_id="test_001")
        async_queue.put_nowait(msg)
        
        retrieved = async_queue.get_nowait()
        assert retrieved is not None
        assert retrieved.sensor_id == "test_001"
        
        empty_result = async_queue.get_nowait()
        assert empty_result is None

    @pytest.mark.asyncio
    async def test_queue_full_drops_oldest(self):
        queue = AsyncQueueWrapper[SensorData]("test_queue", maxsize=3)
        
        msg1 = EnvSensorData(sensor_id="msg_1")
        msg2 = EnvSensorData(sensor_id="msg_2")
        msg3 = EnvSensorData(sensor_id="msg_3")
        msg4 = EnvSensorData(sensor_id="msg_4")
        
        await queue.put(msg1)
        await queue.put(msg2)
        await queue.put(msg3)
        
        assert queue.full() is True
        assert queue.qsize() == 3
        
        await queue.put(msg4)
        
        assert queue.qsize() == 3
        stats = queue.get_stats()
        assert stats.total_dropped == 1
        
        retrieved1 = await queue.get()
        retrieved2 = await queue.get()
        retrieved3 = await queue.get()
        
        assert retrieved1.sensor_id == "msg_2"
        assert retrieved2.sensor_id == "msg_3"
        assert retrieved3.sensor_id == "msg_4"

    @pytest.mark.asyncio
    async def test_put_nowait_full_drops_oldest(self):
        queue = AsyncQueueWrapper[SensorData]("test_queue", maxsize=2)
        
        queue.put_nowait(EnvSensorData(sensor_id="msg_1"))
        queue.put_nowait(EnvSensorData(sensor_id="msg_2"))
        
        assert queue.full() is True
        
        queue.put_nowait(EnvSensorData(sensor_id="msg_3"))
        
        assert queue.qsize() == 2
        stats = queue.get_stats()
        assert stats.total_dropped == 1

    @pytest.mark.asyncio
    async def test_empty_and_full(self, async_queue):
        assert async_queue.empty() is True
        assert async_queue.full() is False
        
        msg = EnvSensorData(sensor_id="test_001")
        await async_queue.put(msg)
        
        assert async_queue.empty() is False
        assert async_queue.full() is False

    @pytest.mark.asyncio
    async def test_stats(self, async_queue):
        stats = async_queue.get_stats()
        assert stats.name == "test_queue"
        assert stats.max_size == 10
        assert stats.total_put == 0
        assert stats.total_get == 0
        assert stats.total_dropped == 0
        
        msg = EnvSensorData(sensor_id="test_001")
        await async_queue.put(msg)
        
        stats = async_queue.get_stats()
        assert stats.total_put == 1
        assert stats.size == 1
        
        await async_queue.get()
        
        stats = async_queue.get_stats()
        assert stats.total_get == 1
        assert stats.size == 0

    @pytest.mark.asyncio
    async def test_concurrent_put(self, async_queue):
        async def put_message(i):
            msg = EnvSensorData(sensor_id=f"msg_{i}")
            return await async_queue.put(msg)
        
        tasks = [put_message(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        assert all(results)
        assert async_queue.qsize() == 10
        
        stats = async_queue.get_stats()
        assert stats.total_put == 10

    @pytest.mark.asyncio
    async def test_concurrent_get(self, async_queue):
        for i in range(5):
            await async_queue.put(EnvSensorData(sensor_id=f"msg_{i}"))
        
        async def get_message():
            return await async_queue.get(timeout=1.0)
        
        tasks = [get_message() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        
        assert all(r is not None for r in results)
        assert len(set(r.sensor_id for r in results)) == 5
        assert async_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_put_timeout_returns_false(self):
        queue = AsyncQueueWrapper[SensorData]("test_queue", maxsize=1)
        
        await queue.put(EnvSensorData(sensor_id="msg_1"))
        
        with patch.object(queue._queue, 'put', new_callable=AsyncMock) as mock_put:
            mock_put.side_effect = asyncio.TimeoutError()
            result = await queue.put(EnvSensorData(sensor_id="msg_2"), timeout=0.1)
            assert result is False

    @pytest.mark.asyncio
    async def test_put_exception_returns_false(self, async_queue):
        with patch.object(async_queue._queue, 'put', new_callable=AsyncMock) as mock_put:
            mock_put.side_effect = Exception("Test error")
            result = await async_queue.put(EnvSensorData(sensor_id="msg_1"))
            assert result is False

    @pytest.mark.asyncio
    async def test_get_exception_returns_none(self, async_queue):
        with patch.object(async_queue._queue, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Test error")
            result = await async_queue.get()
            assert result is None

    def test_put_nowait_exception_returns_false(self, async_queue):
        with patch.object(async_queue._queue, 'put_nowait') as mock_put:
            mock_put.side_effect = Exception("Test error")
            result = async_queue.put_nowait(EnvSensorData(sensor_id="msg_1"))
            assert result is False

    def test_get_nowait_exception_returns_none(self, async_queue):
        with patch.object(async_queue._queue, 'get_nowait') as mock_get:
            mock_get.side_effect = Exception("Test error")
            result = async_queue.get_nowait()
            assert result is None


class TestProcessQueueWrapper:
    def test_initialization(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_process_queue", maxsize=100)
            
            assert wrapper.name == "test_process_queue"
            assert wrapper.max_size == 100
            mock_queue_class.assert_called_once_with(maxsize=100)
            mock_lock_class.assert_called_once()

    def test_put_success(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue", maxsize=10)
            mock_queue.full.return_value = False
            
            msg = EnvSensorData(sensor_id="test_001", temperature=22.5)
            result = wrapper.put(msg)
            
            assert result is True
            mock_queue.put.assert_called_once()
            
            call_args = mock_queue.put.call_args
            assert call_args[0][0]["sensor_id"] == "test_001"
            assert call_args[0][0]["temperature"] == pytest.approx(22.5)

    def test_put_with_timeout(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            mock_queue.full.return_value = False
            
            msg = EnvSensorData(sensor_id="test_001")
            result = wrapper.put(msg, timeout=5.0)
            
            assert result is True
            mock_queue.put.assert_called_once()
            assert mock_queue.put.call_args[1]["timeout"] == 5.0

    def test_put_full_drops_oldest(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue", maxsize=2)
            mock_queue.full.side_effect = [True, False]
            
            msg = EnvSensorData(sensor_id="test_001")
            result = wrapper.put(msg)
            
            assert result is True
            mock_queue.get_nowait.assert_called_once()
            
            stats = wrapper.get_stats()
            assert stats.total_dropped == 1

    def test_put_exception_returns_false(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            mock_queue.full.return_value = False
            mock_queue.put.side_effect = Exception("Test error")
            
            msg = EnvSensorData(sensor_id="test_001")
            result = wrapper.put(msg)
            
            assert result is False

    def test_get_success(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            
            mock_data = {
                "message_id": "test-id",
                "timestamp": "2024-01-15T10:30:00",
                "message_type": "sensor_data",
                "sensor_id": "env_001",
                "shelf_id": "shelf_01",
                "slot_id": "slot_001",
                "sensor_type": "environment",
                "data": {"temperature": 22.5, "humidity": 55.0},
                "is_valid": True,
                "validation_errors": []
            }
            mock_queue.get.return_value = mock_data
            
            result = wrapper.get()
            
            assert result is not None
            assert isinstance(result, SensorData)
            assert result.sensor_id == "env_001"
            assert result.shelf_id == "shelf_01"
            assert result.slot_id == "slot_001"
            assert result.sensor_type == "environment"
            assert result.data == {"temperature": 22.5, "humidity": 55.0}
            assert result.is_valid is True
            assert result.validation_errors == []

    def test_get_with_timeout(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            
            mock_data = {
                "message_id": "test-id",
                "timestamp": "2024-01-15T10:30:00",
                "message_type": "sensor_data",
                "sensor_id": "env_001",
            }
            mock_queue.get.return_value = mock_data
            
            result = wrapper.get(timeout=5.0)
            
            assert result is not None
            mock_queue.get.assert_called_once_with(timeout=5.0)

    def test_get_empty_returns_none(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            mock_queue.get.side_effect = queue.Empty()
            
            result = wrapper.get(timeout=0.1)
            
            assert result is None

    def test_get_exception_returns_none(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            mock_queue.get.side_effect = Exception("Test error")
            
            result = wrapper.get()
            
            assert result is None

    def test_qsize(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            mock_queue.qsize.return_value = 42
            
            assert wrapper.qsize() == 42

    def test_qsize_not_implemented(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            mock_queue.qsize.side_effect = NotImplementedError()
            
            assert wrapper.qsize() == 0

    def test_empty_and_full(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            
            mock_queue.empty.return_value = True
            mock_queue.full.return_value = False
            assert wrapper.empty() is True
            assert wrapper.full() is False
            
            mock_queue.empty.return_value = False
            mock_queue.full.return_value = True
            assert wrapper.empty() is False
            assert wrapper.full() is True

    def test_close(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue")
            wrapper.close()
            
            mock_queue.close.assert_called_once()
            mock_queue.join_thread.assert_called_once()

    def test_stats(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock') as mock_lock_class:
            
            mock_queue = MagicMock()
            mock_lock = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_lock_class.return_value = mock_lock
            
            wrapper = ProcessQueueWrapper[SensorData]("test_queue", maxsize=50)
            mock_queue.full.return_value = False
            mock_queue.qsize.return_value = 0
            
            stats = wrapper.get_stats()
            assert stats.name == "test_queue"
            assert stats.max_size == 50
            assert stats.total_put == 0
            assert stats.total_get == 0
            
            mock_data = {
                "message_id": "test-id",
                "timestamp": "2024-01-15T10:30:00",
                "message_type": "sensor_data",
                "sensor_id": "env_001",
            }
            mock_queue.get.return_value = mock_data
            
            wrapper.put(EnvSensorData(sensor_id="test"))
            wrapper.get()
            
            stats = wrapper.get_stats()
            assert stats.total_put == 1
            assert stats.total_get == 1


class TestQueueManager:
    def test_create_async_queue(self, queue_manager):
        queue = queue_manager.create_async_queue("test_async", maxsize=100)
        
        assert queue is not None
        assert queue.name == "test_async"
        assert queue.max_size == 100
        
        same_queue = queue_manager.create_async_queue("test_async", maxsize=200)
        assert same_queue is queue

    def test_create_process_queue(self, queue_manager):
        with patch('multiprocessing.Queue'), patch('multiprocessing.Lock'):
            queue = queue_manager.create_process_queue("test_process", maxsize=50)
            
            assert queue is not None
            assert queue.name == "test_process"
            assert queue.max_size == 50
            
            same_queue = queue_manager.create_process_queue("test_process", maxsize=100)
            assert same_queue is queue

    def test_get_async_queue(self, queue_manager):
        queue = queue_manager.create_async_queue("test_async")
        
        retrieved = queue_manager.get_async_queue("test_async")
        assert retrieved is queue
        
        missing = queue_manager.get_async_queue("nonexistent")
        assert missing is None

    def test_get_process_queue(self, queue_manager):
        with patch('multiprocessing.Queue'), patch('multiprocessing.Lock'):
            queue = queue_manager.create_process_queue("test_process")
            
            retrieved = queue_manager.get_process_queue("test_process")
            assert retrieved is queue
            
            missing = queue_manager.get_process_queue("nonexistent")
            assert missing is None

    def test_get_queue(self, queue_manager):
        async_queue = queue_manager.create_async_queue("async_queue")
        
        with patch('multiprocessing.Queue'), patch('multiprocessing.Lock'):
            process_queue = queue_manager.create_process_queue("process_queue")
            
            assert queue_manager.get_queue("async_queue") is async_queue
            assert queue_manager.get_queue("process_queue") is process_queue
            assert queue_manager.get_queue("nonexistent") is None

    def test_get_all_stats(self, queue_manager):
        async_queue = queue_manager.create_async_queue("async_1", maxsize=10)
        async_queue.put_nowait(EnvSensorData(sensor_id="test"))
        
        with patch('multiprocessing.Queue'), patch('multiprocessing.Lock'):
            process_queue = queue_manager.create_process_queue("process_1", maxsize=20)
            
            stats = queue_manager.get_all_stats()
            
            assert "async_queues" in stats
            assert "process_queues" in stats
            assert "async_1" in stats["async_queues"]
            assert "process_1" in stats["process_queues"]
            
            async_stats = stats["async_queues"]["async_1"]
            assert async_stats["size"] == 1
            assert async_stats["max_size"] == 10
            assert async_stats["total_put"] == 1

    @pytest.mark.asyncio
    async def test_flush_all_async(self, queue_manager):
        queue1 = queue_manager.create_async_queue("flush_1", maxsize=5)
        queue2 = queue_manager.create_async_queue("flush_2", maxsize=5)
        
        for i in range(3):
            queue1.put_nowait(EnvSensorData(sensor_id=f"msg_{i}"))
            queue2.put_nowait(EnvSensorData(sensor_id=f"msg_{i}"))
        
        assert queue1.qsize() == 3
        assert queue2.qsize() == 3
        
        await queue_manager.flush_all_async()
        
        assert queue1.qsize() == 0
        assert queue2.qsize() == 0

    def test_close_all_process_queues(self, queue_manager):
        with patch('multiprocessing.Queue') as mock_queue_class, patch('multiprocessing.Lock'):
            mock_queue1 = MagicMock()
            mock_queue2 = MagicMock()
            mock_queue_class.side_effect = [mock_queue1, mock_queue2]
            
            queue_manager.create_process_queue("close_1")
            queue_manager.create_process_queue("close_2")
            
            queue_manager.close_all_process_queues()
            
            mock_queue1.close.assert_called_once()
            mock_queue2.close.assert_called_once()

    def test_close_all_process_queues_with_exception(self, queue_manager):
        with patch('multiprocessing.Queue') as mock_queue_class, patch('multiprocessing.Lock'):
            mock_queue = MagicMock()
            mock_queue.close.side_effect = Exception("Close error")
            mock_queue_class.return_value = mock_queue
            
            queue_manager.create_process_queue("error_queue")
            
            try:
                queue_manager.close_all_process_queues()
            except Exception:
                pytest.fail("Should not raise exception")


class TestQueueStats:
    def test_queue_stats_defaults(self):
        stats = QueueStats(name="test_queue")
        
        assert stats.name == "test_queue"
        assert stats.size == 0
        assert stats.max_size == 0
        assert stats.total_put == 0
        assert stats.total_get == 0
        assert stats.total_dropped == 0

    def test_queue_stats_custom(self):
        stats = QueueStats(
            name="test_queue",
            max_size=100,
            size=50,
            total_put=1000,
            total_get=950,
            total_dropped=5
        )
        
        assert stats.name == "test_queue"
        assert stats.max_size == 100
        assert stats.size == 50
        assert stats.total_put == 1000
        assert stats.total_get == 950
        assert stats.total_dropped == 5
