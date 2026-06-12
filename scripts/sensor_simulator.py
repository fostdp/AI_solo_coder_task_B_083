"""
传感器模拟器
- 模拟 50 台环境传感器 (ENV-001 ~ ENV-050)，每5分钟上报温湿度/光照/VOC/霉菌孢子
- 模拟 20 台 pH 检测仪 (PH-001 ~ PH-020)，每5分钟上报纸张pH值
- 通过 MQTT 协议推送，Topic: ancient_med/sensor/env/{sensor_id}, ancient_med/sensor/ph/{sensor_id}
- 包含：日夜温度波动、季节趋势、随机异常事件（霉菌爆发/酸化/高温）
"""
import json
import math
import time
import random
import logging
import argparse
import threading
from datetime import datetime, timezone
from typing import List, Dict

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("sensor-sim")

SHELF_LAYOUT = [
    ("SH-A-01", 6, 8, 0, 0),
    ("SH-A-02", 6, 8, 3, 0),
    ("SH-A-03", 6, 8, 6, 0),
    ("SH-B-01", 6, 8, 0, 3),
    ("SH-B-02", 6, 8, 3, 3),
    ("SH-C-01", 6, 6, 0, 6),
    ("SH-C-02", 6, 6, 3, 6),
]

BOOK_TITLES = [
    "本草纲目", "伤寒论", "金匮要略", "黄帝内经", "千金要方",
    "本草经疏", "景岳全书", "医宗金鉴", "外科正宗", "针灸甲乙经",
    "脉经", "诸病源候论", "温病条辨", "温热经纬", "脾胃论",
]
DYNASTIES = ["明", "清"]


class SensorState:
    def __init__(self, sensor_id: str, sensor_type: str, shelf_id: str, slot_id: str,
                 x: float, y: float):
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.shelf_id = shelf_id
        self.slot_id = slot_id
        self.x, self.y = x, y
        self.base_temp = 20.5 + random.gauss(0, 0.8)
        self.base_humi = 48.0 + random.gauss(0, 2.0)
        self.base_ph = 7.0 - random.random() * 0.5
        if random.random() < 0.08:
            self.base_ph -= random.uniform(0.8, 1.5)
        self.base_mold = 80 + random.random() * 180
        self.anomaly_temp = 0.0
        self.anomaly_humi = 0.0
        self.anomaly_mold = 1.0
        self.anomaly_active = 0
        self.anomaly_ph = 0.0
        self._next_event = time.time() + random.uniform(60, 600)

    def step(self, now: float):
        diurnal = math.sin(2 * math.pi * ((now % 86400) / 86400 - 0.25))
        annual = math.sin(2 * math.pi * ((now % 31536000) / 31536000 - 0.3))
        noise_t = random.gauss(0, 0.25)
        noise_h = random.gauss(0, 0.8)

        self.temperature = (
            self.base_temp + diurnal * 2.5 + annual * 3.0 + noise_t + self.anomaly_temp
        )
        self.humidity = max(
            25.0, min(85.0, self.base_humi - diurnal * 4 + annual * 3 + noise_h + self.anomaly_humi)
        )
        self.light_lux = max(
            0.0,
            (8 + diurnal * 6 + random.gauss(0, 1.5)) * (1 + random.random() * 0.5),
        )
        self.voc_ppm = max(0.0, 0.2 + random.gauss(0.5, 0.2))
        self.mold_spores = max(
            0.0,
            (self.base_mold + diurnal * 60 + random.gauss(0, 40)) * self.anomaly_mold
            + (self.anomaly_active * random.uniform(500, 2000)),
        )
        self.active_mold = 1 if (self.anomaly_active or self.mold_spores > 1800 and random.random() < 0.3) else 0
        self.ph_value = max(
            4.0,
            self.base_ph
            - 0.00002 * (now / 300)
            + random.gauss(0, 0.015)
            + self.anomaly_ph,
        )

        if now > self._next_event:
            self._roll_event()
            self._next_event = now + random.uniform(300, 2400)

        if self.anomaly_temp != 0.0:
            self.anomaly_temp *= 0.98
            if abs(self.anomaly_temp) < 0.1:
                self.anomaly_temp = 0.0
        if self.anomaly_humi != 0.0:
            self.anomaly_humi *= 0.97
        if self.anomaly_mold != 1.0:
            self.anomaly_mold = 1.0 + (self.anomaly_mold - 1.0) * 0.95
        if self.anomaly_active:
            if random.random() < 0.05:
                self.anomaly_active = 0
        if self.anomaly_ph != 0.0:
            self.base_ph += self.anomaly_ph * 0.01
            self.anomaly_ph *= 0.99
            if abs(self.anomaly_ph) < 0.01:
                self.anomaly_ph = 0.0

    def _roll_event(self):
        r = random.random()
        if r < 0.15:
            self.anomaly_temp += random.choice([-1, 1]) * random.uniform(4, 10)
            logger.info(f"[{self.sensor_id}] 温度异常事件: ΔT={self.anomaly_temp:+.2f}℃")
        elif r < 0.30:
            self.anomaly_humi += random.uniform(8, 20)
            logger.info(f"[{self.sensor_id}] 湿度异常事件: ΔRH={self.anomaly_humi:+.1f}%")
        elif r < 0.45:
            self.anomaly_mold *= random.uniform(2, 6)
            if random.random() < 0.3:
                self.anomaly_active = 1
                logger.warning(f"[{self.sensor_id}] 活性霉菌爆发事件 @ {self.slot_id}")
            else:
                logger.info(f"[{self.sensor_id}] 霉菌孢子浓度升高")
        elif r < 0.55:
            self.anomaly_ph -= random.uniform(0.1, 0.5)
            logger.warning(f"[{self.sensor_id}] pH突降事件: ΔpH={self.anomaly_ph:+.3f} @ {self.slot_id}")
        elif r < 0.62:
            self.light_lux += random.uniform(50, 150)
            logger.info(f"[{self.sensor_id}] 光照过强异常")


class Simulator:
    def __init__(
        self,
        broker: str = "broker.emqx.io",
        port: int = 1883,
        username: str = "",
        password: str = "",
        interval: int = 300,
        speed: float = 1.0,
        count_env: int = 50,
        count_ph: int = 20,
        dry_run: bool = False,
    ):
        self.interval = interval
        self.speed = speed
        self.dry_run = dry_run
        self.client = mqtt.Client(
            client_id=f"ancient_med_simulator_{int(time.time())}",
            clean_session=True,
        )
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.broker = broker
        self.port = port
        self.env_sensors: List[SensorState] = []
        self.ph_sensors: List[SensorState] = []
        self._build_sensors(count_env, count_ph)
        self._stop = threading.Event()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"MQTT connected to {self.broker}:{self.port}")
        else:
            logger.error(f"MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"MQTT disconnected rc={rc}, reconnecting...")

    def _build_sensors(self, count_env: int, count_ph: int):
        slot_counter = 0
        all_slots = []
        for shelf_id, rows, cols, sx, sz in SHELF_LAYOUT:
            for r in range(1, rows + 1):
                for c in range(1, cols + 1):
                    x = sx + (c - 1) * 0.4
                    y = sz + (rows - r) * 0.5
                    all_slots.append((shelf_id, f"{shelf_id}-R{r:02d}-C{c:02d}", x, y))
                    slot_counter += 1

        random.seed(2024)
        random.shuffle(all_slots)

        for i in range(count_env):
            shelf_id, slot_id, x, y = all_slots[i % len(all_slots)]
            self.env_sensors.append(SensorState(
                sensor_id=f"ENV-{i + 1:03d}",
                sensor_type="ENV",
                shelf_id=shelf_id, slot_id=slot_id, x=x, y=y,
            ))

        for i in range(count_ph):
            shelf_id, slot_id, x, y = all_slots[(i * 3) % len(all_slots)]
            self.ph_sensors.append(SensorState(
                sensor_id=f"PH-{i + 1:03d}",
                sensor_type="PH",
                shelf_id=shelf_id, slot_id=slot_id, x=x, y=y,
            ))

        logger.info(f"Built {len(self.env_sensors)} env sensors + {len(self.ph_sensors)} pH sensors")
        logger.info(f"Total managed slots: {slot_counter} across {len(SHELF_LAYOUT)} shelves")

    def connect(self):
        if self.dry_run:
            logger.info("Dry-run mode: skip MQTT connect")
            return
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"MQTT connect error: {e}")

    def publish_once(self):
        now = time.time()
        sent_env = sent_ph = 0
        errors = 0

        for s in self.env_sensors:
            s.step(now)
            payload = {
                "timestamp": int(now * 1000),
                "sensor_id": s.sensor_id,
                "shelf_id": s.shelf_id,
                "slot_id": s.slot_id,
                "temperature": round(s.temperature, 3),
                "humidity": round(s.humidity, 2),
                "light_lux": round(s.light_lux, 2),
                "voc_ppm": round(s.voc_ppm, 4),
                "mold_spores": round(s.mold_spores, 1),
                "active_mold": s.active_mold,
                "rssi": -55 - random.randint(0, 25),
            }
            topic = f"ancient_med/sensor/env/{s.sensor_id}"
            if self.dry_run:
                sent_env += 1
                continue
            try:
                info = self.client.publish(
                    topic, json.dumps(payload, ensure_ascii=False), qos=1,
                )
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    sent_env += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1

        for s in self.ph_sensors:
            s.step(now)
            ph = s.ph_value
            cond = (
                "GOOD" if ph >= 6.8
                else "FAIR" if ph >= 6.2
                else "POOR" if ph >= 5.5
                else "VERY_POOR" if ph >= 5.0
                else "CRITICAL"
            )
            payload = {
                "timestamp": int(now * 1000),
                "sensor_id": s.sensor_id,
                "shelf_id": s.shelf_id,
                "slot_id": s.slot_id,
                "ph_value": round(ph, 4),
                "paper_cond": cond,
                "rssi": -60 - random.randint(0, 20),
            }
            topic = f"ancient_med/sensor/ph/{s.sensor_id}"
            if self.dry_run:
                sent_ph += 1
                continue
            try:
                info = self.client.publish(
                    topic, json.dumps(payload, ensure_ascii=False), qos=1,
                )
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    sent_ph += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1

        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sample = self.env_sensors[0]
        sample_ph = self.ph_sensors[0]
        logger.info(
            f"[{ts_str}] Published ENV={sent_env:3d} + PH={sent_ph:2d} | "
            f"errors={errors} | "
            f"T={sample.temperature:+.2f}℃ H={sample.humidity:.1f}% "
            f"mold={sample.mold_spores:.0f} active={sample.active_mold} | "
            f"pH={sample_ph.ph_value:.3f}"
        )

    def run_forever(self):
        logger.info(
            f"Starting simulator: interval={self.interval}s speed={self.speed}x "
            f"dry_run={self.dry_run}"
        )
        self.connect()
        try:
            while not self._stop.is_set():
                t0 = time.time()
                self.publish_once()
                elapsed = time.time() - t0
                sleep_s = max(0.01, self.interval / self.speed - elapsed)
                self._stop.wait(sleep_s)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.shutdown()

    def run_once(self, backfill_minutes: int = 0):
        self.connect()
        if backfill_minutes > 0:
            steps = backfill_minutes * 60 // self.interval
            logger.info(f"Backfilling {steps} intervals ({backfill_minutes} min)...")
            now = time.time()
            for i in range(steps):
                self.publish_once()
                time.sleep(min(0.02, 0.5 / self.speed))
        else:
            self.publish_once()
        self.shutdown()

    def shutdown(self):
        self._stop.set()
        if not self.dry_run:
            self.client.loop_stop()
            self.client.disconnect()
        logger.info("Simulator stopped")


def main():
    parser = argparse.ArgumentParser(description="古代医学文献馆藏传感器模拟器")
    parser.add_argument("--broker", default="broker.emqx.io", help="MQTT broker")
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("-u", "--username", default="", help="MQTT username")
    parser.add_argument("-p", "--password", default="", help="MQTT password")
    parser.add_argument("-i", "--interval", type=int, default=300, help="上报间隔(秒),默认5分钟")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="模拟速度倍率,1.0=实时")
    parser.add_argument("--env", type=int, default=50, help="环境传感器数量")
    parser.add_argument("--ph", type=int, default=20, help="pH传感器数量")
    parser.add_argument("--once", action="store_true", help="仅发送一次并退出")
    parser.add_argument("--backfill", type=int, default=0, help="回补N分钟数据(只报一次模式)")
    parser.add_argument("--dry-run", action="store_true", help="不实际发送MQTT,仅控制台输出")
    args = parser.parse_args()

    sim = Simulator(
        broker=args.broker, port=args.port,
        username=args.username, password=args.password,
        interval=args.interval, speed=args.speed,
        count_env=args.env, count_ph=args.ph,
        dry_run=args.dry_run,
    )

    if args.once or args.backfill > 0:
        sim.run_once(args.backfill)
    else:
        sim.run_forever()


if __name__ == "__main__":
    main()
