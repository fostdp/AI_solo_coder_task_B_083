import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path

from ..core.config import config
from ..core.messages import CrossLibraryComparisonResult, AlertMessage
from ..core.queue_manager import queue_manager, AsyncQueueWrapper
from ..batch_writer.service import BatchWriterService
from .cross_library_data import (
    load_csv_data,
    compute_percentile_rank,
    generate_mock_csv,
)

logger = logging.getLogger(__name__)


@dataclass
class ComparatorStats:
    """比较器统计"""
    total_comparisons: int = 0
    total_anomalies: int = 0
    last_run_time: Optional[str] = None
    last_anomaly_time: Optional[str] = None
    csv_records_loaded: int = 0


class CrossLibraryComparatorService:
    """
    跨馆藏比较服务
    每日凌晨2点运行，与其他图书馆数据进行比较，
    计算百分位数并触发环境异常预警
    """

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

    def __init__(self, batch_writer_service: BatchWriterService = None):
        comp_config = config.comparator

        self._run_interval = comp_config.get("run_interval", 86400)
        self._run_hour = comp_config.get("run_hour", 2)
        self._anomaly_threshold = comp_config.get("anomaly_percentile_threshold", 95.0)
        self._csv_data_path = comp_config.get("csv_data_path", "data/cross_library_comparison.csv")
        self._libraries = comp_config.get("libraries", [])
        self._metrics = comp_config.get("metrics", ["temperature", "humidity", "ph", "mold_spore"])

        self._output_queue: Optional[AsyncQueueWrapper] = None
        self._alert_queue: Optional[AsyncQueueWrapper] = None
        self._batch_writer = batch_writer_service

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = ComparatorStats()
        self._csv_data: List[Dict[str, Any]] = []

    def register_output_queue(self, queue: AsyncQueueWrapper):
        """注册输出队列，用于发送比较结果"""
        self._output_queue = queue
        logger.info("CrossLibraryComparatorService注册输出队列")

    def register_alert_queue(self, queue: AsyncQueueWrapper):
        """注册告警队列，用于发送异常告警"""
        self._alert_queue = queue
        logger.info("CrossLibraryComparatorService注册告警队列")

    def _resolve_csv_path(self) -> str:
        """解析CSV文件的绝对路径"""
        csv_path = Path(self._csv_data_path)
        if not csv_path.is_absolute():
            base_dir = Path(__file__).resolve().parent.parent.parent
            csv_path = base_dir / csv_path
        return str(csv_path)

    def load_csv_data(self) -> List[Dict[str, Any]]:
        """加载CSV数据"""
        csv_path = self._resolve_csv_path()
        data_dir = Path(csv_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)

        self._csv_data = load_csv_data(csv_path)
        self._stats.csv_records_loaded = len(self._csv_data)
        return self._csv_data

    def compute_percentiles(self, metric_name: str, value: float) -> float:
        """
        计算指定指标值的百分位数
        基于所有图书馆的历史数据
        """
        column = self.METRIC_COLUMN_MAP.get(metric_name)
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

    async def compare_all(self) -> List[CrossLibraryComparisonResult]:
        """
        执行所有图书馆、所有指标的比较
        返回比较结果列表
        """
        if not self._csv_data:
            self.load_csv_data()

        latest_data = self._get_latest_data()
        results: List[CrossLibraryComparisonResult] = []
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
                results.append(result)

                if is_anomaly and library == "本馆":
                    await self.trigger_anomaly_alert(metric, float(value), float(percentile))

        self._stats.total_comparisons += len(results)
        self._stats.last_run_time = datetime.now().isoformat()

        for result in results:
            if self._output_queue:
                await self._output_queue.put(result)

            if self._batch_writer:
                self._save_to_database(result)

        return results

    async def trigger_anomaly_alert(self, metric: str, value: float, percentile: float) -> AlertMessage:
        """
        触发环境异常预警
        """
        metric_name = self.METRIC_NAME_MAP.get(metric, metric)

        alert = AlertMessage(
            shelf_id="ALL",
            slot_id="ALL",
            alert_level="orange",
            alert_type="cross_library_anomaly",
            alert_value=float(value),
            threshold=float(self._anomaly_threshold),
            message=f"【环境异常预警】本馆{metric_name}指标{value:.2f}在全国馆藏中处于第{percentile:.1f}百分位，超过{self._anomaly_threshold}%阈值，存在环境异常风险！请立即检查空调和除湿系统运行状态。"
        )

        if self._alert_queue:
            await self._alert_queue.put(alert)

        self._stats.total_anomalies += 1
        self._stats.last_anomaly_time = datetime.now().isoformat()

        logger.warning(
            f"跨馆藏异常预警: {metric_name}={value:.2f}, "
            f"百分位={percentile:.1f}%, 阈值={self._anomaly_threshold}%"
        )

        return alert

    def _save_to_database(self, result: CrossLibraryComparisonResult):
        """保存比较结果到数据库"""
        if not self._batch_writer:
            return

        record = {
            "timestamp": result.timestamp,
            "record_date": result.record_date,
            "library_name": result.library_name,
            "metric": result.metric,
            "value": result.value,
            "percentile": result.percentile,
            "percentile_rank": result.percentile_rank,
            "total_libraries": result.total_libraries,
            "is_anomaly": 1 if result.is_anomaly else 0,
            "data_source": result.data_source,
        }

        self._batch_writer.writer.add("comparison_data", record)

    async def _should_run_now(self) -> bool:
        """检查是否应该在当前时间运行"""
        now = datetime.now()
        return now.hour == self._run_hour

    async def _main_loop(self):
        """主循环"""
        logger.info("跨馆藏比较服务已启动")

        csv_path = self._resolve_csv_path()
        data_dir = Path(csv_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)

        if not os.path.exists(csv_path):
            logger.info(f"CSV文件不存在，生成初始数据: {csv_path}")
            generate_mock_csv(csv_path)

        self.load_csv_data()

        while self._running:
            try:
                if await self._should_run_now():
                    logger.info("开始执行每日跨馆藏比较...")
                    results = await self.compare_all()
                    anomalies = sum(1 for r in results if r.is_anomaly)
                    logger.info(
                        f"跨馆藏比较完成: 共 {len(results)} 条结果, "
                        f"异常 {anomalies} 条"
                    )

                    await asyncio.sleep(3600)

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"跨馆藏比较服务异常: {e}")
                await asyncio.sleep(5)

        logger.info("跨馆藏比较服务已停止")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("CrossLibraryComparatorService已启动")

    async def stop(self):
        """停止服务"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        await queue_manager.flush_all_async()
        logger.info("CrossLibraryComparatorService已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "stats": self._stats.__dict__,
            "config": {
                "run_interval": self._run_interval,
                "run_hour": self._run_hour,
                "anomaly_threshold": self._anomaly_threshold,
                "csv_data_path": self._csv_data_path,
                "libraries": self._libraries,
                "metrics": self._metrics,
            },
            "output_queue_size": self._output_queue.qsize() if self._output_queue else 0,
            "alert_queue_size": self._alert_queue.qsize() if self._alert_queue else 0,
        }
