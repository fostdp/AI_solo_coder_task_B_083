#!/usr/bin/env python3
"""
传感器模拟器
模拟环境传感器和pH值检测仪，通过MQTT上报数据
支持老化漂移、极端温湿度注入等功能
"""

import json
import time
import random
import math
import logging
import os
from datetime import datetime
from typing import Dict, List
import argparse

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SensorSimulator:
    """传感器模拟器"""

    PRESCRIPTION_EFFECTS = {
        "yuncao": (0.3, 0.5),
        "huangbo": (0.4, 0.6),
        "yanye": (0.2, 0.4),
        "none": (0.0, 0.0),
    }

    def __init__(self, broker: str = "localhost", port: int = 1883,
                 username: str = "", password: str = "",
                 total_sensors: int = 70, ph_ratio: float = 0.3,
                 interval: int = 300, extreme_mode: bool = False,
                 drift_enabled: bool = True, drift_rate: float = 0.001,
                 prescription: str = "none"):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.total_sensors = total_sensors
        self.ph_sensor_count = max(1, int(total_sensors * ph_ratio))
        self.env_sensor_count = total_sensors - self.ph_sensor_count
        self.interval = interval
        self.extreme_mode = extreme_mode
        self.drift_enabled = drift_enabled
        self.drift_rate = drift_rate
        self.active_prescription = prescription

        self.client = None
        self.connected = False
        self.start_time = time.time()

        self.shelves = self._generate_shelves()
        self.env_sensors = self._generate_env_sensors()
        self.ph_sensors = self._generate_ph_sensors()

        self._init_sensor_states()

    def _generate_shelves(self) -> List[Dict]:
        """生成书架和格口配置"""
        shelves = []
        total_slots_needed = self.total_sensors

        shelf_rows = 5
        shelf_cols = 4
        slots_per_shelf = 12

        num_shelves = max(10, math.ceil(total_slots_needed / slots_per_shelf))
        actual_shelf_cols = max(2, math.ceil(num_shelves / shelf_rows))

        for s in range(num_shelves):
            row = s // actual_shelf_cols + 1
            col = s % actual_shelf_cols + 1
            shelf_id = f"SHELF-{row:02d}-{col:02d}"
            slots = []
            for slot_idx in range(slots_per_shelf):
                col_letter = chr(ord('A') + slot_idx // 6)
                slot_num = (slot_idx % 6) + 1
                slot_id = f"SLOT-{col_letter}{slot_num}"
                slots.append({"slot_id": slot_id, "row": slot_idx // 6, "col": slot_idx % 6})
            shelves.append({
                "shelf_id": shelf_id,
                "position_row": row,
                "position_col": col,
                "slots": slots
            })

        return shelves

    def _generate_env_sensors(self) -> List[Dict]:
        """生成环境传感器配置"""
        sensors = []
        all_slots = []

        for shelf in self.shelves:
            for slot in shelf["slots"]:
                all_slots.append({
                    "shelf_id": shelf["shelf_id"],
                    "slot_id": slot["slot_id"],
                    "pos_row": shelf["position_row"],
                    "pos_col": shelf["position_col"],
                    "slot_row": slot["row"],
                    "slot_col": slot["col"]
                })

        selected_slots = random.sample(all_slots, min(self.env_sensor_count, len(all_slots)))

        for i, slot_info in enumerate(selected_slots):
            sensors.append({
                "sensor_id": f"ENV-{i + 1:04d}",
                "shelf_id": slot_info["shelf_id"],
                "slot_id": slot_info["slot_id"],
                "type": "environment",
                "pos_row": slot_info["pos_row"],
                "pos_col": slot_info["pos_col"],
                "slot_row": slot_info["slot_row"],
                "slot_col": slot_info["slot_col"],
                "drift_offset": random.uniform(-0.5, 0.5),
                "drift_direction": random.choice([-1, 1])
            })

        return sensors

    def _generate_ph_sensors(self) -> List[Dict]:
        """生成pH传感器配置"""
        sensors = []
        all_slots = []

        for shelf in self.shelves:
            for slot in shelf["slots"]:
                all_slots.append({
                    "shelf_id": shelf["shelf_id"],
                    "slot_id": slot["slot_id"],
                    "pos_row": shelf["position_row"],
                    "pos_col": shelf["position_col"]
                })

        selected_slots = random.sample(all_slots, min(self.ph_sensor_count, len(all_slots)))

        for i, slot_info in enumerate(selected_slots):
            sensors.append({
                "sensor_id": f"PH-{i + 1:04d}",
                "shelf_id": slot_info["shelf_id"],
                "slot_id": slot_info["slot_id"],
                "type": "ph",
                "pos_row": slot_info["pos_row"],
                "pos_col": slot_info["pos_col"],
                "drift_rate": random.uniform(0.0005, 0.002),
                "drift_offset": random.uniform(-0.1, 0.1)
            })

        return sensors

    def _init_sensor_states(self):
        """初始化传感器状态（基线值）"""
        self.env_states = {}
        self.ph_states = {}

        for sensor in self.env_sensors:
            pos_factor = (sensor["pos_row"] - 3) * 0.8
            slot_factor = (sensor["slot_row"] - 1) * 0.4

            base_temp = 20 + pos_factor + slot_factor + random.uniform(-1, 1)
            base_humid = 50 + pos_factor * 2 + random.uniform(-5, 5)

            if self.extreme_mode:
                if random.random() < 0.3:
                    base_temp = 35 + random.uniform(0, 10)
                if random.random() < 0.3:
                    base_humid = 75 + random.uniform(0, 15)

            self.env_states[sensor["sensor_id"]] = {
                "base_temp": base_temp,
                "base_humid": base_humid,
                "base_light": 20 + (2 - sensor["slot_row"]) * 15 + random.uniform(0, 10),
                "base_voc": 150 + random.uniform(-30, 30),
                "base_mold": 30 + random.uniform(-10, 20),
                "phase": random.uniform(0, 2 * math.pi),
                "temp_drift": 0.0,
                "humid_drift": 0.0,
            }

        for sensor in self.ph_sensors:
            base_ph = 6.8 + random.uniform(-0.8, 0.3)
            if self.extreme_mode and random.random() < 0.2:
                base_ph = 5.5 + random.uniform(-0.5, 0.5)

            self.ph_states[sensor["sensor_id"]] = {
                "base_ph": base_ph,
                "decay_rate": sensor["drift_rate"] if self.drift_enabled else random.uniform(0.002, 0.01),
                "last_ph": base_ph,
                "total_drift": 0.0
            }

    def on_connect(self, client, userdata, flags, rc):
        """连接回调"""
        if rc == 0:
            logger.info("MQTT连接成功")
            self.connected = True
        else:
            logger.error(f"MQTT连接失败，错误码: {rc}")
            self.connected = False

    def on_disconnect(self, client, userdata, rc):
        """断开连接回调"""
        logger.warning(f"MQTT断开连接，错误码: {rc}")
        self.connected = False

    def connect(self):
        """连接MQTT"""
        if mqtt is None:
            logger.warning("paho-mqtt未安装，将仅输出数据到控制台")
            return True

        self.client = mqtt.Client(
            client_id=f"sensor_simulator_{os.getpid()}",
            clean_session=True
        )

        if self.username:
            self.client.username_pw_set(self.username, self.password)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"连接MQTT失败: {e}")
            return False

    def _apply_drift(self, sensor: Dict, state: Dict, elapsed_hours: float):
        """应用老化漂移"""
        if not self.drift_enabled:
            return

        drift_amount = self.drift_rate * elapsed_hours * sensor["drift_direction"] * sensor["drift_offset"]

        state["temp_drift"] = drift_amount * 0.1
        state["humid_drift"] = drift_amount * 0.5
        state["base_mold"] = 30 + elapsed_hours * 0.01 * sensor["drift_offset"]

    def _apply_prescription_effect(self, spore_value: float, prescription: str = None) -> float:
        """
        应用处方药效，降低霉菌孢子浓度
        
        Args:
            spore_value: 原始孢子浓度
            prescription: 处方名称，默认使用self.active_prescription
        
        Returns:
            降低后的孢子浓度
        """
        if prescription is None:
            prescription = self.active_prescription

        if prescription == "none" or prescription not in self.PRESCRIPTION_EFFECTS:
            return spore_value

        min_reduction, max_reduction = self.PRESCRIPTION_EFFECTS[prescription]
        reduction_ratio = random.uniform(min_reduction, max_reduction)

        return spore_value * (1.0 - reduction_ratio)

    def _calculate_env_values(self, sensor: Dict, timestamp: float) -> Dict:
        """计算环境传感器当前值"""
        state = self.env_states[sensor["sensor_id"]]

        elapsed_hours = (timestamp - self.start_time) / 3600
        self._apply_drift(sensor, state, elapsed_hours)

        hour = (timestamp % 86400) / 3600
        day_factor = math.sin(hour * math.pi / 12 - math.pi / 3) * 0.8

        temp_variation = math.sin(timestamp / 7200 + state["phase"]) * 0.5
        humid_variation = math.sin(timestamp / 10800 + state["phase"] + 1) * 3

        noise_temp = random.gauss(0, 0.1)
        noise_humid = random.gauss(0, 0.5)
        noise_light = random.gauss(0, 2)
        noise_voc = random.gauss(0, 5)
        noise_mold = random.gauss(0, 2)

        temperature = state["base_temp"] + state["temp_drift"] + day_factor + temp_variation + noise_temp
        humidity = state["base_humid"] + state["humid_drift"] + day_factor * -1.5 + humid_variation + noise_humid
        light = max(0, state["base_light"] * (1 + day_factor * 0.5) + noise_light)
        voc = max(50, state["base_voc"] + day_factor * 10 + noise_voc)
        mold_spore = max(5, state["base_mold"] + humid_variation * 0.5 + noise_mold)

        if self.extreme_mode:
            cycle_pos = (timestamp % 3600) / 3600
            if 0.2 < cycle_pos < 0.4:
                temperature += random.uniform(5, 15)
                humidity += random.uniform(10, 25)
                mold_spore *= random.uniform(2, 5)
            if 0.6 < cycle_pos < 0.7:
                temperature -= random.uniform(5, 10)
                humidity -= random.uniform(10, 20)

        if self.active_prescription and self.active_prescription != "none":
            if self.active_prescription == "all":
                shelf_id = sensor["shelf_id"]
                shelf_num = int(shelf_id.split("-")[1])
                if shelf_num in (1, 2):
                    effective_prescription = "none"
                elif shelf_num in (3, 4):
                    effective_prescription = "yuncao"
                elif shelf_num in (5, 6):
                    effective_prescription = "huangbo"
                elif shelf_num in (7, 8):
                    effective_prescription = "yanye"
                else:
                    effective_prescription = "none"
                mold_spore = self._apply_prescription_effect(mold_spore, effective_prescription)
            else:
                mold_spore = self._apply_prescription_effect(mold_spore)
            mold_spore = max(1.0, mold_spore)

        return {
            "temperature": round(temperature, 2),
            "humidity": round(humidity, 1),
            "light": round(light, 1),
            "voc": round(voc, 1),
            "mold_spore": round(mold_spore, 1)
        }

    def _calculate_ph_value(self, sensor: Dict, timestamp: float) -> Dict:
        """计算pH传感器当前值"""
        state = self.ph_states[sensor["sensor_id"]]

        time_hours = (timestamp - self.start_time) / 3600

        if self.drift_enabled:
            drift = state["decay_rate"] * time_hours + sensor["drift_offset"] * math.sin(time_hours * 0.01)
        else:
            drift = state["decay_rate"] * time_hours / (365 * 24)

        noise = random.gauss(0, 0.02)

        ph_value = state["base_ph"] - drift + noise
        ph_value = max(3.5, min(8.5, ph_value))

        state["total_drift"] = drift
        state["last_ph"] = ph_value

        return {"ph_value": round(ph_value, 3)}

    def publish_env_data(self, sensor: Dict, values: Dict, timestamp_str: str):
        """发布环境传感器数据"""
        payload = {
            "sensor_id": sensor["sensor_id"],
            "shelf_id": sensor["shelf_id"],
            "slot_id": sensor["slot_id"],
            "sensor_type": "environment",
            "temperature": values["temperature"],
            "humidity": values["humidity"],
            "light": values["light"],
            "voc": values["voc"],
            "mold_spore": values["mold_spore"],
            "timestamp": timestamp_str
        }

        topic = f"library/env/{sensor['sensor_id']}"

        if self.client and self.connected:
            self.client.publish(topic, json.dumps(payload), qos=1)
        else:
            logger.debug(f"[{sensor['sensor_id']}] T:{values['temperature']}°C H:{values['humidity']}%")

    def publish_ph_data(self, sensor: Dict, value: Dict, timestamp_str: str):
        """发布pH传感器数据"""
        payload = {
            "sensor_id": sensor["sensor_id"],
            "shelf_id": sensor["shelf_id"],
            "slot_id": sensor["slot_id"],
            "sensor_type": "ph",
            "ph_value": value["ph_value"],
            "timestamp": timestamp_str
        }

        topic = f"library/ph/{sensor['sensor_id']}"

        if self.client and self.connected:
            self.client.publish(topic, json.dumps(payload), qos=1)
        else:
            logger.debug(f"[{sensor['sensor_id']}] pH:{value['ph_value']}")

    def run_once(self):
        """运行一轮数据采集"""
        timestamp = time.time()
        timestamp_str = datetime.now().isoformat()

        logger.info(f"开始发布传感器数据，时间: {timestamp_str}")

        for sensor in self.env_sensors:
            values = self._calculate_env_values(sensor, timestamp)
            self.publish_env_data(sensor, values, timestamp_str)

        for sensor in self.ph_sensors:
            value = self._calculate_ph_value(sensor, timestamp)
            self.publish_ph_data(sensor, value, timestamp_str)

        logger.info(f"数据发布完成: 环境传感器{len(self.env_sensors)}台, pH传感器{len(self.ph_sensors)}台")

        if self.drift_enabled and random.random() < 0.1:
            avg_drift = sum(s["total_drift"] for s in self.ph_states.values()) / len(self.ph_states)
            logger.info(f"当前平均pH漂移: {avg_drift:.4f}")

    def run(self):
        """持续运行"""
        logger.info(f"传感器模拟器启动")
        logger.info(f"总传感器数: {self.total_sensors}")
        logger.info(f"  环境传感器: {len(self.env_sensors)}台")
        logger.info(f"  pH传感器: {len(self.ph_sensors)}台")
        logger.info(f"上报间隔: {self.interval}秒")
        logger.info(f"极端模式: {'开启' if self.extreme_mode else '关闭'}")
        logger.info(f"老化漂移: {'开启' if self.drift_enabled else '关闭'} (速率: {self.drift_rate})")
        logger.info(f"处方药效: {self.active_prescription if self.active_prescription != 'none' else '关闭'}")
        logger.info(f"MQTT Broker: {self.broker}:{self.port}")

        if not self.connect():
            logger.warning("将以控制台输出模式运行")

        try:
            while True:
                self.run_once()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            logger.info("用户中断，正在停止...")
        finally:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
            logger.info("传感器模拟器已停止")

    def generate_history(self, days: int = 30, output_file: str = None):
        """生成历史数据"""
        logger.info(f"生成{days}天的历史数据...")

        all_env_data = []
        all_ph_data = []

        start_time = time.time() - days * 86400
        interval = 300
        total_steps = int(days * 86400 / interval)

        logger.info(f"总数据点数: 环境{total_steps * len(self.env_sensors)}, pH{total_steps * len(self.ph_sensors)}")

        original_start = self.start_time
        self.start_time = start_time

        try:
            for step in range(total_steps):
                timestamp = start_time + step * interval
                timestamp_str = datetime.fromtimestamp(timestamp).isoformat()

                for sensor in self.env_sensors:
                    values = self._calculate_env_values(sensor, timestamp)
                    record = {
                        "sensor_id": sensor["sensor_id"],
                        "shelf_id": sensor["shelf_id"],
                        "slot_id": sensor["slot_id"],
                        "timestamp": timestamp_str,
                        "temperature": values["temperature"],
                        "humidity": values["humidity"],
                        "light": values["light"],
                        "voc": values["voc"],
                        "mold_spore": values["mold_spore"],
                        "sensor_type": "environment"
                    }
                    all_env_data.append(record)

                if step % 12 == 0:
                    for sensor in self.ph_sensors:
                        value = self._calculate_ph_value(sensor, timestamp)
                        record = {
                            "sensor_id": sensor["sensor_id"],
                            "shelf_id": sensor["shelf_id"],
                            "slot_id": sensor["slot_id"],
                            "timestamp": timestamp_str,
                            "ph_value": value["ph_value"],
                            "sensor_type": "ph"
                        }
                        all_ph_data.append(record)

                if step % 100 == 0:
                    progress = (step / total_steps) * 100
                    logger.info(f"生成进度: {progress:.1f}%")
        finally:
            self.start_time = original_start

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump({
                    "env_data": all_env_data,
                    "ph_data": all_ph_data,
                    "metadata": {
                        "days": days,
                        "interval": interval,
                        "env_sensors": len(self.env_sensors),
                        "ph_sensors": len(self.ph_sensors),
                        "extreme_mode": self.extreme_mode,
                        "drift_enabled": self.drift_enabled
                    }
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"历史数据已保存到: {output_file}")

        return {
            "env_data": all_env_data,
            "ph_data": all_ph_data
        }

    def print_summary(self):
        """打印传感器配置摘要"""
        print("\n" + "=" * 60)
        print("传感器模拟器配置")
        print("=" * 60)
        print(f"总传感器数: {self.total_sensors}")
        print(f"  环境传感器: {len(self.env_sensors)}台")
        print(f"  pH传感器: {len(self.ph_sensors)}台")
        print(f"上报间隔: {self.interval}秒")
        print(f"极端模式: {'开启' if self.extreme_mode else '关闭'}")
        print(f"老化漂移: {'开启' if self.drift_enabled else '关闭'}")
        if self.drift_enabled:
            print(f"漂移速率: {self.drift_rate}")
        print(f"处方药效: {self.active_prescription if self.active_prescription != 'none' else '关闭'}")
        if self.active_prescription != "none" and self.active_prescription in self.PRESCRIPTION_EFFECTS:
            min_r, max_r = self.PRESCRIPTION_EFFECTS[self.active_prescription]
            print(f"  减少率范围: {min_r:.0%}-{max_r:.0%}")
        print(f"MQTT Broker: {self.broker}:{self.port}")
        print(f"\n书架数量: {len(self.shelves)}")
        print(f"总格口数: {sum(len(s['slots']) for s in self.shelves)}")
        print("\n环境传感器分布示例:")
        for sensor in self.env_sensors[:5]:
            print(f"  {sensor['sensor_id']} -> {sensor['shelf_id']}/{sensor['slot_id']}")
        if len(self.env_sensors) > 5:
            print(f"  ... 共{len(self.env_sensors)}台")
        print("\npH传感器分布示例:")
        for sensor in self.ph_sensors[:5]:
            print(f"  {sensor['sensor_id']} -> {sensor['shelf_id']}/{sensor['slot_id']}")
        if len(self.ph_sensors) > 5:
            print(f"  ... 共{len(self.ph_sensors)}台")
        print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="传感器模拟器")
    parser.add_argument("--broker", default=os.getenv("MQTT_BROKER", "localhost"),
                        help="MQTT Broker地址 (默认: localhost)")
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")),
                        help="MQTT端口 (默认: 1883)")
    parser.add_argument("--username", default=os.getenv("MQTT_USERNAME", ""),
                        help="MQTT用户名")
    parser.add_argument("--password", default=os.getenv("MQTT_PASSWORD", ""),
                        help="MQTT密码")
    parser.add_argument("--sensors", type=int, default=int(os.getenv("SENSOR_COUNT", "70")),
                        help="总传感器数量 (默认: 70)")
    parser.add_argument("--ph-ratio", type=float, default=0.3,
                        help="pH传感器占比 (默认: 0.3)")
    parser.add_argument("--interval", type=int, default=int(os.getenv("REPORT_INTERVAL", "300")),
                        help="上报间隔(秒) (默认: 300)")
    parser.add_argument("--extreme", action="store_true",
                        default=os.getenv("EXTREME_MODE", "false").lower() == "true",
                        help="启用极端温湿度模式")
    parser.add_argument("--no-drift", action="store_true",
                        help="禁用老化漂移")
    parser.add_argument("--drift-rate", type=float,
                        default=float(os.getenv("DRIFT_RATE", "0.001")),
                        help="漂移速率 (默认: 0.001)")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--history", type=int, default=0, help="生成历史数据天数")
    parser.add_argument("--output", default="", help="历史数据输出文件")
    parser.add_argument("--summary", action="store_true", help="显示配置摘要")
    parser.add_argument("--prescription",
                        choices=["none", "yuncao", "huangbo", "yanye", "all"],
                        default="none",
                        help="启用处方药效模拟 (none/yuncao/huangbo/yanye/all)")

    args = parser.parse_args()

    simulator = SensorSimulator(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=args.password,
        total_sensors=args.sensors,
        ph_ratio=args.ph_ratio,
        interval=args.interval,
        extreme_mode=args.extreme,
        drift_enabled=not args.no_drift,
        drift_rate=args.drift_rate,
        prescription=args.prescription
    )

    if args.summary:
        simulator.print_summary()
        return

    if args.history > 0:
        simulator.generate_history(days=args.history, output_file=args.output or None)
        return

    if args.once:
        simulator.run_once()
    else:
        simulator.run()


if __name__ == "__main__":
    main()
