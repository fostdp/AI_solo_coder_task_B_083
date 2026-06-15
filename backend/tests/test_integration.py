import pytest
import asyncio
import time
import threading
import json
from unittest.mock import MagicMock, patch, call
from typing import Dict, Any, List, Set
import random

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.ingest import MQTTDataHandler, DataCleaner, DataValidator
    from app.batch_writer import BatchWriter
    from app.core.queue_manager import AsyncQueueWrapper, QueueManager
    from app.core.messages import (
        SensorData,
        EnvSensorData,
        PhSensorData,
        AlertMessage,
        serialize_message,
        deserialize_message,
    )


class TestDataPipelineIntegration:
    def test_full_data_flow_env_sensor(self):
        handler = MQTTDataHandler()
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=100, flush_interval=60)
        writer.register_table(
            "env_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id",
             "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]
        )
        
        raw_data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 22.5,
            "humidity": 55.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
            "timestamp": "2024-01-15T10:30:00",
        }
        
        sensor_data = handler.handle_message("library/env/sensor_001", raw_data)
        
        assert sensor_data is not None
        assert sensor_data.is_valid is True
        assert isinstance(sensor_data, EnvSensorData)
        
        record = {
            "timestamp": sensor_data.timestamp,
            "sensor_id": sensor_data.sensor_id,
            "shelf_id": sensor_data.shelf_id,
            "slot_id": sensor_data.slot_id,
            "temperature": sensor_data.temperature,
            "humidity": sensor_data.humidity,
            "light": sensor_data.light,
            "voc": sensor_data.voc,
            "mold_spore": sensor_data.mold_spore,
            "sensor_type": sensor_data.sensor_type,
        }
        
        writer.add("env_sensor_data", record)
        writer.flush_table("env_sensor_data")
        
        assert mock_client.execute.called
        call_args = mock_client.execute.call_args
        assert "INSERT INTO env_sensor_data" in call_args[0][0]
        values = call_args[0][1]
        assert len(values) == 1
        assert values[0][0] == "2024-01-15T10:30:00"
        assert values[0][1] == "env_001"
        assert values[0][4] == pytest.approx(22.5)

    def test_full_data_flow_ph_sensor(self):
        handler = MQTTDataHandler()
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=100, flush_interval=60)
        writer.register_table(
            "ph_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id", "ph_value", "sensor_type"]
        )
        
        raw_data = {
            "sensor_id": "ph_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "ph_value": 6.8,
            "timestamp": "2024-01-15T10:30:00",
        }
        
        sensor_data = handler.handle_message("library/ph/sensor_001", raw_data)
        
        assert sensor_data is not None
        assert sensor_data.is_valid is True
        assert isinstance(sensor_data, PhSensorData)
        
        record = {
            "timestamp": sensor_data.timestamp,
            "sensor_id": sensor_data.sensor_id,
            "shelf_id": sensor_data.shelf_id,
            "slot_id": sensor_data.slot_id,
            "ph_value": sensor_data.ph_value,
            "sensor_type": sensor_data.sensor_type,
        }
        
        writer.add("ph_sensor_data", record)
        writer.flush_table("ph_sensor_data")
        
        assert mock_client.execute.called
        call_args = mock_client.execute.call_args
        assert "INSERT INTO ph_sensor_data" in call_args[0][0]
        values = call_args[0][1]
        assert len(values) == 1
        assert values[0][4] == pytest.approx(6.8)

    def test_data_validation_in_pipeline(self):
        handler = MQTTDataHandler()
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=100, flush_interval=60)
        writer.register_table("env_sensor_data", ["sensor_id", "temperature", "is_valid"])
        
        invalid_data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 100.0,
            "humidity": 150.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
        }
        
        sensor_data = handler.handle_message("library/env/sensor_001", invalid_data)
        
        assert sensor_data is not None
        assert sensor_data.is_valid is False
        assert len(sensor_data.validation_errors) == 2
        
        record = {
            "sensor_id": sensor_data.sensor_id,
            "temperature": sensor_data.temperature,
            "is_valid": sensor_data.is_valid,
        }
        
        writer.add("env_sensor_data", record)
        writer.flush_table("env_sensor_data")
        
        assert mock_client.execute.called
        values = mock_client.execute.call_args[0][1]
        assert values[0][2] is False


class TestMessageDeliveryGuarantee:
    def test_1000_messages_no_loss(self):
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=100, flush_interval=60, max_queue_size=2000)
        writer.register_table(
            "env_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id",
             "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]
        )
        
        total_messages = 1000
        message_ids = []
        
        for i in range(total_messages):
            record = {
                "timestamp": f"2024-01-15T10:{i//60:02d}:{i%60:02d}",
                "sensor_id": f"env_{i:03d}",
                "shelf_id": f"shelf_{i//100:02d}",
                "slot_id": f"slot_{i%100:03d}",
                "temperature": 20.0 + random.uniform(-5, 5),
                "humidity": 50.0 + random.uniform(-10, 10),
                "light": 30.0 + random.uniform(-10, 20),
                "voc": 100.0 + random.uniform(-50, 100),
                "mold_spore": 50.0 + random.uniform(0, 200),
                "sensor_type": "environment",
            }
            message_ids.append(record["sensor_id"])
            writer.add("env_sensor_data", record)
        
        assert writer.get_queue_size("env_sensor_data") == total_messages
        
        results = writer.flush_all()
        total_written = sum(results.values())
        
        loss_rate = (total_messages - total_written) / total_messages
        assert loss_rate < 0.001, f"消息丢失率过高: {loss_rate:.2%}"
        
        all_values = []
        for call_obj in mock_client.execute.call_args_list:
            all_values.extend(call_obj[0][1])
        
        written_ids = [v[1] for v in all_values]
        assert len(written_ids) == total_written
        
        unique_ids = set(written_ids)
        assert len(unique_ids) == len(written_ids), "存在重复消息"

    def test_concurrent_message_writing(self):
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=50, flush_interval=60, max_queue_size=5000)
        writer.register_table(
            "env_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id",
             "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]
        )
        
        messages_per_thread = 250
        num_threads = 4
        total_messages = messages_per_thread * num_threads
        
        def write_messages(thread_id: int):
            for i in range(messages_per_thread):
                msg_id = thread_id * messages_per_thread + i
                record = {
                    "timestamp": f"2024-01-15T10:00:00",
                    "sensor_id": f"env_{msg_id:05d}",
                    "shelf_id": f"shelf_{thread_id}",
                    "slot_id": f"slot_{i:03d}",
                    "temperature": 20.0 + i * 0.01,
                    "humidity": 50.0,
                    "light": 30.0,
                    "voc": 100.0,
                    "mold_spore": 50.0,
                    "sensor_type": "environment",
                }
                writer.add("env_sensor_data", record)
        
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=write_messages, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert writer.get_queue_size("env_sensor_data") == total_messages
        
        results = writer.flush_all()
        total_written = sum(results.values())
        
        loss_rate = (total_messages - total_written) / total_messages
        assert loss_rate < 0.001, f"并发写入消息丢失率过高: {loss_rate:.2%}"
        
        all_values = []
        for call_obj in mock_client.execute.call_args_list:
            all_values.extend(call_obj[0][1])
        
        written_ids = [v[1] for v in all_values]
        unique_ids = set(written_ids)
        assert len(unique_ids) == len(written_ids), "并发写入存在重复消息"
        
        thread_counts = {}
        for msg_id in written_ids:
            thread_id = int(msg_id.split("_")[1]) // messages_per_thread
            thread_counts[thread_id] = thread_counts.get(thread_id, 0) + 1
        
        for thread_id in range(num_threads):
            assert thread_id in thread_counts
            assert thread_counts[thread_id] == messages_per_thread

    def test_queue_with_batch_writer_pipeline(self):
        queue = AsyncQueueWrapper[SensorData]("pipeline_queue", maxsize=2000)
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=100, flush_interval=60)
        writer.register_table(
            "env_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id",
             "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]
        )
        
        async def produce_messages():
            for i in range(500):
                msg = EnvSensorData(
                    sensor_id=f"env_{i:03d}",
                    shelf_id="shelf_01",
                    slot_id=f"slot_{i:03d}",
                    temperature=20.0 + i * 0.01,
                    humidity=50.0,
                    light=30.0,
                    voc=100.0,
                    mold_spore=50.0,
                )
                await queue.put(msg)
        
        async def consume_and_write():
            count = 0
            while count < 500:
                msg = await queue.get(timeout=1.0)
                if msg is not None:
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
                        "sensor_type": msg.sensor_type,
                    }
                    writer.add("env_sensor_data", record)
                    count += 1
        
        async def run_pipeline():
            await asyncio.gather(produce_messages(), consume_and_write())
        
        asyncio.run(run_pipeline())
        
        results = writer.flush_all()
        total_written = sum(results.values())
        
        assert total_written == 500
        
        all_values = []
        for call_obj in mock_client.execute.call_args_list:
            all_values.extend(call_obj[0][1])
        
        written_ids = [v[1] for v in all_values]
        assert len(set(written_ids)) == 500


class TestEndToEndMQTTIntegration:
    def test_mqtt_message_processing_pipeline(self):
        handler = MQTTDataHandler()
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=50, flush_interval=60)
        writer.register_table(
            "env_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id",
             "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]
        )
        writer.register_table(
            "ph_sensor_data",
            ["timestamp", "sensor_id", "shelf_id", "slot_id", "ph_value", "sensor_type"]
        )
        
        mqtt_messages = []
        for i in range(100):
            if i % 2 == 0:
                topic = f"library/env/sensor_{i}"
                payload = {
                    "sensor_id": f"env_{i:03d}",
                    "shelf_id": f"shelf_{i//10}",
                    "slot_id": f"slot_{i%10}",
                    "temperature": 20.0 + random.uniform(-2, 2),
                    "humidity": 50.0 + random.uniform(-5, 5),
                    "light": 30.0 + random.uniform(-10, 10),
                    "voc": 100.0 + random.uniform(-30, 30),
                    "mold_spore": 50.0 + random.uniform(0, 100),
                    "timestamp": f"2024-01-15T10:00:{i:02d}",
                }
            else:
                topic = f"library/ph/sensor_{i}"
                payload = {
                    "sensor_id": f"ph_{i:03d}",
                    "shelf_id": f"shelf_{i//10}",
                    "slot_id": f"slot_{i%10}",
                    "ph_value": 6.0 + random.uniform(0, 1.5),
                    "timestamp": f"2024-01-15T10:00:{i:02d}",
                }
            mqtt_messages.append((topic, payload))
        
        valid_env_count = 0
        valid_ph_count = 0
        
        for topic, payload in mqtt_messages:
            sensor_data = handler.handle_message(topic, payload)
            if sensor_data is not None and sensor_data.is_valid:
                if isinstance(sensor_data, EnvSensorData):
                    record = {
                        "timestamp": sensor_data.timestamp,
                        "sensor_id": sensor_data.sensor_id,
                        "shelf_id": sensor_data.shelf_id,
                        "slot_id": sensor_data.slot_id,
                        "temperature": sensor_data.temperature,
                        "humidity": sensor_data.humidity,
                        "light": sensor_data.light,
                        "voc": sensor_data.voc,
                        "mold_spore": sensor_data.mold_spore,
                        "sensor_type": sensor_data.sensor_type,
                    }
                    writer.add("env_sensor_data", record)
                    valid_env_count += 1
                elif isinstance(sensor_data, PhSensorData):
                    record = {
                        "timestamp": sensor_data.timestamp,
                        "sensor_id": sensor_data.sensor_id,
                        "shelf_id": sensor_data.shelf_id,
                        "slot_id": sensor_data.slot_id,
                        "ph_value": sensor_data.ph_value,
                        "sensor_type": sensor_data.sensor_type,
                    }
                    writer.add("ph_sensor_data", record)
                    valid_ph_count += 1
        
        results = writer.flush_all()
        
        assert results.get("env_sensor_data", 0) == valid_env_count
        assert results.get("ph_sensor_data", 0) == valid_ph_count
        
        stats = handler.get_stats()
        assert stats["total_received"] == 100
        assert stats["env_messages"] == 50
        assert stats["ph_messages"] == 50

    def test_mqtt_subscriber_with_batch_writer(self):
        from app.mqtt_subscriber import MQTTSubscriber
        from app.database import db_manager
        
        mock_client = MagicMock()
        
        with patch.object(db_manager, 'client', mock_client):
            with patch.object(db_manager, 'batch_writer', MagicMock()) as mock_bw:
                subscriber = MQTTSubscriber()
                
                for i in range(10):
                    payload = {
                        "sensor_id": f"env_{i:03d}",
                        "shelf_id": "shelf_01",
                        "slot_id": f"slot_{i:02d}",
                        "temperature": 22.5,
                        "humidity": 55.0,
                        "light": 30.0,
                        "voc": 150.0,
                        "mold_spore": 100.0,
                    }
                    
                    mock_msg = MagicMock()
                    mock_msg.topic = "library/env/sensor_001"
                    mock_msg.payload = json.dumps(payload).encode("utf-8")
                    
                    subscriber.on_message(mock_client, None, mock_msg)
                
                assert mock_bw.add.call_count == 10


class TestAlertIntegration:
    def test_alert_generation_and_storage(self):
        from app.alerts.alert_manager import AlertManager, AlertThreshold
        
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=10, flush_interval=60)
        writer.register_table(
            "alerts",
            ["alert_id", "timestamp", "shelf_id", "slot_id",
             "alert_level", "alert_type", "alert_value", "threshold",
             "message", "is_handled"]
        )
        
        alert_manager = AlertManager(thresholds=AlertThreshold(
            yellow_ph=6.5,
            orange_ph=6.0,
            red_ph=5.5,
            yellow_mold=500.0,
            orange_light=50.0,
        ))
        
        sensor_data = {
            "sensor_id": "ph_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "ph_value": 5.2,
            "timestamp": "2024-01-15T10:30:00",
        }
        
        alerts = alert_manager.check_and_create_alerts(sensor_data)
        
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_level == "red"
        assert alert.alert_type == "ph_low"
        
        record = {
            "alert_id": alert.alert_id,
            "timestamp": alert.timestamp,
            "shelf_id": alert.shelf_id,
            "slot_id": alert.slot_id,
            "alert_level": alert.alert_level,
            "alert_type": alert.alert_type,
            "alert_value": alert.alert_value,
            "threshold": alert.threshold,
            "message": alert.message,
            "is_handled": alert.is_handled,
        }
        
        writer.add("alerts", record)
        writer.flush_table("alerts")
        
        assert mock_client.execute.called
        values = mock_client.execute.call_args[0][1]
        assert len(values) == 1
        assert values[0][4] == "red"
        assert values[0][5] == "ph_low"
        assert values[0][6] == pytest.approx(5.2)


class TestMessageSerializationRoundTrip:
    def test_full_serialization_pipeline(self):
        original = SensorData(
            sensor_id="env_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            sensor_type="environment",
            data={"temperature": 22.5, "humidity": 55.0, "light": 30.0, "voc": 150.0, "mold_spore": 100.0},
        )
        
        serialized = serialize_message(original)
        deserialized = deserialize_message(serialized)
        reserialized = serialize_message(deserialized)
        
        assert deserialized.sensor_id == original.sensor_id
        assert deserialized.shelf_id == original.shelf_id
        assert deserialized.slot_id == original.slot_id
        assert deserialized.sensor_type == original.sensor_type
        assert deserialized.data == original.data
        assert serialized == reserialized

    def test_queue_message_serialization(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock'):
            
            mock_queue = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_queue.full.return_value = False
            
            from app.core.queue_manager import ProcessQueueWrapper
            
            queue = ProcessQueueWrapper[SensorData]("test_queue", maxsize=10)
            
            original = SensorData(
                sensor_id="env_001",
                shelf_id="shelf_01",
                slot_id="slot_001",
                sensor_type="environment",
                data={"temperature": 22.5, "humidity": 55.0},
            )
            
            queue.put(original)
            
            call_args = mock_queue.put.call_args
            serialized_data = call_args[0][0]
            
            assert "sensor_id" in serialized_data
            assert serialized_data["sensor_id"] == "env_001"
            assert "data" in serialized_data
            assert serialized_data["data"]["temperature"] == pytest.approx(22.5)
            
            mock_queue.get.return_value = serialized_data
            
            retrieved = queue.get()
            
            assert retrieved is not None
            assert isinstance(retrieved, SensorData)
            assert retrieved.sensor_id == "env_001"
            assert retrieved.shelf_id == "shelf_01"
            assert retrieved.slot_id == "slot_001"
            assert retrieved.sensor_type == "environment"
            assert retrieved.data == {"temperature": 22.5, "humidity": 55.0}


class TestBackpressureHandling:
    def test_queue_backpressure_with_high_volume(self):
        queue = AsyncQueueWrapper[SensorData]("backpressure_test", maxsize=100)
        mock_client = MagicMock()
        writer = BatchWriter(client=mock_client, batch_size=50, flush_interval=60, max_queue_size=500)
        writer.register_table("env_sensor_data", ["sensor_id", "temperature"])
        
        async def produce_fast():
            for i in range(200):
                msg = EnvSensorData(
                    sensor_id=f"env_{i:03d}",
                    shelf_id="shelf_01",
                    slot_id="slot_001",
                    temperature=20.0 + i * 0.01,
                    humidity=50.0,
                    light=30.0,
                    voc=100.0,
                    mold_spore=50.0,
                )
                await queue.put(msg)
        
        async def consume_slow():
            count = 0
            while count < 200:
                msg = await queue.get(timeout=2.0)
                if msg is not None:
                    record = {
                        "sensor_id": msg.sensor_id,
                        "temperature": msg.temperature,
                    }
                    writer.add("env_sensor_data", record)
                    count += 1
                    await asyncio.sleep(0.001)
        
        async def run_test():
            await asyncio.gather(produce_fast(), consume_slow())
        
        asyncio.run(run_test())
        
        stats = queue.get_stats()
        assert stats.total_put == 200
        assert stats.total_get == 200
        
        if stats.total_dropped > 0:
            drop_rate = stats.total_dropped / stats.total_put
            assert drop_rate < 0.001, f"背压下消息丢失率过高: {drop_rate:.2%}"

    def test_batch_writer_under_load(self):
        mock_client = MagicMock()
        writer = BatchWriter(
            client=mock_client,
            batch_size=100,
            flush_interval=0.1,
            max_queue_size=5000,
            max_retries=2,
        )
        writer.register_table("env_sensor_data", ["sensor_id", "temperature"])
        
        writer.start()
        
        try:
            for i in range(1000):
                writer.add("env_sensor_data", {
                    "sensor_id": f"env_{i:04d}",
                    "temperature": 20.0 + i * 0.001,
                })
            
            time.sleep(0.5)
            
            stats = writer.get_stats()
            
            if stats["dropped_records"] > 0:
                drop_rate = stats["dropped_records"] / 1000
                assert drop_rate < 0.001, f"高负载下消息丢失率过高: {drop_rate:.2%}"
            
            assert stats["total_records"] >= 999
        finally:
            writer.stop()


class TestQueueReliabilityIntegration:
    def test_async_queue_1000_messages_no_loss(self):
        queue = AsyncQueueWrapper[SensorData]("async_reliability_test", maxsize=1500)
        total_messages = 1000
        sent_ids = set()
        received_ids = set()

        async def producer():
            for i in range(total_messages):
                msg_id = f"msg_{i:04d}"
                sent_ids.add(msg_id)
                msg = EnvSensorData(
                    sensor_id=msg_id,
                    shelf_id="shelf_01",
                    slot_id=f"slot_{i:03d}",
                    temperature=20.0 + i * 0.01,
                    humidity=50.0,
                    light=30.0,
                    voc=100.0,
                    mold_spore=50.0,
                )
                await queue.put(msg)

        async def consumer():
            count = 0
            while count < total_messages:
                msg = await queue.get(timeout=2.0)
                if msg is not None:
                    received_ids.add(msg.sensor_id)
                    count += 1

        async def run_test():
            await asyncio.gather(producer(), consumer())

        asyncio.run(run_test())

        assert len(received_ids) == total_messages
        assert sent_ids == received_ids

        stats = queue.get_stats()
        assert stats.total_put == total_messages
        assert stats.total_get == total_messages
        assert stats.total_dropped == 0

    def test_process_queue_1000_messages_no_loss(self):
        with patch('multiprocessing.Queue') as mock_queue_class, \
             patch('multiprocessing.Lock'):

            mock_queue = MagicMock()
            mock_queue_class.return_value = mock_queue
            mock_queue.full.return_value = False
            mock_queue.empty.return_value = False

            from app.core.queue_manager import ProcessQueueWrapper

            queue = ProcessQueueWrapper[SensorData]("process_reliability_test", maxsize=1500)
            total_messages = 1000
            sent_ids = set()

            for i in range(total_messages):
                msg_id = f"msg_{i:04d}"
                sent_ids.add(msg_id)
                msg = EnvSensorData(
                    sensor_id=msg_id,
                    shelf_id="shelf_01",
                    slot_id=f"slot_{i:03d}",
                    temperature=20.0 + i * 0.01,
                    humidity=50.0,
                    light=30.0,
                    voc=100.0,
                    mold_spore=50.0,
                )
                queue.put(msg)

            assert mock_queue.put.call_count == total_messages

            received_ids = set()
            mock_items = list(mock_queue.put.call_args_list)

            for i in range(total_messages):
                serialized_data = mock_items[i][0][0]
                mock_queue.get.return_value = serialized_data
                retrieved = queue.get()
                assert retrieved is not None
                received_ids.add(retrieved.sensor_id)

            assert len(received_ids) == total_messages
            assert sent_ids == received_ids

    def test_mixed_queue_communication_pipeline(self):
        queue_manager = QueueManager()
        total_messages = 1000
        sent_ids = set()
        received_ids = set()

        queue_manager.create_async_queue("to_aging", maxsize=1500)
        queue_manager.create_process_queue("aging_results", maxsize=1500)

        async def produce_to_aging():
            for i in range(total_messages):
                msg_id = f"aging_req_{i:04d}"
                sent_ids.add(msg_id)
                from app.core.messages import AgingPredictionRequest
                req = AgingPredictionRequest(
                    request_id=msg_id,
                    shelf_id="shelf_01",
                    slot_id=f"slot_{i:03d}",
                    temperature=22.5,
                    humidity=55.0,
                    ph_value=6.5,
                    paper_type="bamboo",
                )
                await queue_manager.put("to_aging", req)

        async def simulate_aging_engine():
            count = 0
            while count < total_messages:
                req = await queue_manager.get("to_aging", timeout=2.0)
                if req is not None:
                    from app.core.messages import AgingPredictionResult
                    result = AgingPredictionResult(
                        request_id=req.request_id,
                        shelf_id=req.shelf_id,
                        slot_id=req.slot_id,
                        predicted_ph=6.0,
                        ph_decay_rate=0.005,
                        expected_lifetime_years=50.0,
                        risk_level="low",
                    )
                    queue_manager.put_sync("aging_results", result)
                    count += 1

        async def consume_results():
            count = 0
            while count < total_messages:
                result = queue_manager.get_sync("aging_results", timeout=2.0)
                if result is not None:
                    received_ids.add(result.request_id)
                    count += 1

        async def run_pipeline():
            await asyncio.gather(
                produce_to_aging(),
                simulate_aging_engine(),
                consume_results(),
            )

        asyncio.run(run_pipeline())

        assert len(received_ids) == total_messages
        assert sent_ids == received_ids

        stats = queue_manager.get_all_stats()
        assert stats["async_queues"]["to_aging"]["total_put"] == total_messages
        assert stats["async_queues"]["to_aging"]["total_get"] == total_messages
        assert stats["async_queues"]["to_aging"]["total_dropped"] == 0

    def test_queue_manager_concurrent_access(self):
        queue_manager = QueueManager()
        num_queues = 3
        messages_per_queue = 500
        total_messages = num_queues * messages_per_queue

        for i in range(num_queues):
            queue_manager.create_async_queue(f"queue_{i}", maxsize=1000)

        sent_messages = {f"queue_{i}": set() for i in range(num_queues)}
        received_messages = {f"queue_{i}": set() for i in range(num_queues)}

        async def producer(queue_name: str, start_id: int):
            for i in range(messages_per_queue):
                msg_id = f"{queue_name}_msg_{start_id + i:04d}"
                sent_messages[queue_name].add(msg_id)
                msg = EnvSensorData(
                    sensor_id=msg_id,
                    shelf_id="shelf_01",
                    slot_id=f"slot_{i:03d}",
                    temperature=20.0 + i * 0.01,
                    humidity=50.0,
                    light=30.0,
                    voc=100.0,
                    mold_spore=50.0,
                )
                await queue_manager.put(queue_name, msg)

        async def consumer(queue_name: str):
            count = 0
            while count < messages_per_queue:
                msg = await queue_manager.get(queue_name, timeout=2.0)
                if msg is not None:
                    received_messages[queue_name].add(msg.sensor_id)
                    count += 1

        async def run_concurrent():
            producers = [producer(f"queue_{i}", i * 1000) for i in range(num_queues)]
            consumers = [consumer(f"queue_{i}") for i in range(num_queues)]
            await asyncio.gather(*producers, *consumers)

        asyncio.run(run_concurrent())

        for i in range(num_queues):
            queue_name = f"queue_{i}"
            assert len(sent_messages[queue_name]) == messages_per_queue
            assert len(received_messages[queue_name]) == messages_per_queue
            assert sent_messages[queue_name] == received_messages[queue_name]

        total_received = sum(len(msgs) for msgs in received_messages.values())
        assert total_received == total_messages

    def test_queue_backpressure_no_loss_under_stress(self):
        queue = AsyncQueueWrapper[SensorData]("stress_test", maxsize=100)
        total_messages = 1000
        sent_ids = set()
        received_ids = set()

        async def fast_producer():
            for i in range(total_messages):
                msg_id = f"stress_{i:04d}"
                sent_ids.add(msg_id)
                msg = EnvSensorData(
                    sensor_id=msg_id,
                    shelf_id="shelf_01",
                    slot_id=f"slot_{i:03d}",
                    temperature=20.0 + i * 0.01,
                    humidity=50.0,
                    light=30.0,
                    voc=100.0,
                    mold_spore=50.0,
                )
                await queue.put(msg)

        async def slow_consumer():
            count = 0
            while count < total_messages:
                msg = await queue.get(timeout=5.0)
                if msg is not None:
                    received_ids.add(msg.sensor_id)
                    count += 1
                    await asyncio.sleep(0.005)

        async def run_stress():
            await asyncio.gather(fast_producer(), slow_consumer())

        asyncio.run(run_stress())

        assert len(received_ids) == total_messages
        assert sent_ids == received_ids

        stats = queue.get_stats()
        assert stats.total_put == total_messages
        assert stats.total_get == total_messages
        assert stats.total_dropped == 0, "背压控制下不应有消息丢失"
