"""
Comparator Service - 独立进程跨馆藏比对服务
每日凌晨 2:00 运行跨馆藏比对任务
使用独立连接池，不与主进程争用
"""

import os
import sys
import csv
import logging
import threading
import queue
import time
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from clickhouse_driver import Client
import requests
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("comparator-service")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.comparator.cross_library_data import (
        load_csv_data,
        compute_percentile_rank,
        generate_mock_csv,
        LIBRARIES,
        CSV_COLUMNS,
    )
except ImportError:
    LIBRARIES = [
        "本馆", "国家图书馆", "上海图书馆", "南京图书馆",
        "浙江图书馆", "故宫博物院", "北京大学图书馆", "中国科学院图书馆",
    ]
    CSV_COLUMNS = [
        "date", "library_name", "avg_temperature", "avg_humidity",
        "avg_ph", "avg_mold_spore",
    ]

    def generate_mock_csv(file_path: str) -> None:
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
        if not values:
            return 50.0
        values_array = np.array(values, dtype=float)
        target = float(target_value)
        count_less_or_equal = np.sum(values_array <= target)
        percentile = (count_less_or_equal / len(values_array)) * 100.0
        return round(float(percentile), 2)


class NamedConnectionPool:
    """命名ClickHouse连接池"""

    def __init__(self, name: str, max_connections: int = 4):
        self.name = name
        self.max_connections = max_connections
        self._pool: "queue.Queue[Client]" = queue.Queue(maxsize=max_connections)
        self._created_count = 0
        self._lock = threading.Lock()
        self._total_checkouts = 0
        self._total_returns = 0
        self._timeouts = 0

    def _create_client(self) -> Optional[Client]:
        try:
            client = Client(
                host=os.getenv("CLICKHOUSE_HOST", "localhost"),
                port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
                user=os.getenv("CLICKHOUSE_USER", "default"),
                password=os.getenv("CLICKHOUSE_PASSWORD", ""),
                database=os.getenv("CLICKHOUSE_DATABASE", "ancient_medical_books"),
                connect_timeout=10,
                send_receive_timeout=30,
            )
            logger.info(f"[{self.name}] 创建ClickHouse连接 (池大小={self.max_connections})")
            return client
        except Exception as e:
            logger.error(f"[{self.name}] 创建ClickHouse连接失败: {e}")
            return None

    def acquire(self, timeout: float = 5.0) -> Optional[Client]:
        start_time = time.time()
        try:
            client = self._pool.get_nowait()
            self._total_checkouts += 1
            return client
        except queue.Empty:
            pass
        with self._lock:
            if self._created_count < self.max_connections:
                client = self._create_client()
                if client:
                    self._created_count += 1
                    self._total_checkouts += 1
                    return client
        try:
            remaining = timeout - (time.time() - start_time)
            if remaining > 0:
                client = self._pool.get(timeout=remaining)
                self._total_checkouts += 1
                return client
        except queue.Empty:
            pass
        self._timeouts += 1
        logger.warning(f"[{self.name}] 连接池获取超时")
        return None

    def release(self, client: Client) -> None:
        if client is None:
            return
        try:
            self._pool.put_nowait(client)
            self._total_returns += 1
        except queue.Full:
            try:
                client.disconnect()
            except Exception:
                pass
            with self._lock:
                self._created_count -= 1

    def close_all(self) -> None:
        closed = 0
        while not self._pool.empty():
            try:
                client = self._pool.get_nowait()
                client.disconnect()
                closed += 1
            except (queue.Empty, Exception):
                pass
        logger.info(f"[{self.name}] 连接池已关闭，释放{closed}个连接")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "max_connections": self.max_connections,
            "created": self._created_count,
            "idle": self._pool.qsize(),
            "checkouts": self._total_checkouts,
            "returns": self._total_returns,
            "timeouts": self._timeouts,
        }


@dataclass
class CrossLibraryComparisonResult:
    """跨馆藏比对结果"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    message_type: str = "cross_library_comparison_result"
    record_date: str = ""
    library_name: str = ""
    metric: str = ""
    value: float = 0.0
    percentile: float = 0.0
    percentile_rank: int = 0
    total_libraries: int = 0
    is_anomaly: bool = False
    data_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AlertMessage:
    """告警消息"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    message_type: str = "alert"
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    shelf_id: str = "ALL"
    slot_id: str = "ALL"
    alert_level: str = "orange"
    alert_type: str = ""
    alert_value: float = 0.0
    threshold: float = 0.0
    message: str = ""
    is_handled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComparatorStats:
    """比较器统计"""
    total_comparisons: int = 0
    total_anomalies: int = 0
    last_run_time: Optional[str] = None
    last_anomaly_time: Optional[str] = None
    csv_records_loaded: int = 0


METRIC_COLUMN_MAP = {
    "temperature": "avg_temperature",
    "humidity": "avg_humidity",
    "ph": "avg_ph",
    "mold_spore": "avg_mold_spore",
}

METRIC_NAME_MAP = {
    "temperature": "温度",
    "humidity": "湿度",
    "ph": "pH值",
    "mold_spore": "霉菌孢子",
}


class ComparatorService:
    """跨馆藏比对服务（独立进程）"""

    def __init__(self):
        self._run_hour = int(os.getenv("COMPARATOR_RUN_HOUR", "2"))
        self._anomaly_threshold = float(os.getenv("COMPARATOR_ANOMALY_THRESHOLD", "95.0"))
        self._csv_data_path = os.getenv("COMPARATOR_CSV_PATH", str(BASE_DIR / "data" / "cross_library_comparison.csv"))
        self._libraries = os.getenv("COMPARATOR_LIBRARIES", ",".join(LIBRARIES)).split(",")
        self._metrics = ["temperature", "humidity", "ph", "mold_spore"]

        self._callback_url = os.getenv("MAIN_SERVICE_CALLBACK_URL", "http://localhost:8000/api/comparator/callback")
        self._alert_callback_url = os.getenv("MAIN_SERVICE_ALERT_URL", "http://localhost:8000/api/alert/callback")

        self._db_pool = NamedConnectionPool("comparator", max_connections=2)
        self._stats = ComparatorStats()
        self._csv_data: List[Dict[str, Any]] = []
        self._results_cache: List[Dict[str, Any]] = []
        self._alerts_cache: List[Dict[str, Any]] = []
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None

        self._result_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._alert_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._callback_thread: Optional[threading.Thread] = None

    def start(self):
        """启动服务"""
        if self._running:
            return
        self._running = True

        csv_path = Path(self._csv_data_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not csv_path.exists():
            logger.info(f"CSV文件不存在，生成初始数据: {csv_path}")
            generate_mock_csv(str(csv_path))
        self.load_csv_data()

        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True, name="comparator-scheduler")
        self._scheduler_thread.start()

        self._callback_thread = threading.Thread(target=self._callback_loop, daemon=True, name="comparator-callback")
        self._callback_thread.start()

        logger.info("Comparator Service 已启动")

    def stop(self):
        """停止服务"""
        self._running = False
        self._db_pool.close_all()
        logger.info("Comparator Service 已停止")

    def _scheduler_loop(self):
        """调度循环 - 每日凌晨2点运行"""
        logger.info(f"调度器已启动，每日 {self._run_hour}:00 执行比对")
        last_run_date = None
        while self._running:
            try:
                now = datetime.now()
                if now.hour == self._run_hour and now.minute == 0 and last_run_date != now.date():
                    logger.info("开始执行每日跨馆藏比对...")
                    results = self.compare_all()
                    anomalies = sum(1 for r in results if r.get("is_anomaly", False))
                    logger.info(f"跨馆藏比对完成: 共 {len(results)} 条结果, 异常 {anomalies} 条")
                    last_run_date = now.date()
                    time.sleep(60)
                time.sleep(30)
            except Exception as e:
                logger.error(f"调度器异常: {e}")
                time.sleep(5)

    def _callback_loop(self):
        """回调循环 - 通过HTTP回调发送结果到主服务"""
        while self._running:
            try:
                while not self._result_queue.empty():
                    result = self._result_queue.get_nowait()
                    self._send_callback(self._callback_url, result)

                while not self._alert_queue.empty():
                    alert = self._alert_queue.get_nowait()
                    self._send_callback(self._alert_callback_url, alert)

                time.sleep(1)
            except Exception as e:
                logger.error(f"回调循环异常: {e}")
                time.sleep(5)

    def _send_callback(self, url: str, data: Dict[str, Any]) -> bool:
        """发送HTTP回调"""
        try:
            response = requests.post(url, json=data, timeout=5)
            if response.status_code == 200:
                logger.debug(f"回调成功: {url}")
                return True
            else:
                logger.warning(f"回调失败: {url}, status={response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"回调异常: {url}, error={e}")
            return False

    def load_csv_data(self) -> List[Dict[str, Any]]:
        """加载CSV数据"""
        self._csv_data = load_csv_data(self._csv_data_path)
        self._stats.csv_records_loaded = len(self._csv_data)
        return self._csv_data

    def compute_percentiles(self, metric_name: str, value: float) -> float:
        """计算指定指标值的百分位数"""
        column = METRIC_COLUMN_MAP.get(metric_name)
        if not column or not self._csv_data:
            return 50.0
        values = [row[column] for row in self._csv_data]
        return compute_percentile_rank(values, value)

    def _get_latest_data(self) -> Dict[str, Dict[str, float]]:
        """获取各图书馆的最新数据"""
        if not self._csv_data:
            return {}
        latest_data: Dict[str, Dict[str, float]] = {}
        sorted_data = sorted(self._csv_data, key=lambda x: x["date"], reverse=True)
        for row in sorted_data:
            library = row["library_name"]
            if library not in latest_data:
                latest_data[library] = {
                    "temperature": row["avg_temperature"],
                    "humidity": row["avg_humidity"],
                    "ph": row["avg_ph"],
                    "mold_spore": row["avg_mold_spore"],
                    "date": row["date"],
                }
        return latest_data

    def compare_all(self) -> List[Dict[str, Any]]:
        """执行所有图书馆、所有指标的比较"""
        if not self._csv_data:
            self.load_csv_data()

        latest_data = self._get_latest_data()
        results: List[Dict[str, Any]] = []
        total_libraries = len(latest_data)
        today_str = datetime.now().strftime("%Y-%m-%d")

        for library in self._libraries:
            if library not in latest_data:
                continue
            lib_data = latest_data[library]
            lib_date = lib_data.get("date", today_str)

            for metric in self._metrics:
                value = lib_data.get(metric)
                if value is None:
                    continue

                percentile = self.compute_percentiles(metric, value)
                percentile_rank = int(round(percentile / 100.0 * total_libraries))
                is_anomaly = percentile > self._anomaly_threshold and metric in ["temperature", "humidity"]

                result = CrossLibraryComparisonResult(
                    record_date=lib_date,
                    library_name=library,
                    metric=metric,
                    value=float(value),
                    percentile=float(percentile),
                    percentile_rank=percentile_rank,
                    total_libraries=total_libraries,
                    is_anomaly=is_anomaly,
                    data_source="csv",
                )
                result_dict = result.to_dict()
                results.append(result_dict)
                self._result_queue.put(result_dict)
                self._save_to_database(result_dict)

                if is_anomaly and library == "本馆":
                    alert = self._create_anomaly_alert(metric, float(value), float(percentile))
                    alert_dict = alert.to_dict()
                    self._alert_queue.put(alert_dict)

        self._results_cache = results
        self._stats.total_comparisons += len(results)
        self._stats.last_run_time = datetime.now().isoformat()

        return results

    def _create_anomaly_alert(self, metric: str, value: float, percentile: float) -> AlertMessage:
        """创建异常预警"""
        metric_name = METRIC_NAME_MAP.get(metric, metric)
        alert = AlertMessage(
            shelf_id="ALL",
            slot_id="ALL",
            alert_level="orange",
            alert_type="cross_library_anomaly",
            alert_value=float(value),
            threshold=float(self._anomaly_threshold),
            message=f"【环境异常预警】本馆{metric_name}指标{value:.2f}在全国馆藏中处于第{percentile:.1f}百分位，超过{self._anomaly_threshold}%阈值，存在环境异常风险！请立即检查空调和除湿系统运行状态。"
        )
        self._stats.total_anomalies += 1
        self._stats.last_anomaly_time = datetime.now().isoformat()
        self._alerts_cache.append(alert.to_dict())
        logger.warning(f"跨馆藏异常预警: {metric_name}={value:.2f}, 百分位={percentile:.1f}%")
        return alert

    def _save_to_database(self, result: Dict[str, Any]):
        """保存比较结果到数据库（使用独立连接池）"""
        record = {
            "timestamp": result["timestamp"],
            "record_date": result["record_date"],
            "library_name": result["library_name"],
            "metric": result["metric"],
            "value": result["value"],
            "percentile": result["percentile"],
            "percentile_rank": result["percentile_rank"],
            "total_libraries": result["total_libraries"],
            "is_anomaly": 1 if result["is_anomaly"] else 0,
            "data_source": result["data_source"],
        }
        try:
            columns = list(record.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            col_names = ", ".join(columns)
            values_tuple = tuple(record[col] for col in columns)
            client = self._db_pool.acquire(timeout=3.0)
            if client:
                try:
                    query = f"INSERT INTO comparison_data ({col_names}) VALUES"
                    client.execute(query, [values_tuple])
                finally:
                    self._db_pool.release(client)
        except Exception as e:
            logger.warning(f"独立池写入失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "stats": asdict(self._stats),
            "config": {
                "run_hour": self._run_hour,
                "anomaly_threshold": self._anomaly_threshold,
                "csv_data_path": self._csv_data_path,
                "libraries": self._libraries,
                "metrics": self._metrics,
            },
            "pool_stats": self._db_pool.get_stats(),
            "callback_url": self._callback_url,
            "result_queue_size": self._result_queue.qsize(),
            "alert_queue_size": self._alert_queue.qsize(),
        }

    def get_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取缓存的比对结果"""
        return self._results_cache[-limit:] if limit > 0 else self._results_cache

    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取缓存的告警"""
        return self._alerts_cache[-limit:] if limit > 0 else self._alerts_cache


class CompareRequest(BaseModel):
    """比对请求"""
    force: bool = False


app = FastAPI(
    title="Comparator Service",
    description="跨馆藏比对独立服务",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = ComparatorService()


@app.on_event("startup")
async def startup_event():
    service.start()


@app.on_event("shutdown")
async def shutdown_event():
    service.stop()


@app.get("/")
async def root():
    return {
        "service": "comparator-service",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "pool_stats": service._db_pool.get_stats(),
        "csv_records": len(service._csv_data),
    }


@app.post("/compare")
async def trigger_compare(request: CompareRequest):
    """手动触发比对"""
    try:
        if request.force:
            service.load_csv_data()
        results = service.compare_all()
        return {
            "success": True,
            "count": len(results),
            "anomalies": sum(1 for r in results if r.get("is_anomaly", False)),
            "results": results,
        }
    except Exception as e:
        logger.error(f"比对失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """获取统计信息"""
    return service.get_stats()


@app.get("/results")
async def get_results(limit: int = 100):
    """获取比对结果"""
    return {
        "count": len(service._results_cache),
        "results": service.get_results(limit),
    }


@app.get("/alerts")
async def get_alerts(limit: int = 50):
    """获取告警信息"""
    return {
        "count": len(service._alerts_cache),
        "alerts": service.get_alerts(limit),
    }


@app.post("/reload")
async def reload_data():
    """重新加载CSV数据"""
    try:
        data = service.load_csv_data()
        return {
            "success": True,
            "records_loaded": len(data),
        }
    except Exception as e:
        logger.error(f"重新加载数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    host = os.getenv("COMPARATOR_SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("COMPARATOR_SERVICE_PORT", "8001"))
    logger.info(f"启动 Comparator Service: {host}:{port}")
    uvicorn.run(app, host=host, port=port)
