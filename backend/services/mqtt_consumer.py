"""
MQTT 订阅消费者
- 订阅传感器数据 Topic (环境: ancient_med/sensor/env/+ , pH: ancient_med/sensor/ph/+)
- 批量写入 ClickHouse
- 触发实时告警检测
"""
import json
import time
import uuid
import logging
import threading
from datetime import datetime, timezone
from typing import List, Dict, Any
from queue import Queue, Empty

import paho.mqtt.client as mqtt

from ..config import settings
from ..database import get_ch
from .alert_service import AlertEngine

logger = logging.getLogger(__name__)


class MqttConsumer:

    def __init__(self):
        self.client = mqtt.Client(
            client_id=f"{settings.mqtt_client_id}_{int(time.time())}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        self.env_queue: Queue = Queue(maxsize=5000)
        self.ph_queue: Queue = Queue(maxsize=2000)
        self.ch = get_ch()
        self.alert_engine = AlertEngine()

        self._stop_event = threading.Event()
        self._batch_thread: threading.Thread = None

        self._batch_size = settings.mqtt_batch_size
        self._batch_interval = settings.mqtt_batch_interval

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT connected, subscribing topics...")
            client.subscribe(settings.mqtt_topic_env, qos=1)
            client.subscribe(settings.mqtt_topic_ph, qos=1)
            logger.info(f"Subscribed: {settings.mqtt_topic_env}, {settings.mqtt_topic_ph}")
        else:
            logger.error(f"MQTT connect failed, rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"MQTT disconnected, rc={rc}. Reconnecting...")
        while not self._stop_event.is_set():
            try:
                client.reconnect()
                break
            except Exception as e:
                logger.error(f"MQTT reconnect failed: {e}, retry in 5s")
                time.sleep(5)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if "sensor/env/" in msg.topic:
                self.env_queue.put(payload)
                self.alert_engine.check_env_alert(payload)
            elif "sensor/ph/" in msg.topic:
                self.ph_queue.put(payload)
                self.alert_engine.check_ph_alert(payload)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}, topic={msg.topic}")
        except Exception as e:
            logger.error(f"Message processing error: {e}")

    def _batch_writer_loop(self):
        logger.info("Batch writer thread started")
        while not self._stop_event.is_set():
            try:
                env_batch = self._drain_queue(self.env_queue, self._batch_size)
                if env_batch:
                    self._flush_env_batch(env_batch)
                ph_batch = self._drain_queue(self.ph_queue, self._batch_size)
                if ph_batch:
                    self._flush_ph_batch(ph_batch)
            except Exception as e:
                logger.error(f"Batch writer error: {e}")
            time.sleep(self._batch_interval)
        logger.info("Batch writer thread stopped")

    def _drain_queue(self, queue: Queue, limit: int) -> List[Dict]:
        items = []
        try:
            while len(items) < limit:
                item = queue.get_nowait()
                items.append(item)
        except Empty:
            pass
        return items

    def _flush_env_batch(self, batch: List[Dict]):
        try:
            columns = [
                "timestamp", "sensor_id", "shelf_id", "slot_id",
                "temperature", "humidity", "light_lux", "voc_ppm",
                "mold_spores", "active_mold", "rssi",
            ]
            rows = []
            for d in batch:
                ts = d.get("timestamp", datetime.now(timezone.utc).timestamp() * 1000)
                if isinstance(ts, (int, float)) and ts < 1e12:
                    ts *= 1000
                rows.append({
                    "timestamp": ts,
                    "sensor_id": str(d.get("sensor_id", "")),
                    "shelf_id": str(d.get("shelf_id", "")),
                    "slot_id": str(d.get("slot_id", "")),
                    "temperature": float(d.get("temperature", 0.0)),
                    "humidity": float(d.get("humidity", 0.0)),
                    "light_lux": float(d.get("light_lux", 0.0)),
                    "voc_ppm": float(d.get("voc_ppm", 0.0)),
                    "mold_spores": float(d.get("mold_spores", 0.0)),
                    "active_mold": int(d.get("active_mold", 0)),
                    "rssi": int(d.get("rssi", -60)),
                })
            self.ch.insert("env_sensor_data", rows, columns)
            logger.debug(f"Env batch flushed: {len(rows)} rows")
        except Exception as e:
            logger.error(f"Flush env batch failed: {e}")

    def _flush_ph_batch(self, batch: List[Dict]):
        try:
            columns = [
                "timestamp", "sensor_id", "shelf_id", "slot_id",
                "ph_value", "paper_cond", "rssi",
            ]
            rows = []
            for d in batch:
                ts = d.get("timestamp", datetime.now(timezone.utc).timestamp() * 1000)
                if isinstance(ts, (int, float)) and ts < 1e12:
                    ts *= 1000
                ph = float(d.get("ph_value", 7.0))
                rows.append({
                    "timestamp": ts,
                    "sensor_id": str(d.get("sensor_id", "")),
                    "shelf_id": str(d.get("shelf_id", "")),
                    "slot_id": str(d.get("slot_id", "")),
                    "ph_value": ph,
                    "paper_cond": str(d.get("paper_cond", self._classify_paper(ph))),
                    "rssi": int(d.get("rssi", -60)),
                })
            self.ch.insert("ph_sensor_data", rows, columns)
            logger.debug(f"pH batch flushed: {len(rows)} rows")
        except Exception as e:
            logger.error(f"Flush pH batch failed: {e}")

    @staticmethod
    def _classify_paper(ph: float) -> str:
        if ph >= 6.8:
            return "GOOD"
        elif ph >= 6.2:
            return "FAIR"
        elif ph >= 5.5:
            return "POOR"
        elif ph >= 5.0:
            return "VERY_POOR"
        else:
            return "CRITICAL"

    def start(self):
        logger.info("Starting MQTT consumer...")
        try:
            self.client.connect(
                settings.mqtt_broker,
                settings.mqtt_port,
                keepalive=60,
            )
        except Exception as e:
            logger.error(f"MQTT initial connect failed: {e}")
        self.client.loop_start()
        self._batch_thread = threading.Thread(
            target=self._batch_writer_loop, daemon=True, name="mqtt-batch-writer"
        )
        self._batch_thread.start()
        logger.info("MQTT consumer started")

    def stop(self):
        logger.info("Stopping MQTT consumer...")
        self._stop_event.set()
        self.client.loop_stop()
        self.client.disconnect()
        if self._batch_thread and self._batch_thread.is_alive():
            self._batch_thread.join(timeout=10)
        remaining_env = self._drain_queue(self.env_queue, 99999)
        remaining_ph = self._drain_queue(self.ph_queue, 99999)
        if remaining_env:
            self._flush_env_batch(remaining_env)
        if remaining_ph:
            self._flush_ph_batch(remaining_ph)
        logger.info("MQTT consumer stopped")


mqtt_consumer = MqttConsumer()
