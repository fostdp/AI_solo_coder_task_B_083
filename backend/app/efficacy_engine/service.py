"""
药效评估引擎服务
基于贝叶斯统计方法评估三方古代药方的防霉效果
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..core.config import config
from ..core.messages import (
    EfficacyEvaluationRequest,
    EfficacyEvaluationResult,
)
from ..core.queue_manager import queue_manager, AsyncQueueWrapper
from .efficacy import (
    bayesian_efficacy_estimation,
    calculate_reduction_rate,
    BayesianEfficacyResult,
)

logger = logging.getLogger(__name__)


PRESCRIPTION_NAMES = {
    "yuncao": "芸草",
    "huangbo": "黄柏",
    "yanye": "烟叶",
}


@dataclass
class EfficacyEngineStats:
    """药效引擎统计"""
    total_evaluations: int = 0
    total_errors: int = 0
    last_evaluation_time: Optional[str] = None
    prescription_evaluations: Dict[str, int] = None

    def __post_init__(self):
        if self.prescription_evaluations is None:
            self.prescription_evaluations = {}


class SporeDataCollector:
    """孢子数据收集器"""

    def __init__(self, lookback_hours: int = 24):
        self.lookback_hours = lookback_hours
        self._data: Dict[str, List[Dict[str, Any]]] = {}

    def add_data(self, shelf_id: str, slot_id: str, mold_spore: float, timestamp: float = None):
        """添加孢子浓度数据"""
        if timestamp is None:
            timestamp = time.time()

        key = f"{shelf_id}:{slot_id}"
        if key not in self._data:
            self._data[key] = []

        self._data[key].append({
            "shelf_id": shelf_id,
            "slot_id": slot_id,
            "mold_spore": mold_spore,
            "timestamp": timestamp,
        })

        cutoff = time.time() - self.lookback_hours * 3600
        self._data[key] = [
            d for d in self._data[key] if d["timestamp"] > cutoff
        ]

    def get_data(self, shelf_id: str, slot_id: str) -> List[Dict[str, Any]]:
        """获取指定位置的孢子数据"""
        key = f"{shelf_id}:{slot_id}"
        return self._data.get(key, [])

    def get_shelf_data(self, shelf_ids: List[str]) -> List[Dict[str, Any]]:
        """获取指定书架的所有孢子数据"""
        result = []
        for key, data in self._data.items():
            if any(key.startswith(f"{shelf_id}:") for shelf_id in shelf_ids):
                result.extend(data)
        return result

    def get_before_after_data(
        self,
        shelf_ids: List[str],
        reference_time: float = None
    ) -> List[Dict[str, float]]:
        """
        获取处理前后的孢子数据对
        以reference_time为分界，之前为before，之后为after
        """
        if reference_time is None:
            reference_time = time.time() - 12 * 3600

        result = []
        shelf_data = self.get_shelf_data(shelf_ids)

        if not shelf_data:
            return result

        position_data: Dict[str, Dict[str, Any]] = {}

        for d in shelf_data:
            key = f"{d['shelf_id']}:{d['slot_id']}"
            if key not in position_data:
                position_data[key] = {"before": [], "after": []}

            if d["timestamp"] <= reference_time:
                position_data[key]["before"].append(d)
            else:
                position_data[key]["after"].append(d)

        for key, data in position_data.items():
            before_data = data["before"]
            after_data = data["after"]

            if before_data and after_data:
                avg_before = sum(d["mold_spore"] for d in before_data) / len(before_data)
                avg_after = sum(d["mold_spore"] for d in after_data) / len(after_data)

                shelf_id, slot_id = key.split(":")
                result.append({
                    "shelf_id": shelf_id,
                    "slot_id": slot_id,
                    "spores_before": avg_before,
                    "spores_after": avg_after,
                })

        return result


class EfficacyEngineService:
    """
    药效评估引擎服务
    定期评估三方药方的防霉效果，输出评估结果到队列
    """

    PRESCRIPTIONS = ["yuncao", "huangbo", "yanye"]

    def __init__(self):
        self._request_queue = queue_manager.create_async_queue("efficacy_requests", maxsize=1000)
        self._result_queue = queue_manager.create_async_queue("efficacy_results", maxsize=1000)

        self._running = False
        self._process_task: Optional[asyncio.Task] = None
        self._periodic_task: Optional[asyncio.Task] = None
        self._stats = EfficacyEngineStats()

        eff_config = config.efficacy_engine
        self._run_interval = eff_config.get("run_interval", 3600)
        self._control_group_shelves = eff_config.get("control_group_shelves", ["SHELF-01", "SHELF-02"])
        self._treatment_group_shelves = eff_config.get("treatment_group_shelves", {
            "yuncao": ["SHELF-03", "SHELF-04"],
            "huangbo": ["SHELF-05", "SHELF-06"],
            "yanye": ["SHELF-07", "SHELF-08"],
        })
        bayesian_prior = eff_config.get("bayesian_prior", {"alpha": 2.0, "beta": 2.0})
        self._prior_alpha = bayesian_prior.get("alpha", 2.0)
        self._prior_beta = bayesian_prior.get("beta", 2.0)
        self._min_sample_size = eff_config.get("min_sample_size", 10)
        self._ci_level = eff_config.get("ci_level", 0.95)

        self._data_collector = SporeDataCollector(lookback_hours=48)

    def get_request_queue(self) -> AsyncQueueWrapper:
        """获取请求队列"""
        return self._request_queue

    def get_result_queue(self) -> AsyncQueueWrapper:
        """获取结果队列"""
        return self._result_queue

    async def submit_evaluation(self, request: EfficacyEvaluationRequest) -> bool:
        """提交评估请求"""
        return await self._request_queue.put(request)

    def record_spore_data(self, shelf_id: str, slot_id: str, mold_spore: float, timestamp: float = None):
        """记录孢子浓度数据用于评估"""
        self._data_collector.add_data(shelf_id, slot_id, mold_spore, timestamp)

    async def evaluate_prescription(
        self,
        prescription: str,
        shelf_id: Optional[str] = None,
        slot_id: Optional[str] = None
    ) -> Optional[EfficacyEvaluationResult]:
        """
        评估单个药方的效果

        Args:
            prescription: 药方名称 (yuncao, huangbo, yanye)
            shelf_id: 可选，指定书架ID
            slot_id: 可选，指定格口ID

        Returns:
            EfficacyEvaluationResult 或 None（数据不足时）
        """
        if prescription not in self.PRESCRIPTIONS:
            logger.warning(f"未知的药方: {prescription}")
            return None

        treatment_shelves = self._treatment_group_shelves.get(prescription, [])
        if not treatment_shelves:
            logger.warning(f"药方 {prescription} 没有配置治疗组书架")
            return None

        reference_time = time.time() - self._run_interval

        if shelf_id and slot_id:
            treatment_data = self._data_collector.get_before_after_data(
                [shelf_id], reference_time
            )
            target_shelf = shelf_id
            target_slot = slot_id
        else:
            treatment_data = self._data_collector.get_before_after_data(
                treatment_shelves, reference_time
            )
            target_shelf = treatment_shelves[0] if treatment_shelves else ""
            target_slot = ""

        control_data = self._data_collector.get_before_after_data(
            self._control_group_shelves, reference_time
        )

        sample_size = min(len(treatment_data), len(control_data))
        if sample_size < self._min_sample_size:
            logger.debug(
                f"药方 {prescription} 数据不足: "
                f"治疗组{len(treatment_data)}条, 对照组{len(control_data)}条, "
                f"需要至少{self._min_sample_size}条"
            )

            if treatment_data and control_data:
                sample_size = min(len(treatment_data), len(control_data))
                treatment_data = treatment_data[:sample_size]
                control_data = control_data[:sample_size]
            else:
                return None

        try:
            bayesian_result = bayesian_efficacy_estimation(
                treatment_data=treatment_data,
                control_data=control_data,
                prior_alpha=self._prior_alpha,
                prior_beta=self._prior_beta,
                ci_level=self._ci_level,
            )
        except Exception as e:
            logger.error(f"贝叶斯评估失败 {prescription}: {e}")
            self._stats.total_errors += 1
            return None

        spores_before = sum(d["spores_before"] for d in treatment_data) / len(treatment_data)
        spores_after = sum(d["spores_after"] for d in treatment_data) / len(treatment_data)
        reduction_rate = calculate_reduction_rate(spores_before, spores_after)

        result = EfficacyEvaluationResult(
            prescription=prescription,
            shelf_id=target_shelf,
            slot_id=target_slot,
            treatment_group=PRESCRIPTION_NAMES.get(prescription, prescription),
            reduction_rate=reduction_rate,
            efficacy_mean=bayesian_result.posterior_mean,
            efficacy_ci_low=bayesian_result.ci_low,
            efficacy_ci_high=bayesian_result.ci_high,
            posterior_mean=bayesian_result.posterior_mean,
            posterior_var=bayesian_result.posterior_var,
            sample_size=sample_size,
            spores_before=spores_before,
            spores_after=spores_after,
        )

        logger.info(
            f"药方评估完成 [{prescription}]: "
            f"减少率={reduction_rate:.2%}, "
            f"后验均值={bayesian_result.posterior_mean:.4f}, "
            f"95%CI=[{bayesian_result.ci_low:.4f}, {bayesian_result.ci_high:.4f}], "
            f"样本量={sample_size}"
        )

        self._stats.total_evaluations += 1
        self._stats.last_evaluation_time = datetime.now().isoformat()
        self._stats.prescription_evaluations[prescription] = (
            self._stats.prescription_evaluations.get(prescription, 0) + 1
        )

        return result

    async def evaluate_all(self) -> List[EfficacyEvaluationResult]:
        """评估所有药方"""
        results = []
        for prescription in self.PRESCRIPTIONS:
            result = await self.evaluate_prescription(prescription)
            if result:
                results.append(result)
                await self._result_queue.put(result)

        logger.info(f"完成所有药方评估，共 {len(results)} 个有效结果")
        return results

    def get_efficacy_summary(self) -> Dict[str, Any]:
        """获取药效评估摘要"""
        summary = {
            "stats": self._stats.__dict__,
            "prescriptions": {},
            "control_group": self._control_group_shelves,
            "treatment_groups": self._treatment_group_shelves,
            "bayesian_prior": {
                "alpha": self._prior_alpha,
                "beta": self._prior_beta,
            },
            "config": {
                "run_interval": self._run_interval,
                "min_sample_size": self._min_sample_size,
                "ci_level": self._ci_level,
            },
        }

        for prescription in self.PRESCRIPTIONS:
            treatment_shelves = self._treatment_group_shelves.get(prescription, [])
            treatment_data = self._data_collector.get_shelf_data(treatment_shelves)
            control_data = self._data_collector.get_shelf_data(self._control_group_shelves)

            summary["prescriptions"][prescription] = {
                "name": PRESCRIPTION_NAMES.get(prescription, prescription),
                "treatment_shelves": treatment_shelves,
                "treatment_data_points": len(treatment_data),
                "control_data_points": len(control_data),
            }

        return summary

    async def _process_requests(self):
        """处理评估请求队列"""
        logger.info("药效评估引擎请求处理器已启动")
        while self._running:
            try:
                request = await self._request_queue.get(timeout=1.0)
                if request is None:
                    continue

                if isinstance(request, EfficacyEvaluationRequest):
                    result = await self.evaluate_prescription(
                        prescription=request.prescription,
                        shelf_id=request.shelf_id,
                        slot_id=request.slot_id,
                    )
                    if result:
                        await self._result_queue.put(result)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._stats.total_errors += 1
                logger.error(f"处理药效评估请求异常: {e}")
                await asyncio.sleep(0.1)

        logger.info("药效评估引擎请求处理器已停止")

    async def _periodic_evaluation(self):
        """定期执行评估"""
        logger.info("药效评估引擎定期评估任务已启动")
        while self._running:
            try:
                await asyncio.sleep(self._run_interval)
                if not self._running:
                    break

                logger.info("开始定期药效评估...")
                await self.evaluate_all()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats.total_errors += 1
                logger.error(f"定期药效评估异常: {e}")
                await asyncio.sleep(1.0)

        logger.info("药效评估引擎定期评估任务已停止")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        self._process_task = asyncio.create_task(self._process_requests())
        self._periodic_task = asyncio.create_task(self._periodic_evaluation())
        logger.info("药效评估引擎服务已启动")

    async def stop(self):
        """停止服务"""
        self._running = False

        for task in [self._process_task, self._periodic_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._process_task = None
        self._periodic_task = None
        await queue_manager.flush_all_async()
        logger.info("药效评估引擎服务已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "stats": self._stats.__dict__,
            "queues": {
                "request_queue_size": self._request_queue.qsize(),
                "result_queue_size": self._result_queue.qsize(),
            },
        }
