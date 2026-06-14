import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from ..config import settings
from ..database import get_batch_writer
from .alert_manager import alert_manager

try:
    import paho.mqtt.client as mqtt_client
    HAS_PAHO = True
except ImportError:
    HAS_PAHO = False

logger = logging.getLogger(__name__)


class MqttIngestService:
    ENV_COLS = [
        "timestamp", "sensor_id", "shelf_id", "slot_id",
        "temperature", "humidity", "light_lux", "voc_ppm",
        "mold_spores", "active_mold", "rssi",
    ]
    PH_COLS = [
        "timestamp", "sensor_id", "shelf_id", "slot_id",
        "ph_value", "paper_cond", "rssi",
    ]

    def __init__(self):
        self._mqtt: Optional[Any] = None
        self._ph_cache: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._writer = get_batch_writer()
        self._stop = threading.Event()

    def start(self):
        if HAS_PAHO:
            self._mqtt = mqtt_client.Client(
                callback_api_version=getattr(mqtt_client, "CallbackAPIVersion", mqtt_client.MQTTv311),
                client_id=f"abm_ingest_{int(time.time())}",
            )
            self._mqtt.on_connect = self._on_connect
            self._mqtt.on_message = self._on_message
            try:
                self._mqtt.connect(settings.mqtt_broker, settings.mqtt_port, keepalive=60)
                self._mqtt.loop_start()
                logger.info("MQTT client started")
            except Exception as e:
                logger.warning(f"MQTT connect failed (running in mock mode): {e}")
                self._mqtt = None
        else:
            logger.warning("paho-mqtt not installed, MQTT ingestion disabled")
            self._mqtt = None

        self._writer.start()
        logger.info("MQTT ingestion service started with BatchWriter")

    def stop(self):
        self._stop.set()
        if self._mqtt:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass
        self._writer.stop(flush=True)
        logger.info("MQTT ingestion service stopped")

    def _on_connect(self, client, userdata, flags, rc, *args, **kwargs):
        if rc == 0:
            logger.info("MQTT connected, subscribing topics")
            client.subscribe(settings.mqtt_topic_env, qos=1)
            client.subscribe(settings.mqtt_topic_ph, qos=1)
        else:
            logger.error(f"MQTT connect failed: rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic
            if topic.startswith("sensor/env/"):
                self.ingest_env(payload)
            elif topic.startswith("sensor/ph/"):
                self.ingest_ph(payload)
        except Exception as e:
            logger.error(f"MQTT message error: {e}")

    def ingest_env(self, data: Dict[str, Any]) -> bool:
        try:
            ts = data.get("timestamp_ms") or data.get("timestamp") or int(datetime.now(timezone.utc).timestamp() * 1000)
            if isinstance(ts, str):
                ts = int(datetime.fromisoformat(ts).timestamp() * 1000)
            sensor_id = data.get("sensor_id", "")
            shelf_id = data.get("shelf_id", "")
            slot_id = data.get("slot_id", "")
            temperature = float(data.get("temperature", 22.0))
            humidity = float(data.get("humidity", 50.0))
            light_lux = float(data.get("light_lux", 0.0))
            voc_ppm = float(data.get("voc_ppm", 0.0))
            mold_spores = float(data.get("mold_spores", 0.0))
            active_mold = int(data.get("active_mold", 0))
            rssi = int(data.get("rssi", -60))

            row = [
                f"{ts}", f"'{sensor_id}'", f"'{shelf_id}'", f"'{slot_id}'",
                f"{temperature}", f"{humidity}", f"{light_lux}", f"{voc_ppm}",
                f"{mold_spores}", f"{active_mold}", f"{rssi}",
            ]
            self._writer.add("env_sensor_data", self.ENV_COLS, row)

            with self._lock:
                ph_value = self._ph_cache.get(slot_id)
            sensor_ph_id = data.get("sensor_ph_id", f"PH-{int(hash(slot_id) % 20) + 1:03d}")
            alert_manager.evaluate_and_alert(
                shelf_id=shelf_id, slot_id=slot_id,
                sensor_env_id=sensor_id, sensor_ph_id=sensor_ph_id,
                ph_value=ph_value, temperature=temperature, humidity=humidity,
                light_lux=light_lux, voc_ppm=voc_ppm,
                mold_spores=mold_spores, active_mold=active_mold,
            )

            return True
        except Exception as e:
            logger.error(f"Ingest env error: {e}")
            return False

    def ingest_ph(self, data: Dict[str, Any]) -> bool:
        try:
            ts = data.get("timestamp_ms") or data.get("timestamp") or int(datetime.now(timezone.utc).timestamp() * 1000)
            if isinstance(ts, str):
                ts = int(datetime.fromisoformat(ts).timestamp() * 1000)
            sensor_id = data.get("sensor_id", "")
            shelf_id = data.get("shelf_id", "")
            slot_id = data.get("slot_id", "")
            ph_value = float(data.get("ph_value", 7.0))
            if ph_value >= 6.8:
                paper_cond = "GOOD"
            elif ph_value >= 6.2:
                paper_cond = "FAIR"
            else:
                paper_cond = "POOR"
            rssi = int(data.get("rssi", -60))

            row = [
                f"{ts}", f"'{sensor_id}'", f"'{shelf_id}'", f"'{slot_id}'",
                f"{ph_value}", f"'{paper_cond}'", f"{rssi}",
            ]
            self._writer.add("ph_sensor_data", self.PH_COLS, row)

            with self._lock:
                self._ph_cache[slot_id] = ph_value
            return True
        except Exception as e:
            logger.error(f"Ingest ph error: {e}")
            return False

    @property
    def queue_size(self) -> int:
        return self._writer.queue_size()

    @property
    def stats(self) -> Dict[str, Any]:
        return self._writer.stats


mqtt_ingest = MqttIngestService()
