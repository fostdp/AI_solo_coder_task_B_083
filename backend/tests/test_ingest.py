import pytest
from unittest.mock import MagicMock, patch
import json
from typing import Dict, Any

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.ingest import DataValidator, DataCleaner, MQTTDataHandler
    from app.core.messages import EnvSensorData, PhSensorData


class TestDataValidator:
    def test_default_ranges(self):
        validator = DataValidator()
        
        assert "temperature" in validator.validation_ranges
        assert "humidity" in validator.validation_ranges
        assert "ph" in validator.validation_ranges
        assert "light" in validator.validation_ranges
        assert "voc" in validator.validation_ranges
        assert "mold_spore" in validator.validation_ranges
        
        assert validator.validation_ranges["temperature"] == (-10, 50)
        assert validator.validation_ranges["humidity"] == (0, 100)
        assert validator.validation_ranges["ph"] == (3, 9)

    def test_custom_ranges(self):
        custom_ranges = {
            "temperature": (0, 40),
            "humidity": (30, 70),
        }
        validator = DataValidator(validation_ranges=custom_ranges)
        
        assert validator.validation_ranges["temperature"] == (0, 40)
        assert validator.validation_ranges["humidity"] == (30, 70)

    def test_validate_temperature_valid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_temperature(22.5)
        assert valid is True
        assert err is None
        
        valid, err = validator.validate_temperature(-10)
        assert valid is True
        
        valid, err = validator.validate_temperature(50)
        assert valid is True

    def test_validate_temperature_invalid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_temperature(-15)
        assert valid is False
        assert "温度超出范围" in err
        
        valid, err = validator.validate_temperature(60)
        assert valid is False
        assert "温度超出范围" in err

    def test_validate_humidity_valid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_humidity(55)
        assert valid is True
        assert err is None
        
        valid, err = validator.validate_humidity(0)
        assert valid is True
        
        valid, err = validator.validate_humidity(100)
        assert valid is True

    def test_validate_humidity_invalid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_humidity(-5)
        assert valid is False
        assert "湿度超出范围" in err
        
        valid, err = validator.validate_humidity(150)
        assert valid is False
        assert "湿度超出范围" in err

    def test_validate_ph_valid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_ph(6.8)
        assert valid is True
        assert err is None
        
        valid, err = validator.validate_ph(3)
        assert valid is True
        
        valid, err = validator.validate_ph(9)
        assert valid is True

    def test_validate_ph_invalid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_ph(2.5)
        assert valid is False
        assert "pH值超出范围" in err
        
        valid, err = validator.validate_ph(10)
        assert valid is False
        assert "pH值超出范围" in err

    def test_validate_light_valid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_light(30)
        assert valid is True
        assert err is None
        
        valid, err = validator.validate_light(0)
        assert valid is True
        
        valid, err = validator.validate_light(1000)
        assert valid is True

    def test_validate_light_invalid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_light(-10)
        assert valid is False
        assert "光照超出范围" in err
        
        valid, err = validator.validate_light(2000)
        assert valid is False
        assert "光照超出范围" in err

    def test_validate_voc_valid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_voc(150)
        assert valid is True
        assert err is None
        
        valid, err = validator.validate_voc(0)
        assert valid is True
        
        valid, err = validator.validate_voc(2000)
        assert valid is True

    def test_validate_voc_invalid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_voc(-50)
        assert valid is False
        assert "VOC超出范围" in err
        
        valid, err = validator.validate_voc(3000)
        assert valid is False
        assert "VOC超出范围" in err

    def test_validate_mold_spore_valid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_mold_spore(100)
        assert valid is True
        assert err is None
        
        valid, err = validator.validate_mold_spore(0)
        assert valid is True
        
        valid, err = validator.validate_mold_spore(100000)
        assert valid is True

    def test_validate_mold_spore_invalid(self):
        validator = DataValidator()
        
        valid, err = validator.validate_mold_spore(-100)
        assert valid is False
        assert "霉菌孢子超出范围" in err
        
        valid, err = validator.validate_mold_spore(200000)
        assert valid is False
        assert "霉菌孢子超出范围" in err

    def test_validate_boundary_values(self):
        validator = DataValidator()
        
        valid, _ = validator.validate_temperature(-10.0)
        assert valid is True
        valid, _ = validator.validate_temperature(-9.9)
        assert valid is True
        valid, _ = validator.validate_temperature(50.0)
        assert valid is True
        valid, _ = validator.validate_temperature(50.1)
        assert valid is False


class TestDataCleaner:
    def test_check_required_fields_all_present(self):
        cleaner = DataCleaner()
        data = {"a": 1, "b": 2, "c": 3}
        required = ["a", "b", "c"]
        
        has_all, missing = cleaner.check_required_fields(data, required)
        assert has_all is True
        assert missing == []

    def test_check_required_fields_some_missing(self):
        cleaner = DataCleaner()
        data = {"a": 1, "c": 3}
        required = ["a", "b", "c"]
        
        has_all, missing = cleaner.check_required_fields(data, required)
        assert has_all is False
        assert "b" in missing

    def test_clean_env_data_valid(self, sample_env_sensor_data):
        cleaner = DataCleaner()
        data, errors = cleaner.clean_env_data(sample_env_sensor_data)
        
        assert data is not None
        assert isinstance(data, EnvSensorData)
        assert data.sensor_id == "env_001"
        assert data.shelf_id == "shelf_01"
        assert data.slot_id == "slot_001"
        assert data.temperature == pytest.approx(22.5)
        assert data.humidity == pytest.approx(55.0)
        assert data.light == pytest.approx(30.0)
        assert data.voc == pytest.approx(150.0)
        assert data.mold_spore == pytest.approx(100.0)
        assert data.is_valid is True
        assert errors == []

    def test_clean_env_data_with_timestamp(self, sample_env_sensor_data):
        sample_env_sensor_data["timestamp"] = "2024-01-15T10:30:00"
        
        cleaner = DataCleaner()
        data, errors = cleaner.clean_env_data(sample_env_sensor_data)
        
        assert data.timestamp == "2024-01-15T10:30:00"

    def test_clean_env_data_missing_fields(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "temperature": 22.5,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is None
        assert len(errors) > 0
        assert "缺少必要字段" in errors[0]

    def test_clean_env_data_invalid_numeric(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": "not_a_number",
            "humidity": 55.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is None
        assert len(errors) > 0
        assert "数值转换失败" in errors[0]

    def test_clean_env_data_out_of_range(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 100.0,
            "humidity": 150.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.is_valid is False
        assert len(errors) == 2
        assert any("温度超出范围" in e for e in errors)
        assert any("湿度超出范围" in e for e in errors)

    def test_clean_env_data_string_numbers(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": "22.5",
            "humidity": "55",
            "light": "30.0",
            "voc": "150",
            "mold_spore": "100.5",
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.temperature == pytest.approx(22.5)
        assert result.humidity == pytest.approx(55.0)
        assert result.is_valid is True
        assert errors == []

    def test_clean_env_data_none_value(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": None,
            "humidity": 55.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is None
        assert len(errors) > 0

    def test_clean_ph_data_valid(self, sample_ph_sensor_data):
        cleaner = DataCleaner()
        data, errors = cleaner.clean_ph_data(sample_ph_sensor_data)
        
        assert data is not None
        assert isinstance(data, PhSensorData)
        assert data.sensor_id == "ph_001"
        assert data.shelf_id == "shelf_01"
        assert data.slot_id == "slot_001"
        assert data.ph_value == pytest.approx(6.8)
        assert data.is_valid is True
        assert errors == []

    def test_clean_ph_data_missing_fields(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "ph_001",
            "ph_value": 6.8,
        }
        
        result, errors = cleaner.clean_ph_data(data)
        
        assert result is None
        assert len(errors) > 0
        assert "缺少必要字段" in errors[0]

    def test_clean_ph_data_invalid_numeric(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "ph_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "ph_value": "not_a_number",
        }
        
        result, errors = cleaner.clean_ph_data(data)
        
        assert result is None
        assert len(errors) > 0
        assert "pH值转换失败" in errors[0]

    def test_clean_ph_data_out_of_range(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "ph_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "ph_value": 1.0,
        }
        
        result, errors = cleaner.clean_ph_data(data)
        
        assert result is not None
        assert result.is_valid is False
        assert len(errors) == 1
        assert "pH值超出范围" in errors[0]

    def test_clean_ph_data_string_number(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "ph_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "ph_value": "6.8",
        }
        
        result, errors = cleaner.clean_ph_data(data)
        
        assert result is not None
        assert result.ph_value == pytest.approx(6.8)
        assert result.is_valid is True
        assert errors == []

    def test_clean_ph_data_with_timestamp(self, sample_ph_sensor_data):
        sample_ph_sensor_data["timestamp"] = "2024-01-15T10:30:00"
        
        cleaner = DataCleaner()
        data, errors = cleaner.clean_ph_data(sample_ph_sensor_data)
        
        assert data.timestamp == "2024-01-15T10:30:00"

    def test_clean_data_extra_fields(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 22.5,
            "humidity": 55.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
            "extra_field_1": "value1",
            "extra_field_2": 123,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.is_valid is True
        assert errors == []

    def test_clean_data_boundary_values(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": -10.0,
            "humidity": 0.0,
            "light": 1000.0,
            "voc": 2000.0,
            "mold_spore": 100000.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.is_valid is True
        assert errors == []


class TestMQTTDataHandler:
    def test_handle_env_message(self, sample_env_sensor_data):
        handler = MQTTDataHandler()
        
        result = handler.handle_message("library/env/sensor_001", sample_env_sensor_data)
        
        assert result is not None
        assert isinstance(result, EnvSensorData)
        assert result.sensor_id == "env_001"
        
        stats = handler.get_stats()
        assert stats["total_received"] == 1
        assert stats["env_messages"] == 1
        assert stats["valid_messages"] == 1
        assert stats["invalid_messages"] == 0

    def test_handle_ph_message(self, sample_ph_sensor_data):
        handler = MQTTDataHandler()
        
        result = handler.handle_message("library/ph/sensor_001", sample_ph_sensor_data)
        
        assert result is not None
        assert isinstance(result, PhSensorData)
        assert result.sensor_id == "ph_001"
        
        stats = handler.get_stats()
        assert stats["total_received"] == 1
        assert stats["ph_messages"] == 1
        assert stats["valid_messages"] == 1

    def test_handle_unknown_topic(self, sample_env_sensor_data):
        handler = MQTTDataHandler()
        
        result = handler.handle_message("unknown/topic", sample_env_sensor_data)
        
        assert result is None
        
        stats = handler.get_stats()
        assert stats["total_received"] == 1
        assert stats["env_messages"] == 0
        assert stats["ph_messages"] == 0
        assert stats["valid_messages"] == 0
        assert stats["invalid_messages"] == 0

    def test_handle_invalid_env_message(self):
        handler = MQTTDataHandler()
        invalid_data = {
            "sensor_id": "env_001",
            "temperature": "invalid",
        }
        
        result = handler.handle_message("library/env/sensor_001", invalid_data)
        
        assert result is None
        
        stats = handler.get_stats()
        assert stats["total_received"] == 1
        assert stats["env_messages"] == 1
        assert stats["invalid_messages"] == 1

    def test_handle_out_of_range_data(self):
        handler = MQTTDataHandler()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 100.0,
            "humidity": 55.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
        }
        
        result = handler.handle_message("library/env/sensor_001", data)
        
        assert result is not None
        assert result.is_valid is False
        
        stats = handler.get_stats()
        assert stats["invalid_messages"] == 1

    def test_handle_message_exception(self):
        handler = MQTTDataHandler()
        
        with patch.object(handler, '_handle_env_message') as mock_handle:
            mock_handle.side_effect = Exception("Test error")
            
            result = handler.handle_message("library/env/sensor_001", {})
            
            assert result is None
            
            stats = handler.get_stats()
            assert stats["invalid_messages"] == 1

    def test_stats_tracking(self, sample_env_sensor_data, sample_ph_sensor_data):
        handler = MQTTDataHandler()
        
        for _ in range(5):
            handler.handle_message("library/env/sensor_001", sample_env_sensor_data)
        
        for _ in range(3):
            handler.handle_message("library/ph/sensor_001", sample_ph_sensor_data)
        
        handler.handle_message("library/env/sensor_001", {"invalid": "data"})
        
        stats = handler.get_stats()
        assert stats["total_received"] == 9
        assert stats["env_messages"] == 6
        assert stats["ph_messages"] == 3
        assert stats["valid_messages"] == 8
        assert stats["invalid_messages"] == 1

    def test_reset_stats(self, sample_env_sensor_data):
        handler = MQTTDataHandler()
        
        handler.handle_message("library/env/sensor_001", sample_env_sensor_data)
        
        stats = handler.get_stats()
        assert stats["total_received"] == 1
        
        handler.reset_stats()
        
        stats = handler.get_stats()
        assert stats["total_received"] == 0
        assert stats["valid_messages"] == 0
        assert stats["invalid_messages"] == 0

    def test_get_stats_returns_copy(self, sample_env_sensor_data):
        handler = MQTTDataHandler()
        
        handler.handle_message("library/env/sensor_001", sample_env_sensor_data)
        
        stats1 = handler.get_stats()
        stats1["total_received"] = 999
        
        stats2 = handler.get_stats()
        assert stats2["total_received"] == 1

    def test_multiple_topics(self, sample_env_sensor_data, sample_ph_sensor_data):
        handler = MQTTDataHandler()
        
        topics = [
            "library/env/shelf_01",
            "library/env/shelf_02",
            "library/ph/shelf_01",
            "library/env/shelf_03",
            "library/ph/shelf_02",
        ]
        
        for topic in topics:
            if "env" in topic:
                handler.handle_message(topic, sample_env_sensor_data)
            else:
                handler.handle_message(topic, sample_ph_sensor_data)
        
        stats = handler.get_stats()
        assert stats["total_received"] == 5
        assert stats["env_messages"] == 3
        assert stats["ph_messages"] == 2
        assert stats["valid_messages"] == 5


class TestMQTTClientIntegration:
    def test_mqtt_subscriber_message_handling(self, sample_env_sensor_data):
        handler = MQTTDataHandler()
        
        with patch('paho.mqtt.client.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
            from app.mqtt_subscriber import MQTTSubscriber
            subscriber = MQTTSubscriber()
            
            mock_msg = MagicMock()
            mock_msg.topic = "library/env/sensor_001"
            mock_msg.payload = json.dumps(sample_env_sensor_data).encode("utf-8")
            
            with patch.object(subscriber, '_handle_env_data') as mock_handle:
                subscriber.on_message(mock_client, None, mock_msg)
                
                mock_handle.assert_called_once()
                call_args = mock_handle.call_args[0][0]
                assert call_args["sensor_id"] == "env_001"

    def test_mqtt_subscriber_env_data_validation(self, mock_clickhouse_client):
        from app.mqtt_subscriber import MQTTSubscriber
        from app.database import db_manager
        
        with patch.object(db_manager, 'client', mock_clickhouse_client):
            with patch.object(db_manager, 'batch_writer', MagicMock()):
                subscriber = MQTTSubscriber()
                
                valid_data = {
                    "sensor_id": "env_001",
                    "shelf_id": "shelf_01",
                    "slot_id": "slot_001",
                    "temperature": 22.5,
                    "humidity": 55.0,
                    "light": 30.0,
                    "voc": 150.0,
                    "mold_spore": 100.0,
                }
                
                subscriber._handle_env_data(valid_data)
                
                invalid_data = {
                    "sensor_id": "env_001",
                    "temperature": 22.5,
                }
                
                subscriber._handle_env_data(invalid_data)

    def test_mqtt_subscriber_ph_data_validation(self, mock_clickhouse_client):
        from app.mqtt_subscriber import MQTTSubscriber
        from app.database import db_manager
        
        with patch.object(db_manager, 'client', mock_clickhouse_client):
            with patch.object(db_manager, 'batch_writer', MagicMock()):
                subscriber = MQTTSubscriber()
                
                valid_data = {
                    "sensor_id": "ph_001",
                    "shelf_id": "shelf_01",
                    "slot_id": "slot_001",
                    "ph_value": 6.8,
                }
                
                subscriber._handle_ph_data(valid_data)
                
                invalid_data = {
                    "sensor_id": "ph_001",
                    "ph_value": 6.8,
                }
                
                subscriber._handle_ph_data(invalid_data)


class TestEdgeCases:
    def test_empty_string_values(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "",
            "shelf_id": "",
            "slot_id": "",
            "temperature": 22.5,
            "humidity": 55.0,
            "light": 30.0,
            "voc": 150.0,
            "mold_spore": 100.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.sensor_id == ""
        assert result.is_valid is True

    def test_negative_valid_values(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": -5.0,
            "humidity": 0.0,
            "light": 0.0,
            "voc": 0.0,
            "mold_spore": 0.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.temperature == pytest.approx(-5.0)
        assert result.is_valid is True

    def test_large_valid_values(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 50.0,
            "humidity": 100.0,
            "light": 1000.0,
            "voc": 2000.0,
            "mold_spore": 100000.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.is_valid is True

    def test_scientific_notation(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 2.25e1,
            "humidity": 5.5e1,
            "light": 3e1,
            "voc": 1.5e2,
            "mold_spore": 1e2,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.temperature == pytest.approx(22.5)
        assert result.is_valid is True

    def test_integer_values(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 22,
            "humidity": 55,
            "light": 30,
            "voc": 150,
            "mold_spore": 100,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.temperature == pytest.approx(22.0)
        assert result.humidity == pytest.approx(55.0)
        assert result.is_valid is True

    def test_multiple_validation_errors(self):
        cleaner = DataCleaner()
        data = {
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "temperature": 100.0,
            "humidity": -10.0,
            "light": 2000.0,
            "voc": -50.0,
            "mold_spore": 200000.0,
        }
        
        result, errors = cleaner.clean_env_data(data)
        
        assert result is not None
        assert result.is_valid is False
        assert len(errors) == 5
