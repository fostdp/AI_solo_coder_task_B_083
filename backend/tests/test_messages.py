import json
import pytest
from datetime import datetime
from typing import Dict, Any
import uuid
from unittest.mock import patch

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.core.messages import (
        Message,
        SensorData,
        EnvSensorData,
        PhSensorData,
        AgingPredictionRequest,
        AgingPredictionResult,
        MoldPredictionRequest,
        MoldPredictionResult,
        AlertMessage,
        ClickHouseRecord,
        ControlMessage,
        deserialize_message,
        serialize_message,
        MESSAGE_CLASSES,
    )


class TestBaseMessage:
    def test_message_defaults(self):
        msg = Message()
        
        assert msg.message_id is not None
        assert len(msg.message_id) > 0
        assert msg.timestamp is not None
        assert msg.message_type == "data"
        
        try:
            uuid.UUID(msg.message_id)
            valid_uuid = True
        except ValueError:
            valid_uuid = False
        assert valid_uuid

    def test_message_custom(self):
        custom_id = "custom-id-123"
        custom_ts = "2024-01-15T10:30:00"
        msg = Message(
            message_id=custom_id,
            timestamp=custom_ts,
            message_type="custom"
        )
        
        assert msg.message_id == custom_id
        assert msg.timestamp == custom_ts
        assert msg.message_type == "custom"

    def test_to_dict(self):
        msg = Message(
            message_id="test-id",
            timestamp="2024-01-15T10:30:00",
            message_type="test"
        )
        
        d = msg.to_dict()
        
        assert isinstance(d, dict)
        assert d["message_id"] == "test-id"
        assert d["timestamp"] == "2024-01-15T10:30:00"
        assert d["message_type"] == "test"

    def test_to_json(self):
        msg = Message(
            message_id="test-id",
            timestamp="2024-01-15T10:30:00",
            message_type="test"
        )
        
        json_str = msg.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["message_id"] == "test-id"
        assert parsed["timestamp"] == "2024-01-15T10:30:00"
        assert parsed["message_type"] == "test"


class TestSensorData:
    def test_sensor_data_defaults(self):
        data = SensorData()
        
        assert data.sensor_id == ""
        assert data.shelf_id == ""
        assert data.slot_id == ""
        assert data.sensor_type == ""
        assert data.data == {}
        assert data.is_valid is True
        assert data.validation_errors == []
        assert data.message_type == "sensor_data"

    def test_sensor_data_custom(self):
        data = SensorData(
            sensor_id="sensor_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            sensor_type="environment",
            data={"temperature": 22.5},
            is_valid=False,
            validation_errors=["温度异常"]
        )
        
        assert data.sensor_id == "sensor_001"
        assert data.shelf_id == "shelf_01"
        assert data.slot_id == "slot_001"
        assert data.sensor_type == "environment"
        assert data.data == {"temperature": 22.5}
        assert data.is_valid is False
        assert data.validation_errors == ["温度异常"]

    def test_sensor_data_to_dict(self):
        data = SensorData(
            sensor_id="sensor_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            sensor_type="environment",
            data={"temperature": 22.5}
        )
        
        d = data.to_dict()
        
        assert d["sensor_id"] == "sensor_001"
        assert d["shelf_id"] == "shelf_01"
        assert d["slot_id"] == "slot_001"
        assert d["sensor_type"] == "environment"
        assert d["data"] == {"temperature": 22.5}
        assert d["message_type"] == "sensor_data"


class TestEnvSensorData:
    def test_env_sensor_data_defaults(self):
        data = EnvSensorData()
        
        assert data.sensor_type == "environment"
        assert data.temperature == 0.0
        assert data.humidity == 0.0
        assert data.light == 0.0
        assert data.voc == 0.0
        assert data.mold_spore == 0.0
        assert data.message_type == "sensor_data"

    def test_env_sensor_data_custom(self, sample_env_sensor_data):
        data = EnvSensorData(
            sensor_id="env_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            temperature=22.5,
            humidity=55.0,
            light=30.0,
            voc=150.0,
            mold_spore=100.0,
        )
        
        assert data.sensor_id == "env_001"
        assert data.temperature == pytest.approx(22.5)
        assert data.humidity == pytest.approx(55.0)
        assert data.light == pytest.approx(30.0)
        assert data.voc == pytest.approx(150.0)
        assert data.mold_spore == pytest.approx(100.0)
        assert data.sensor_type == "environment"

    def test_env_sensor_data_serialization(self):
        data = EnvSensorData(
            sensor_id="env_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            temperature=22.5,
            humidity=55.0,
        )
        
        d = data.to_dict()
        
        assert d["temperature"] == pytest.approx(22.5)
        assert d["humidity"] == pytest.approx(55.0)
        assert d["sensor_type"] == "environment"


class TestPhSensorData:
    def test_ph_sensor_data_defaults(self):
        data = PhSensorData()
        
        assert data.sensor_type == "ph"
        assert data.ph_value == 0.0
        assert data.message_type == "sensor_data"

    def test_ph_sensor_data_custom(self):
        data = PhSensorData(
            sensor_id="ph_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            ph_value=6.8,
        )
        
        assert data.sensor_id == "ph_001"
        assert data.ph_value == pytest.approx(6.8)
        assert data.sensor_type == "ph"


class TestAgingPredictionMessages:
    def test_aging_prediction_request_defaults(self):
        req = AgingPredictionRequest()
        
        assert req.message_type == "aging_prediction_request"
        assert req.shelf_id == ""
        assert req.slot_id == ""
        assert req.paper_type == "bamboo"
        assert req.current_ph == pytest.approx(7.0)
        assert req.temperature == pytest.approx(20.0)
        assert req.humidity == pytest.approx(50.0)
        assert req.ph_history == []
        assert req.prediction_days == [30, 90, 180]

    def test_aging_prediction_request_custom(self):
        history = [
            {"date": "2024-01-01", "ph": 6.8},
            {"date": "2024-01-15", "ph": 6.7}
        ]
        req = AgingPredictionRequest(
            shelf_id="shelf_01",
            slot_id="slot_001",
            paper_type="rice",
            current_ph=6.5,
            temperature=25.0,
            humidity=60.0,
            ph_history=history,
            prediction_days=[7, 30, 90, 180, 365]
        )
        
        assert req.shelf_id == "shelf_01"
        assert req.paper_type == "rice"
        assert req.current_ph == pytest.approx(6.5)
        assert req.ph_history == history
        assert req.prediction_days == [7, 30, 90, 180, 365]

    def test_aging_prediction_result_defaults(self):
        result = AgingPredictionResult()
        
        assert result.message_type == "aging_prediction_result"
        assert result.ph_decay_rate == pytest.approx(0.0)
        assert result.predicted_lifetime_years == pytest.approx(0.0)
        assert result.ph_predictions == {}
        assert result.severity == "normal"
        assert result.daily_history == []

    def test_aging_prediction_result_custom(self):
        predictions = {30: 6.4, 90: 6.2, 180: 6.0}
        history = [{"date": "2024-01-15", "ph": 6.5}]
        
        result = AgingPredictionResult(
            shelf_id="shelf_01",
            slot_id="slot_001",
            paper_type="bamboo",
            ph_decay_rate=0.005,
            predicted_lifetime_years=50.0,
            ph_predictions=predictions,
            severity="warning",
            daily_history=history,
        )
        
        assert result.ph_decay_rate == pytest.approx(0.005)
        assert result.predicted_lifetime_years == pytest.approx(50.0)
        assert result.ph_predictions == predictions
        assert result.severity == "warning"
        assert result.daily_history == history


class TestMoldPredictionMessages:
    def test_mold_prediction_request_defaults(self):
        req = MoldPredictionRequest()
        
        assert req.message_type == "mold_prediction_request"
        assert req.temperature == pytest.approx(20.0)
        assert req.humidity == pytest.approx(50.0)
        assert req.current_spores == pytest.approx(0.0)
        assert req.mold_type == "mixed"

    def test_mold_prediction_request_custom(self):
        req = MoldPredictionRequest(
            shelf_id="shelf_01",
            slot_id="slot_001",
            temperature=25.0,
            humidity=85.0,
            current_spores=500.0,
            mold_type="aspergillus",
        )
        
        assert req.temperature == pytest.approx(25.0)
        assert req.humidity == pytest.approx(85.0)
        assert req.current_spores == pytest.approx(500.0)
        assert req.mold_type == "aspergillus"

    def test_mold_prediction_result_defaults(self):
        result = MoldPredictionResult()
        
        assert result.message_type == "mold_prediction_result"
        assert result.risk_score == pytest.approx(0.0)
        assert result.risk_level == "negligible"
        assert result.growth_rate == pytest.approx(0.0)
        assert result.predicted_spores_7d == pytest.approx(0.0)
        assert result.predicted_spores_30d == pytest.approx(0.0)
        assert result.is_active_mold == False

    def test_mold_prediction_result_custom(self):
        result = MoldPredictionResult(
            shelf_id="shelf_01",
            slot_id="slot_001",
            risk_score=0.75,
            risk_level="high",
            growth_rate=0.05,
            predicted_spores_7d=1500.0,
            predicted_spores_30d=5000.0,
            is_active_mold=True,
        )
        
        assert result.risk_score == pytest.approx(0.75)
        assert result.risk_level == "high"
        assert result.growth_rate == pytest.approx(0.05)
        assert result.predicted_spores_7d == pytest.approx(1500.0)
        assert result.predicted_spores_30d == pytest.approx(5000.0)
        assert result.is_active_mold is True


class TestAlertMessage:
    def test_alert_message_defaults(self):
        alert = AlertMessage()
        
        assert alert.message_type == "alert"
        assert alert.alert_id is not None
        assert alert.shelf_id == ""
        assert alert.slot_id == ""
        assert alert.alert_level == "yellow"
        assert alert.alert_type == ""
        assert alert.alert_value == pytest.approx(0.0)
        assert alert.threshold == pytest.approx(0.0)
        assert alert.message == ""
        assert alert.is_handled == False

    def test_alert_message_custom(self, sample_alert_msg):
        assert sample_alert_msg.shelf_id == "shelf_01"
        assert sample_alert_msg.slot_id == "slot_001"
        assert sample_alert_msg.alert_level == "yellow"
        assert sample_alert_msg.alert_type == "ph_low"
        assert sample_alert_msg.alert_value == pytest.approx(6.2)
        assert sample_alert_msg.threshold == pytest.approx(6.5)
        assert sample_alert_msg.message == "pH值偏低"
        assert sample_alert_msg.is_handled == False

    def test_alert_message_serialization(self):
        alert = AlertMessage(
            shelf_id="shelf_01",
            slot_id="slot_001",
            alert_level="red",
            alert_type="mold_high",
            alert_value=1000.0,
            threshold=500.0,
            message="霉菌超标",
            is_handled=True,
        )
        
        d = alert.to_dict()
        
        assert d["alert_level"] == "red"
        assert d["alert_type"] == "mold_high"
        assert d["alert_value"] == pytest.approx(1000.0)
        assert d["threshold"] == pytest.approx(500.0)
        assert d["message"] == "霉菌超标"
        assert d["is_handled"] is True


class TestOtherMessages:
    def test_clickhouse_record_defaults(self):
        record = ClickHouseRecord()
        
        assert record.message_type == "clickhouse_record"
        assert record.table_name == ""
        assert record.record == {}

    def test_clickhouse_record_custom(self):
        record = ClickHouseRecord(
            table_name="env_sensor_data",
            record={"temperature": 22.5, "humidity": 55.0}
        )
        
        assert record.table_name == "env_sensor_data"
        assert record.record == {"temperature": 22.5, "humidity": 55.0}

    def test_control_message_defaults(self):
        msg = ControlMessage()
        
        assert msg.message_type == "control"
        assert msg.action == ""
        assert msg.params == {}

    def test_control_message_custom(self):
        msg = ControlMessage(
            action="flush",
            params={"table": "env_sensor_data"}
        )
        
        assert msg.action == "flush"
        assert msg.params == {"table": "env_sensor_data"}


class TestMessageClasses:
    def test_message_classes_mapping(self):
        assert "sensor_data" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["sensor_data"] == SensorData
        assert "aging_prediction_request" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["aging_prediction_request"] == AgingPredictionRequest
        assert "aging_prediction_result" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["aging_prediction_result"] == AgingPredictionResult
        assert "mold_prediction_request" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["mold_prediction_request"] == MoldPredictionRequest
        assert "mold_prediction_result" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["mold_prediction_result"] == MoldPredictionResult
        assert "alert" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["alert"] == AlertMessage
        assert "clickhouse_record" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["clickhouse_record"] == ClickHouseRecord
        assert "control" in MESSAGE_CLASSES
        assert MESSAGE_CLASSES["control"] == ControlMessage


class TestDeserializeMessage:
    def test_deserialize_sensor_data(self):
        data = {
            "message_id": "test-id",
            "timestamp": "2024-01-15T10:30:00",
            "message_type": "sensor_data",
            "sensor_id": "env_001",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "sensor_type": "environment",
            "data": {"temperature": 22.5, "humidity": 55.0},
            "is_valid": True,
            "validation_errors": [],
            "extra_field": "should_be_ignored"
        }
        
        msg = deserialize_message(data)
        
        assert isinstance(msg, SensorData)
        assert msg.message_id == "test-id"
        assert msg.sensor_id == "env_001"
        assert msg.shelf_id == "shelf_01"
        assert msg.slot_id == "slot_001"
        assert msg.sensor_type == "environment"
        assert msg.data == {"temperature": 22.5, "humidity": 55.0}
        assert msg.is_valid is True
        assert msg.validation_errors == []

    def test_deserialize_alert(self):
        data = {
            "message_id": "alert-id",
            "timestamp": "2024-01-15T10:30:00",
            "message_type": "alert",
            "alert_id": "alert-123",
            "shelf_id": "shelf_01",
            "slot_id": "slot_001",
            "alert_level": "red",
            "alert_type": "ph_low",
            "alert_value": 5.5,
            "threshold": 6.5,
            "message": "pH值严重偏低",
            "is_handled": False
        }
        
        msg = deserialize_message(data)
        
        assert isinstance(msg, AlertMessage)
        assert msg.alert_id == "alert-123"
        assert msg.alert_level == "red"
        assert msg.alert_value == pytest.approx(5.5)

    def test_deserialize_unknown_type(self):
        data = {
            "message_id": "test-id",
            "timestamp": "2024-01-15T10:30:00",
            "message_type": "unknown_type",
            "custom_field": "value"
        }
        
        msg = deserialize_message(data)
        
        assert isinstance(msg, Message)
        assert msg.message_id == "test-id"
        assert msg.timestamp == "2024-01-15T10:30:00"
        assert msg.message_type == "unknown_type"

    def test_deserialize_invalid_data_fallback(self):
        data = {
            "message_type": "sensor_data",
            "invalid_field": "value",
            "temperature": "not_a_number"
        }
        
        msg = deserialize_message(data)
        
        assert isinstance(msg, SensorData)

    def test_deserialize_empty_data(self):
        data = {}
        
        msg = deserialize_message(data)
        
        assert isinstance(msg, Message)
        assert msg.message_type == "data"


class TestSerializeMessage:
    def test_serialize_basic(self, sample_sensor_data_msg):
        result = serialize_message(sample_sensor_data_msg)
        
        assert isinstance(result, dict)
        assert result["sensor_id"] == "env_001"
        assert result["shelf_id"] == "shelf_01"
        assert result["temperature"] == pytest.approx(22.5)
        assert result["message_type"] == "sensor_data"

    def test_serialize_alert(self, sample_alert_msg):
        result = serialize_message(sample_alert_msg)
        
        assert isinstance(result, dict)
        assert result["shelf_id"] == "shelf_01"
        assert result["alert_level"] == "yellow"
        assert result["message_type"] == "alert"

    def test_serialize_matches_to_dict(self, sample_sensor_data_msg):
        serialized = serialize_message(sample_sensor_data_msg)
        to_dict_result = sample_sensor_data_msg.to_dict()
        
        assert serialized == to_dict_result


class TestMessageRoundTrip:
    def test_sensor_data_round_trip(self):
        original = SensorData(
            sensor_id="env_001",
            shelf_id="shelf_01",
            slot_id="slot_001",
            sensor_type="environment",
            data={"temperature": 22.5, "humidity": 55.0},
        )
        
        serialized = serialize_message(original)
        deserialized = deserialize_message(serialized)
        
        assert isinstance(deserialized, SensorData)
        assert deserialized.sensor_id == original.sensor_id
        assert deserialized.shelf_id == original.shelf_id
        assert deserialized.slot_id == original.slot_id
        assert deserialized.sensor_type == original.sensor_type
        assert deserialized.data == original.data

    def test_alert_round_trip(self):
        original = AlertMessage(
            shelf_id="shelf_01",
            slot_id="slot_001",
            alert_level="orange",
            alert_type="mold_spore_high",
            alert_value=1500.0,
            threshold=500.0,
            message="霉菌孢子浓度过高",
        )
        
        serialized = serialize_message(original)
        deserialized = deserialize_message(serialized)
        
        assert isinstance(deserialized, AlertMessage)
        assert deserialized.shelf_id == original.shelf_id
        assert deserialized.alert_level == original.alert_level
        assert deserialized.alert_value == pytest.approx(original.alert_value)
        assert deserialized.message == original.message
