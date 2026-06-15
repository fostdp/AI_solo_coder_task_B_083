import json
import logging
import threading
import time
from typing import Dict
import paho.mqtt.client as mqtt
from .config import settings
from .database import db_manager
from .alerts import AlertManager
from .config import settings as app_settings

logger = logging.getLogger(__name__)


class MQTTSubscriber:
    """
    MQTT订阅服务
    负责接收传感器数据并写入ClickHouse
    """

    def __init__(self, alert_manager: AlertManager = None):
        self.client = None
        self.connected = False
        self.alert_manager = alert_manager
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._running = False

    def on_connect(self, client, userdata, flags, rc):
        """连接回调"""
        if rc == 0:
            logger.info("MQTT连接成功")
            self.connected = True
            client.subscribe(settings.MQTT_TOPIC_ENV, qos=1)
            client.subscribe(settings.MQTT_TOPIC_PH, qos=1)
            logger.info(f"已订阅主题: {settings.MQTT_TOPIC_ENV}, {settings.MQTT_TOPIC_PH}")
        else:
            logger.error(f"MQTT连接失败，错误码: {rc}")
            self.connected = False

    def on_disconnect(self, client, userdata, rc):
        """断开连接回调"""
        logger.warning(f"MQTT断开连接，错误码: {rc}")
        self.connected = False

    def on_message(self, client, userdata, msg):
        """消息接收回调"""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic

            if topic.startswith("library/env/"):
                self._handle_env_data(payload)
            elif topic.startswith("library/ph/"):
                self._handle_ph_data(payload)
            else:
                logger.debug(f"收到未处理主题的消息: {topic}")

            if time.time() - self._last_flush > settings.BATCH_WRITE_INTERVAL:
                self._flush_buffers()

        except json.JSONDecodeError as e:
            logger.error(f"消息解析失败: {e}")
        except Exception as e:
            logger.error(f"处理消息异常: {e}")

    def _handle_env_data(self, data: Dict):
        """处理环境传感器数据"""
        required_fields = ["sensor_id", "shelf_id", "slot_id",
                           "temperature", "humidity", "light", "voc", "mold_spore"]

        if not all(field in data for field in required_fields):
            logger.warning(f"环境数据缺少必要字段: {data}")
            return

        record = {
            "sensor_id": data["sensor_id"],
            "shelf_id": data["shelf_id"],
            "slot_id": data["slot_id"],
            "temperature": float(data["temperature"]),
            "humidity": float(data["humidity"]),
            "light": float(data["light"]),
            "voc": float(data["voc"]),
            "mold_spore": float(data["mold_spore"]),
            "sensor_type": "environment"
        }

        with self._lock:
            db_manager.add_env_to_buffer(record)

        if self.alert_manager:
            alerts = self.alert_manager.check_and_create_alerts(data)
            for alert in alerts:
                alert_dict = alert.to_dict()
                with self._lock:
                    db_manager.add_alert_to_buffer(alert_dict)
                self.alert_manager.push_alert(alert, settings.ALERT_EMAILS)

    def _handle_ph_data(self, data: Dict):
        """处理pH传感器数据"""
        required_fields = ["sensor_id", "shelf_id", "slot_id", "ph_value"]

        if not all(field in data for field in required_fields):
            logger.warning(f"pH数据缺少必要字段: {data}")
            return

        record = {
            "sensor_id": data["sensor_id"],
            "shelf_id": data["shelf_id"],
            "slot_id": data["slot_id"],
            "ph_value": float(data["ph_value"]),
            "sensor_type": "ph"
        }

        with self._lock:
            db_manager.add_ph_to_buffer(record)

        if self.alert_manager:
            alerts = self.alert_manager.check_and_create_alerts(data)
            for alert in alerts:
                alert_dict = alert.to_dict()
                with self._lock:
                    db_manager.add_alert_to_buffer(alert_dict)
                self.alert_manager.push_alert(alert, settings.ALERT_EMAILS)

    def _flush_buffers(self):
        """刷写所有缓冲区"""
        with self._lock:
            env_count = db_manager.flush_env_buffer()
            ph_count = db_manager.flush_ph_buffer()
            alert_count = db_manager.flush_alert_buffer()
            self._last_flush = time.time()

        if env_count > 0 or ph_count > 0:
            logger.debug(f"刷写缓冲区: 环境数据{env_count}条, pH数据{ph_count}条, 告警{alert_count}条")

    def start(self):
        """启动MQTT订阅"""
        self.client = mqtt.Client(
            client_id="library_monitor_backend",
            clean_session=True
        )

        if settings.MQTT_USERNAME:
            self.client.username_pw_set(
                settings.MQTT_USERNAME,
                settings.MQTT_PASSWORD
            )

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self._running = True
        self._connect_loop()

    def _connect_loop(self):
        """连接循环（带重连机制）"""
        while self._running:
            try:
                logger.info(f"正在连接MQTT broker: {settings.MQTT_BROKER}:{settings.MQTT_PORT}")
                self.client.connect(
                    settings.MQTT_BROKER,
                    settings.MQTT_PORT,
                    keepalive=60
                )
                self.client.loop_forever()
            except Exception as e:
                logger.error(f"MQTT连接异常: {e}")
                if self._running:
                    logger.info("5秒后尝试重连...")
                    time.sleep(5)

    def stop(self):
        """停止MQTT订阅"""
        self._running = False
        if self.client:
            self.client.disconnect()
        self._flush_buffers()
        logger.info("MQTT订阅已停止")

    def start_background(self):
        """在后台线程中启动"""
        thread = threading.Thread(target=self.start, daemon=True)
        thread.start()
        logger.info("MQTT订阅后台线程已启动")
        return thread


mqtt_subscriber = MQTTSubscriber()
