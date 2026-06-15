import csv
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

LIBRARIES = [
    "本馆",
    "国家图书馆",
    "上海图书馆",
    "南京图书馆",
    "浙江图书馆",
    "故宫博物院",
    "北京大学图书馆",
    "中国科学院图书馆",
]

CSV_COLUMNS = [
    "date",
    "library_name",
    "avg_temperature",
    "avg_humidity",
    "avg_ph",
    "avg_mold_spore",
]


def generate_mock_csv(file_path: str) -> None:
    """
    生成模拟的跨馆藏历史数据
    为8个图书馆生成365天的历史数据
    """
    base_dir = Path(file_path).parent
    base_dir.mkdir(parents=True, exist_ok=True)

    np.random.seed(42)

    library_baselines = {
        "本馆": {"temp": 18.0, "humidity": 45.0, "ph": 6.8, "mold": 150.0},
        "国家图书馆": {"temp": 17.5, "humidity": 42.0, "ph": 6.9, "mold": 120.0},
        "上海图书馆": {"temp": 19.0, "humidity": 48.0, "ph": 6.7, "mold": 180.0},
        "南京图书馆": {"temp": 18.5, "humidity": 46.0, "ph": 6.8, "mold": 160.0},
        "浙江图书馆": {"temp": 19.5, "humidity": 50.0, "ph": 6.6, "mold": 200.0},
        "故宫博物院": {"temp": 17.0, "humidity": 40.0, "ph": 7.0, "mold": 100.0},
        "北京大学图书馆": {"temp": 18.2, "humidity": 44.0, "ph": 6.8, "mold": 140.0},
        "中国科学院图书馆": {"temp": 17.8, "humidity": 43.0, "ph": 6.9, "mold": 130.0},
    }

    start_date = datetime.now() - timedelta(days=365)

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for day in range(365):
            current_date = start_date + timedelta(days=day)
            date_str = current_date.strftime("%Y-%m-%d")
            seasonal_temp_offset = 5.0 * np.sin(2 * np.pi * day / 365)

            for library in LIBRARIES:
                baseline = library_baselines[library]
                temp = baseline["temp"] + seasonal_temp_offset + np.random.normal(0, 0.8)
                humidity = baseline["humidity"] + np.random.normal(0, 3.0)
                ph = baseline["ph"] + np.random.normal(0, 0.1)
                mold = max(0, baseline["mold"] + np.random.normal(0, 30.0))

                if day > 200 and library == "本馆":
                    temp += 3.0
                    humidity += 8.0
                    mold += 150.0

                writer.writerow({
                    "date": date_str,
                    "library_name": library,
                    "avg_temperature": round(temp, 2),
                    "avg_humidity": round(humidity, 2),
                    "avg_ph": round(ph, 2),
                    "avg_mold_spore": round(mold, 2),
                })

    logger.info(f"已生成模拟CSV数据: {file_path}, 共 {365 * len(LIBRARIES)} 条记录")


def load_csv_data(file_path: str) -> List[Dict[str, Any]]:
    """
    加载并解析CSV数据
    """
    if not os.path.exists(file_path):
        logger.warning(f"CSV文件不存在，生成模拟数据: {file_path}")
        generate_mock_csv(file_path)

    data = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    parsed_row = {
                        "date": row["date"],
                        "library_name": row["library_name"],
                        "avg_temperature": float(row["avg_temperature"]),
                        "avg_humidity": float(row["avg_humidity"]),
                        "avg_ph": float(row["avg_ph"]),
                        "avg_mold_spore": float(row["avg_mold_spore"]),
                    }
                    data.append(parsed_row)
                except (ValueError, KeyError) as e:
                    logger.warning(f"解析CSV行失败: {row}, 错误: {e}")
                    continue

        logger.info(f"已加载CSV数据: {file_path}, 共 {len(data)} 条记录")
        return data

    except Exception as e:
        logger.error(f"加载CSV数据失败: {e}")
        return []


def compute_percentile_rank(values: List[float], target_value: float) -> float:
    """
    使用numpy计算目标值在数据集中的百分位排名
    返回值范围: 0-100
    """
    if not values:
        return 50.0

    values_array = np.array(values, dtype=float)
    target = float(target_value)

    count_less_or_equal = np.sum(values_array <= target)
    percentile = (count_less_or_equal / len(values_array)) * 100.0

    return round(float(percentile), 2)
