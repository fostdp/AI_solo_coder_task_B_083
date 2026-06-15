"""
数据摄取模块
负责MQTT消息接收、数据清洗、验证
"""
import asyncio
import json
import logging
import threading
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime

import paho.mqtt.client as mqtt

from ..core.config import config
from ..core.messages import EnvSensorData, PhSensorData, SensorData, AlertMessage
from ..core.queue_manager import queue_manager, AsyncQueueWrapper

logger = logging.getLogger(__name__)


class DataValidator:
    """数据验证器 - 验证传感器数据范围（向后兼容版本）"""

    def __init__(self, validation_ranges: Dict[str, Tuple[float, float]] = None):
        validation_config = config.data_validation
        default_ranges = {
            "temperature": tuple(validation_config.get("temperature_range", [-10, 50])),
            "humidity": tuple(validation_config.get("humidity_range", [0, 100])),
            "ph": tuple(validation_config.get("ph_range", [3, 9])),
            "light": tuple(validation_config.get("light_range", [0, 1000])),
            "voc": tuple(validation_config.get("voc_range", [0, 2000])),
            "mold_spore": tuple(validation_config.get("mold_spore_range", [0, 100000])),
        }

        if validation_ranges:
            normalized_ranges = {}
            for key, value in validation_ranges.items():
                normalized_key = "ph" if key == "ph_value" else key
                normalized_ranges[normalized_key] = tuple(value) if isinstance(value, (list, tuple)) else value
            self.validation_ranges = {**default_ranges, **normalized_ranges}
        else:
            self.validation_ranges = default_ranges

        self.temp_range = self.validation_ranges["temperature"]
        self.humidity_range = self.validation_ranges["humidity"]
        self.ph_range = self.validation_ranges["ph"]
        self.light_range = self.validation_ranges["light"]
        self.voc_range = self.validation_ranges["voc"]
        self.mold_range = self.validation_ranges["mold_spore"]

    def validate_temperature(self, value: float) -> Tuple[bool, Optional[str]]:
        """验证温度（兼容API）"""
        try:
            v = float(value)
            if self.validation_ranges["temperature"][0] <= v <= self.validation_ranges["temperature"][1]:
                return True, None
            return False, f"温度超出范围: {v}，应为{self.validation_ranges['temperature']}"
        except (ValueError, TypeError):
            return False, "温度数据无效"

    def validate_humidity(self, value: float) -> Tuple[bool, Optional[str]]:
        """验证湿度（兼容API）"""
        try:
            v = float(value)
            if self.validation_ranges["humidity"][0] <= v <= self.validation_ranges["humidity"][1]:
                return True, None
            return False, f"湿度超出范围: {v}，应为{self.validation_ranges['humidity']}"
        except (ValueError, TypeError):
            return False, "湿度数据无效"

    def validate_ph(self, value: float) -> Tuple[bool, Optional[str]]:
        """验证pH（兼容API）"""
        try:
            v = float(value)
            if self.validation_ranges["ph"][0] <= v <= self.validation_ranges["ph"][1]:
                return True, None
            return False, f"pH值超出范围: {v}，应为{self.validation_ranges['ph']}"
        except (ValueError, TypeError):
            return False, "pH值无效"

    def validate_light(self, value: float) -> Tuple[bool, Optional[str]]:
        """验证光照（兼容API）"""
        try:
            v = float(value)
            if self.validation_ranges["light"][0] <= v <= self.validation_ranges["light"][1]:
                return True, None
            return False, f"光照超出范围: {v}，应为{self.validation_ranges['light']}"
        except (ValueError, TypeError):
            return False, "光照数据无效"

    def validate_voc(self, value: float) -> Tuple[bool, Optional[str]]:
        """验证VOC（兼容API）"""
        try:
            v = float(value)
            if self.validation_ranges["voc"][0] <= v <= self.validation_ranges["voc"][1]:
                return True, None
            return False, f"VOC超出范围: {v}，应为{self.validation_ranges['voc']}"
        except (ValueError, TypeError):
            return False, "VOC数据无效"

    def validate_mold_spore(self, value: float) -> Tuple[bool, Optional[str]]:
        """验证霉菌孢子（兼容API）"""
        try:
            v = float(value)
            if self.validation_ranges["mold_spore"][0] <= v <= self.validation_ranges["mold_spore"][1]:
                return True, None
            return False, f"霉菌孢子超出范围: {v}，应为{self.validation_ranges['mold_spore']}"
        except (ValueError, TypeError):
            return False, "霉菌孢子数据无效"

    def _clamp(self, value: float, min_val: float, max_val: float) -> Tuple[float, bool]:
        """钳位值到范围内，返回(钳位后的值, 是否被修改)"""
        if value < min_val:
            return min_val, True
        if value > max_val:
            return max_val, True
        return value, False

    def validate_env_data(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """验证环境传感器数据"""
        errors = []
        cleaned = {}

        required_fields = ["sensor_id", "shelf_id", "slot_id"]
        for field in required_fields:
            if field not in data:
                errors.append(f"缺少必填字段: {field}")
                cleaned[field] = "unknown"
            else:
                cleaned[field] = str(data[field])

        temp = data.get("temperature", 20.0)
        try:
            temp = float(temp)
            temp, modified = self._clamp(temp, self.temp_range[0], self.temp_range[1])
            if modified:
                errors.append(f"温度超出范围，已钳位: {temp}")
        except (ValueError, TypeError):
            errors.append("温度数据无效，使用默认值20")
            temp = 20.0
        cleaned["temperature"] = temp

        humidity = data.get("humidity", 50.0)
        try:
            humidity = float(humidity)
            humidity, modified = self._clamp(humidity, self.humidity_range[0], self.humidity_range[1])
            if modified:
                errors.append(f"湿度超出范围，已钳位: {humidity}")
        except (ValueError, TypeError):
            errors.append("湿度数据无效，使用默认值50")
            humidity = 50.0
        cleaned["humidity"] = humidity

        light = data.get("light", 0.0)
        try:
            light = float(light)
            light, modified = self._clamp(light, self.light_range[0], self.light_range[1])
            if modified:
                errors.append(f"光照超出范围，已钳位: {light}")
        except (ValueError, TypeError):
            errors.append("光照数据无效，使用默认值0")
            light = 0.0
        cleaned["light"] = light

        voc = data.get("voc", 0.0)
        try:
            voc = float(voc)
            voc, modified = self._clamp(voc, self.voc_range[0], self.voc_range[1])
            if modified:
                errors.append(f"VOC超出范围，已钳位: {voc}")
        except (ValueError, TypeError):
            errors.append("VOC数据无效，使用默认值0")
            voc = 0.0
        cleaned["voc"] = voc

        mold = data.get("mold_spore", 50.0)
        try:
            mold = float(mold)
            mold, modified = self._clamp(mold, self.mold_range[0], self.mold_range[1])
            if modified:
                errors.append(f"霉菌孢子超出范围，已钳位: {mold}")
        except (ValueError, TypeError):
            errors.append("霉菌孢子数据无效，使用默认值50")
            mold = 50.0
        cleaned["mold_spore"] = mold

        cleaned["timestamp"] = data.get("timestamp", datetime.now().isoformat())

        return cleaned, errors

    def validate_ph_data(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """验证pH传感器数据"""
        errors = []
        cleaned = {}

        required_fields = ["sensor_id", "shelf_id", "slot_id"]
        for field in required_fields:
            if field not in data:
                errors.append(f"缺少必填字段: {field}")
                cleaned[field] = "unknown"
            else:
                cleaned[field] = str(data[field])

        ph_value = data.get("ph_value", 7.0)
        try:
            ph_value = float(ph_value)
            ph_value, modified = self._clamp(ph_value, self.ph_range[0], self.ph_range[1])
            if modified:
                errors.append(f"pH值超出范围，已钳位: {ph_value}")
        except (ValueError, TypeError):
            errors.append("pH值无效，使用默认值7")
            ph_value = 7.0
        cleaned["ph_value"] = ph_value

        cleaned["timestamp"] = data.get("timestamp", datetime.now().isoformat())

        return cleaned, errors


class MQTTSubscriber:
    """MQTT订阅器 - 异步化处理MQTT消息"""

    def __init__(self, output_queue: AsyncQueueWrapper, alert_queue: AsyncQueueWrapper):
        mqtt_config = config.mqtt
        self.broker = mqtt_config.get("broker", "localhost")
        self.port = mqtt_config.get("port", 1883)
        self.username = mqtt_config.get("username", "")
        self.password = mqtt_config.get("password", "")
        self.topic_env = mqtt_config.get("topic_env", "library/env/+")
        self.topic_ph = mqtt_config.get("topic_ph", "library/ph/+")
        self.qos = mqtt_config.get("qos", 1)
        self.keepalive = mqtt_config.get("keepalive", 60)
        self.reconnect_interval = mqtt_config.get("reconnect_interval", 5)

        self.output_queue = output_queue
        self.alert_queue = alert_queue
        self.validator = DataValidator()

        self.client: Optional[mqtt.Client] = None
        self._is_connected = False
        self._is_running = False
        self._connect_thread: Optional[threading.Thread] = None
        self._loop = asyncio.get_event_loop()

        self._stats = {
            "total_received": 0,
            "valid_messages": 0,
            "invalid_messages": 0,
            "alert_triggered": 0,
            "last_message_time": None,
        }

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT连接回调"""
        if rc == 0:
            logger.info(f"MQTT连接成功: {self.broker}:{self.port}")
            self._is_connected = True
            client.subscribe(self.topic_env, qos=self.qos)
            client.subscribe(self.topic_ph, qos=self.qos)
            logger.info(f"已订阅主题: {self.topic_env}, {self.topic_ph}")
        else:
            logger.error(f"MQTT连接失败，返回码: {rc}")
            self._is_connected = False

    def _on_disconnect(self, client, userdata, rc):
        """MQTT断开回调"""
        logger.warning(f"MQTT断开连接，返回码: {rc}")
        self._is_connected = False

    def _on_message(self, client, userdata, msg):
        """MQTT消息回调 - 在独立线程中执行，快速返回"""
        try:
            self._stats["total_received"] += 1
            self._stats["last_message_time"] = datetime.now().isoformat()

            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic

            asyncio.run_coroutine_threadsafe(
                self._process_message(topic, payload),
                self._loop
            )

        except json.JSONDecodeError as e:
            self._stats["invalid_messages"] += 1
            logger.error(f"MQTT消息JSON解析失败: {e}")
        except Exception as e:
            self._stats["invalid_messages"] += 1
            logger.error(f"MQTT消息处理异常: {e}")

    async def _process_message(self, topic: str, payload: Dict[str, Any]):
        """异步处理消息 - 实际的业务逻辑"""
        try:
            if topic.startswith("library/env/"):
                await self._handle_env_data(payload)
            elif topic.startswith("library/ph/"):
                await self._handle_ph_data(payload)
            else:
                logger.debug(f"忽略未知主题: {topic}")
        except Exception as e:
            logger.error(f"处理消息失败 {topic}: {e}")

    async def _handle_env_data(self, payload: Dict[str, Any]):
        """处理环境传感器数据"""
        cleaned, errors = self.validator.validate_env_data(payload)

        if errors:
            logger.debug(f"环境数据清洗警告: {errors}")

        sensor_data = EnvSensorData(
            sensor_id=cleaned["sensor_id"],
            shelf_id=cleaned["shelf_id"],
            slot_id=cleaned["slot_id"],
            data=cleaned,
            temperature=cleaned["temperature"],
            humidity=cleaned["humidity"],
            light=cleaned["light"],
            voc=cleaned["voc"],
            mold_spore=cleaned["mold_spore"],
            is_valid=len(errors) == 0,
            validation_errors=errors,
        )

        success = await self.output_queue.put(sensor_data)
        if success:
            self._stats["valid_messages"] += 1
        else:
            self._stats["invalid_messages"] += 1

        thresholds = config.get_alert_thresholds()
        if cleaned["mold_spore"] > thresholds.get("yellow_mold", 500.0):
            await self._trigger_alert(
                shelf_id=cleaned["shelf_id"],
                slot_id=cleaned["slot_id"],
                alert_type="mold_spore_high",
                alert_value=cleaned["mold_spore"],
                threshold=thresholds.get("yellow_mold", 500.0),
                alert_level="yellow",
                message=f"霉菌孢子浓度过高: {cleaned['mold_spore']:.0f} CFU/m³",
            )

        if cleaned["light"] > thresholds.get("orange_light", 50.0):
            await self._trigger_alert(
                shelf_id=cleaned["shelf_id"],
                slot_id=cleaned["slot_id"],
                alert_type="light_high",
                alert_value=cleaned["light"],
                threshold=thresholds.get("orange_light", 50.0),
                alert_level="orange",
                message=f"光照强度过高: {cleaned['light']:.1f} lux",
            )

    async def _handle_ph_data(self, payload: Dict[str, Any]):
        """处理pH传感器数据"""
        cleaned, errors = self.validator.validate_ph_data(payload)

        if errors:
            logger.debug(f"pH数据清洗警告: {errors}")

        sensor_data = PhSensorData(
            sensor_id=cleaned["sensor_id"],
            shelf_id=cleaned["shelf_id"],
            slot_id=cleaned["slot_id"],
            data=cleaned,
            ph_value=cleaned["ph_value"],
            is_valid=len(errors) == 0,
            validation_errors=errors,
        )

        success = await self.output_queue.put(sensor_data)
        if success:
            self._stats["valid_messages"] += 1
        else:
            self._stats["invalid_messages"] += 1

        thresholds = config.get_alert_thresholds()
        ph = cleaned["ph_value"]

        if ph < thresholds.get("red_ph", 5.5):
            level = "red"
        elif ph < thresholds.get("orange_ph", 6.0):
            level = "orange"
        elif ph < thresholds.get("yellow_ph", 6.5):
            level = "yellow"
        else:
            return

        threshold_map = {"yellow": 6.5, "orange": 6.0, "red": 5.5}
        await self._trigger_alert(
            shelf_id=cleaned["shelf_id"],
            slot_id=cleaned["slot_id"],
            alert_type="ph_low",
            alert_value=ph,
            threshold=thresholds.get(f"{level}_ph", threshold_map[level]),
            alert_level=level,
            message=f"纸张pH值过低: {ph:.2f}",
        )

    async def _trigger_alert(self, **kwargs):
        """触发告警"""
        alert = AlertMessage(**kwargs)
        await self.alert_queue.put(alert)
        self._stats["alert_triggered"] += 1

    def start(self):
        """启动MQTT订阅（后台线程）"""
        if self._is_running:
            return

        self._is_running = True
        self._connect_thread = threading.Thread(
            target=self._connect_loop,
            daemon=True,
            name="MQTT-Connect-Thread"
        )
        self._connect_thread.start()
        logger.info("MQTT订阅器已启动")

    def _connect_loop(self):
        """MQTT连接循环 - 在后台线程中运行"""
        while self._is_running:
            try:
                self.client = mqtt.Client(
                    client_id=f"library_monitor_{datetime.now().timestamp():.0f}",
                    protocol=mqtt.MQTTv311
                )
                self.client.on_connect = self._on_connect
                self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message

                if self.username:
                    self.client.username_pw_set(self.username, self.password)

                logger.info(f"正在连接MQTT broker: {self.broker}:{self.port}")
                self.client.connect(self.broker, self.port, keepalive=self.keepalive)
                self.client.loop_forever()

            except Exception as e:
                logger.error(f"MQTT连接异常: {e}")
                self._is_connected = False

            if self._is_running:
                logger.info(f"{self.reconnect_interval}秒后重试MQTT连接...")
                threading.Event().wait(self.reconnect_interval)

    def stop(self):
        """停止MQTT订阅"""
        self._is_running = False
        if self.client:
            try:
                self.client.disconnect()
                self.client.loop_stop()
            except Exception as e:
                logger.error(f"停止MQTT客户端失败: {e}")
        if self._connect_thread:
            self._connect_thread.join(timeout=5)
        logger.info("MQTT订阅器已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return dict(self._stats)

    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected


class IngestService:
    """数据摄取服务 - 组合MQTT订阅和数据清洗"""

    def __init__(self):
        self.sensor_queue = queue_manager.create_async_queue("sensor_data", maxsize=1000)
        self.alert_queue = queue_manager.create_async_queue("ingest_alerts", maxsize=100)
        self.subscriber = MQTTSubscriber(self.sensor_queue, self.alert_queue)

    async def start(self):
        """启动服务"""
        self.subscriber.start()
        logger.info("数据摄取服务已启动")

    async def stop(self):
        """停止服务"""
        self.subscriber.stop()
        await queue_manager.flush_all_async()
        logger.info("数据摄取服务已停止")

    def get_sensor_queue(self) -> AsyncQueueWrapper:
        """获取传感器数据队列"""
        return self.sensor_queue

    def get_alert_queue(self) -> AsyncQueueWrapper:
        """获取告警队列"""
        return self.alert_queue

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "mqtt": self.subscriber.get_stats(),
            "queues": queue_manager.get_all_stats(),
        }


class DataCleaner:
    """数据清洗器 - 数据清洗和转换（向后兼容）"""

    def __init__(self, validator: DataValidator = None):
        self.validator = validator or DataValidator()

    def check_required_fields(self, data: Dict[str, Any], required_fields: List[str]) -> Tuple[bool, List[str]]:
        """检查必填字段"""
        missing = [field for field in required_fields if field not in data]
        return len(missing) == 0, missing

    def clean_env_data(self, data: Dict[str, Any]) -> Tuple[Optional[EnvSensorData], List[str]]:
        """清洗环境传感器数据"""
        required_fields = ["sensor_id", "shelf_id", "slot_id"]
        has_all, missing = self.check_required_fields(data, required_fields)

        if not has_all:
            errors = [f"缺少必要字段: {', '.join(missing)}"]
            return None, errors

        errors = []
        cleaned = {}

        for field in required_fields:
            cleaned[field] = str(data[field])

        numeric_fields = ["temperature", "humidity", "light", "voc", "mold_spore"]
        for field in numeric_fields:
            value = data.get(field, 0)
            try:
                cleaned[field] = float(value)
            except (ValueError, TypeError):
                errors.append(f"{field}数值转换失败: {value}")
                return None, errors

        for field in numeric_fields:
            validator_method = getattr(self.validator, f"validate_{field}")
            valid, err = validator_method(cleaned[field])
            if not valid:
                errors.append(err)
                cleaned[field] = self.validator._clamp(
                    cleaned[field],
                    self.validator.validation_ranges[field][0],
                    self.validator.validation_ranges[field][1],
                )[0]

        timestamp = data.get("timestamp", datetime.now().isoformat())

        sensor_data = EnvSensorData(
            sensor_id=cleaned["sensor_id"],
            shelf_id=cleaned["shelf_id"],
            slot_id=cleaned["slot_id"],
            data=cleaned,
            temperature=cleaned["temperature"],
            humidity=cleaned["humidity"],
            light=cleaned["light"],
            voc=cleaned["voc"],
            mold_spore=cleaned["mold_spore"],
            is_valid=len(errors) == 0,
            validation_errors=errors,
        )
        sensor_data.timestamp = timestamp

        return sensor_data, errors

    def clean_ph_data(self, data: Dict[str, Any]) -> Tuple[Optional[PhSensorData], List[str]]:
        """清洗pH传感器数据"""
        required_fields = ["sensor_id", "shelf_id", "slot_id"]
        has_all, missing = self.check_required_fields(data, required_fields)

        if not has_all:
            errors = [f"缺少必要字段: {', '.join(missing)}"]
            return None, errors

        errors = []
        cleaned = {}

        for field in required_fields:
            cleaned[field] = str(data[field])

        value = data.get("ph_value", 7.0)
        try:
            cleaned["ph_value"] = float(value)
        except (ValueError, TypeError):
            errors.append(f"pH值转换失败: {value}")
            return None, errors

        valid, err = self.validator.validate_ph(cleaned["ph_value"])
        if not valid:
            errors.append(err)
            cleaned["ph_value"] = self.validator._clamp(
                cleaned["ph_value"],
                self.validator.validation_ranges["ph"][0],
                self.validator.validation_ranges["ph"][1],
            )[0]

        timestamp = data.get("timestamp", datetime.now().isoformat())

        sensor_data = PhSensorData(
            sensor_id=cleaned["sensor_id"],
            shelf_id=cleaned["shelf_id"],
            slot_id=cleaned["slot_id"],
            data=cleaned,
            ph_value=cleaned["ph_value"],
            is_valid=len(errors) == 0,
            validation_errors=errors,
        )
        sensor_data.timestamp = timestamp

        return sensor_data, errors


class MQTTDataHandler:
    """MQTT数据处理器 - 向后兼容版本"""

    def __init__(self, cleaner: DataCleaner = None, validator: DataValidator = None):
        self.validator = validator or DataValidator()
        self.cleaner = cleaner or DataCleaner(self.validator)
        self._stats = {
            "total_received": 0,
            "env_messages": 0,
            "ph_messages": 0,
            "valid_messages": 0,
            "invalid_messages": 0,
            "unknown_topics": 0,
            "errors": 0,
        }

    def handle_message(self, topic: str, payload: Dict[str, Any]) -> Optional[SensorData]:
        """处理MQTT消息"""
        self._stats["total_received"] += 1

        try:
            if topic.startswith("library/env/"):
                self._stats["env_messages"] += 1
                return self._handle_env_message(payload)
            elif topic.startswith("library/ph/"):
                self._stats["ph_messages"] += 1
                return self._handle_ph_message(payload)
            else:
                self._stats["unknown_topics"] += 1
                return None
        except Exception as e:
            self._stats["errors"] += 1
            self._stats["invalid_messages"] += 1
            logger.error(f"处理MQTT消息失败: {e}")
            return None

    def _handle_env_message(self, payload: Dict[str, Any]) -> Optional[EnvSensorData]:
        """处理环境传感器消息"""
        result, errors = self.cleaner.clean_env_data(payload)
        if result and result.is_valid:
            self._stats["valid_messages"] += 1
        else:
            self._stats["invalid_messages"] += 1
        return result

    def _handle_ph_message(self, payload: Dict[str, Any]) -> Optional[PhSensorData]:
        """处理pH传感器消息"""
        result, errors = self.cleaner.clean_ph_data(payload)
        if result and result.is_valid:
            self._stats["valid_messages"] += 1
        else:
            self._stats["invalid_messages"] += 1
        return result

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（返回副本）"""
        return dict(self._stats)

    def reset_stats(self):
        """重置统计信息"""
        for key in self._stats:
            self._stats[key] = 0


# 向后兼容别名
_MQTTSubscriberAlias = MQTTSubscriber
