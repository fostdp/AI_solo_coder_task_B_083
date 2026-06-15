import pytest
import asyncio
import os
import sys
from unittest.mock import MagicMock, patch
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.core.messages import SensorData, EnvSensorData, PhSensorData, AlertMessage
    from app.core.queue_manager import QueueManager, AsyncQueueWrapper, ProcessQueueWrapper
    from app.batch_writer import BatchWriter


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_config():
    with patch("app.core.config.Config.load") as mock_load:
        mock_instance = MagicMock()
        mock_instance.service = MagicMock()
        mock_instance.service.name = "Test Service"
        mock_instance.service.host = "127.0.0.1"
        mock_instance.service.port = 8080
        mock_instance.clickhouse = {"host": "localhost", "port": 8123}
        mock_instance.mqtt = {"broker": "localhost", "port": 1883}
        mock_instance.data_validation = {
            "temperature_range": [-10, 50],
            "humidity_range": [0, 100],
            "ph_range": [3, 9],
            "light_range": [0, 1000],
            "voc_range": [0, 2000],
            "mold_spore_range": [0, 100000],
        }
        mock_load.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def sample_env_sensor_data() -> Dict[str, Any]:
    return {
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


@pytest.fixture
def sample_ph_sensor_data() -> Dict[str, Any]:
    return {
        "sensor_id": "ph_001",
        "shelf_id": "shelf_01",
        "slot_id": "slot_001",
        "ph_value": 6.8,
        "timestamp": "2024-01-15T10:30:00",
    }


@pytest.fixture
def sample_sensor_data_msg() -> EnvSensorData:
    return EnvSensorData(
        sensor_id="env_001",
        shelf_id="shelf_01",
        slot_id="slot_001",
        temperature=22.5,
        humidity=55.0,
        light=30.0,
        voc=150.0,
        mold_spore=100.0,
    )


@pytest.fixture
def sample_alert_msg() -> AlertMessage:
    return AlertMessage(
        shelf_id="shelf_01",
        slot_id="slot_001",
        alert_level="yellow",
        alert_type="ph_low",
        alert_value=6.2,
        threshold=6.5,
        message="pH值偏低",
    )


@pytest.fixture
def async_queue():
    queue = AsyncQueueWrapper[SensorData]("test_queue", maxsize=10)
    yield queue


@pytest.fixture
def queue_manager():
    qm = QueueManager()
    yield qm


@pytest.fixture
def mock_clickhouse_client():
    mock_client = MagicMock()
    mock_client.execute = MagicMock(return_value=[])
    yield mock_client


@pytest.fixture
def batch_writer(mock_clickhouse_client):
    writer = BatchWriter(
        client=mock_clickhouse_client,
        batch_size=10,
        flush_interval=1,
        max_queue_size=100,
    )
    writer.register_table(
        "env_sensor_data",
        ["timestamp", "sensor_id", "shelf_id", "slot_id",
         "temperature", "humidity", "light", "voc", "mold_spore", "sensor_type"]
    )
    writer.register_table(
        "ph_sensor_data",
        ["timestamp", "sensor_id", "shelf_id", "slot_id", "ph_value", "sensor_type"]
    )
    writer.register_table(
        "test_table",
        ["col1", "col2", "col3"]
    )
    yield writer


@pytest.fixture
def mock_mqtt_client():
    with patch("paho.mqtt.client.Client") as mock:
        client_instance = MagicMock()
        mock.return_value = client_instance
        client_instance.connect = MagicMock()
        client_instance.subscribe = MagicMock()
        client_instance.loop_start = MagicMock()
        client_instance.loop_stop = MagicMock()
        client_instance.disconnect = MagicMock()
        client_instance.publish = MagicMock()
        yield client_instance


@pytest.fixture
def mock_requests_post():
    with patch("requests.post") as mock:
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0}
        mock.return_value = mock_response
        yield mock


@pytest.fixture
def mock_smtplib():
    with patch("smtplib.SMTP") as mock:
        smtp_instance = MagicMock()
        mock.return_value.__enter__.return_value = smtp_instance
        smtp_instance.starttls = MagicMock()
        smtp_instance.login = MagicMock()
        smtp_instance.sendmail = MagicMock()
        yield smtp_instance
