#!/usr/bin/env python3
"""
传感器模拟器
模拟50台环境传感器和20台pH值检测仪，每5分钟通过MQTT上报数据
"""

import json
import time
import random
import math
import logging
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

    def __init__(self, broker: str = "localhost", port: int = 1883,
                 username: str = "", password: str = "",
                 env_sensor_count: int = 50, ph_sensor_count: int = 20,
                 interval: int = 300):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.env_sensor_count = env_sensor_count
        self.ph_sensor_count = ph_sensor_count
        self.interval = interval

        self.client = None
        self.connected = False

        self.shelves = self._generate_shelves()
        self.env_sensors = self._generate_env_sensors()
        self.ph_sensors = self._generate_ph_sensors()

        self._init_sensor_states()

    def _generate_shelves(self) -> List[Dict]:
        """生成书架和格口配置"""
        shelves = []
        shelf_rows = 5
        shelf_cols = 2
        slots_per_shelf = 12

        for row in range(1, shelf_rows + 1):
            for col in range(1, shelf_cols + 1):
                shelf_id = f"SHELF-{row:02d}"
                slots = []
                for s in range(slots_per_shelf):
                    col_letter = chr(ord('A') + s // 6)
                    slot_num = (s % 6) + 1
                    slot_id = f"SLOT-{col_letter}{slot_num}"
                    slots.append({"slot_id": slot_id, "row": s // 6, "col": s % 6})
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
                "sensor_id": f"ENV-{i + 1:03d}",
                "shelf_id": slot_info["shelf_id"],
                "slot_id": slot_info["slot_id"],
                "type": "environment",
                "pos_row": slot_info["pos_row"],
                "pos_col": slot_info["pos_col"],
                "slot_row": slot_info["slot_row"],
                "slot_col": slot_info["slot_col"]
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
                    "slot_id": slot["slot_id"]
                })

        selected_slots = random.sample(all_slots, min(self.ph_sensor_count, len(all_slots)))

        for i, slot_info in enumerate(selected_slots):
            sensors.append({
                "sensor_id": f"PH-{i + 1:03d}",
                "shelf_id": slot_info["shelf_id"],
                "slot_id": slot_info["slot_id"],
                "type": "ph"
            })

        return sensors

    def _init_sensor_states(self):
        """初始化传感器状态（基线值）"""
        self.env_states = {}
        self.ph_states = {}

        for sensor in self.env_sensors:
            pos_factor = (sensor["pos_row"] - 3) * 0.5
            slot_factor = (sensor["slot_row"] - 1) * 0.3

            self.env_states[sensor["sensor_id"]] = {
                "base_temp": 20 + pos_factor + slot_factor + random.uniform(-1, 1),
                "base_humid": 50 + pos_factor * 2 + random.uniform(-5, 5),
                "base_light": 20 + (2 - sensor["slot_row"]) * 15 + random.uniform(0, 10),
                "base_voc": 150 + random.uniform(-30, 30),
                "base_mold": 30 + random.uniform(-10, 20),
                "phase": random.uniform(0, 2 * math.pi)
            }

        for sensor in self.ph_sensors:
            self.ph_states[sensor["sensor_id"]] = {
                "base_ph": 6.8 + random.uniform(-0.8, 0.3),
                "decay_rate": random.uniform(0.002, 0.01),
                "last_ph": 6.8 + random.uniform(-0.8, 0.3)
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
            client_id="sensor_simulator",
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

    def _calculate_env_values(self, sensor: Dict, timestamp: float) -> Dict:
        """计算环境传感器当前值"""
        state = self.env_states[sensor["sensor_id"]]

        hour = (timestamp % 86400) / 3600
        day_factor = math.sin(hour * math.pi / 12 - math.pi / 3) * 0.8

        temp_variation = math.sin(timestamp / 7200 + state["phase"]) * 0.5
        humid_variation = math.sin(timestamp / 10800 + state["phase"] + 1) * 3

        noise_temp = random.gauss(0, 0.1)
        noise_humid = random.gauss(0, 0.5)
        noise_light = random.gauss(0, 2)
        noise_voc = random.gauss(0, 5)
        noise_mold = random.gauss(0, 2)

        temperature = state["base_temp"] + day_factor + temp_variation + noise_temp
        humidity = state["base_humid"] + day_factor * -1.5 + humid_variation + noise_humid
        light = max(0, state["base_light"] * (1 + day_factor * 0.5) + noise_light)
        voc = max(50, state["base_voc"] + day_factor * 10 + noise_voc)
        mold_spore = max(5, state["base_mold"] + humid_variation * 0.5 + noise_mold)

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

        time_hours = timestamp / 3600
        decay = state["decay_rate"] * time_hours / (365 * 24)

        noise = random.gauss(0, 0.02)

        ph_value = state["base_ph"] - decay + noise
        ph_value = max(4.0, min(8.0, ph_value))

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

    def run(self):
        """持续运行"""
        logger.info(f"传感器模拟器启动")
        logger.info(f"环境传感器: {len(self.env_sensors)}台")
        logger.info(f"pH传感器: {len(self.ph_sensors)}台")
        logger.info(f"上报间隔: {self.interval}秒")
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

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump({
                    "env_data": all_env_data,
                    "ph_data": all_ph_data,
                    "metadata": {
                        "days": days,
                        "interval": interval,
                        "env_sensors": len(self.env_sensors),
                        "ph_sensors": len(self.ph_sensors)
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
        print(f"书架数量: {len(self.shelves)}")
        print(f"环境传感器: {len(self.env_sensors)}台")
        print(f"pH传感器: {len(self.ph_sensors)}台")
        print(f"上报间隔: {self.interval}秒")
        print(f"MQTT Broker: {self.broker}:{self.port}")
        print("\n书架列表:")
        for shelf in self.shelves:
            print(f"  {shelf['shelf_id']} - {len(shelf['slots'])}个格口")
        print("\n环境传感器分布:")
        for sensor in self.env_sensors[:5]:
            print(f"  {sensor['sensor_id']} -> {sensor['shelf_id']}/{sensor['slot_id']}")
        if len(self.env_sensors) > 5:
            print(f"  ... 共{len(self.env_sensors)}台")
        print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="传感器模拟器")
    parser.add_argument("--broker", default="localhost", help="MQTT Broker地址")
    parser.add_argument("--port", type=int, default=1883, help="MQTT端口")
    parser.add_argument("--username", default="", help="MQTT用户名")
    parser.add_argument("--password", default="", help="MQTT密码")
    parser.add_argument("--env-count", type=int, default=50, help="环境传感器数量")
    parser.add_argument("--ph-count", type=int, default=20, help="pH传感器数量")
    parser.add_argument("--interval", type=int, default=300, help="上报间隔(秒)")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--history", type=int, default=0, help="生成历史数据天数")
    parser.add_argument("--output", default="", help="历史数据输出文件")
    parser.add_argument("--summary", action="store_true", help="显示配置摘要")

    args = parser.parse_args()

    simulator = SensorSimulator(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=args.password,
        env_sensor_count=args.env_count,
        ph_sensor_count=args.ph_count,
        interval=args.interval
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
