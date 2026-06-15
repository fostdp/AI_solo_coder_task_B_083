"""
霉菌风险计算引擎
负责霉菌生长速率、孢子浓度预测和风险评估
"""
import asyncio
import logging
import math
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

from ..core.config import config
from ..core.messages import (
    MoldPredictionRequest,
    MoldPredictionResult,
    AlertMessage,
)
from ..core.queue_manager import queue_manager, AsyncQueueWrapper

logger = logging.getLogger(__name__)


@dataclass
class MoldEngineStats:
    """霉菌引擎统计"""
    total_predictions: int = 0
    total_errors: int = 0
    last_prediction_time: Optional[str] = None
    high_risk_alerts: int = 0
    active_mold_detected: int = 0


class MoldGrowthModel:
    """
    霉菌生长模型 - 从config.yaml加载参数
    基于罗氏模型（Rasch model）：RH>70%且T>15℃时生长速率指数上升
    """

    def __init__(self, mold_type: str = "mixed"):
        mold_config = config.get_mold_config()
        self.mold_types = mold_config.get("mold_types", {})
        self.mold_type = mold_type
        self.params = self._get_params()

    def _get_params(self) -> Dict[str, Any]:
        if self.mold_type in self.mold_types:
            return self.mold_types[self.mold_type]
        else:
            return self._get_mixed_params()

    def _get_mixed_params(self) -> Dict[str, Any]:
        types = list(self.mold_types.values())
        if not types:
            return {
                "name": "混合霉菌",
                "opt_temp": 25.0,
                "min_temp": 5.0,
                "max_temp": 45.0,
                "opt_humidity": 85.0,
                "min_humidity": 65.0,
                "growth_rate": 1.0,
                "spore_production": 0.8,
                "paper_damage": 0.8,
            }

        n = len(types)
        return {
            "name": "混合霉菌",
            "opt_temp": sum(t["opt_temp"] for t in types) / n,
            "min_temp": min(t["min_temp"] for t in types),
            "max_temp": max(t["max_temp"] for t in types),
            "opt_humidity": sum(t["opt_humidity"] for t in types) / n,
            "min_humidity": min(t["min_humidity"] for t in types),
            "growth_rate": sum(t["growth_rate"] for t in types) / n,
            "spore_production": sum(t["spore_production"] for t in types) / n,
            "paper_damage": sum(t["paper_damage"] for t in types) / n,
        }

    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """边界钳位"""
        return max(min_val, min(max_val, value))

    def temperature_response(self, temperature_c: float) -> float:
        """
        温度响应函数（钟形曲线）
        返回0-1之间的值
        """
        temperature_c = self._clamp(temperature_c, -50.0, 100.0)

        if temperature_c <= self.params["min_temp"] or temperature_c >= self.params["max_temp"]:
            return 0.0

        opt = self.params["opt_temp"]
        min_t = self.params["min_temp"]
        max_t = self.params["max_temp"]

        if temperature_c <= opt:
            t_factor = math.pow((temperature_c - min_t) / (opt - min_t), 0.8)
        else:
            t_factor = math.pow((max_t - temperature_c) / (max_t - opt), 1.2)

        return self._clamp(t_factor, 0.0, 1.0)

    def humidity_response(self, humidity: float) -> float:
        """
        湿度响应函数（S型曲线）
        RH > 70%时生长速率指数上升（罗氏模型）
        返回0-1之间的值
        """
        humidity = self._clamp(humidity, 0.0, 100.0)
        min_h = self.params["min_humidity"]
        opt_h = self.params["opt_humidity"]

        if humidity < min_h:
            return 0.0
        if humidity >= opt_h:
            return 1.0

        h_factor = 1.0 / (1.0 + math.exp(-0.5 * (humidity - (min_h + opt_h) / 2)))
        h_factor = (h_factor - 0.5) * 2.0
        return self._clamp(h_factor, 0.0, 1.0)

    def growth_rate(self, temperature_c: float, humidity: float) -> float:
        """
        计算综合生长速率（孢子/天）
        罗氏模型：RH>70%且T>15℃时生长速率指数上升
        """
        t_resp = self.temperature_response(temperature_c)
        h_resp = self.humidity_response(humidity)

        if t_resp <= 0.01 or h_resp <= 0.01:
            return 0.0

        base_rate = self.params["growth_rate"]

        if humidity > 70.0 and temperature_c > 15.0:
            rh_factor = math.exp(0.08 * (humidity - 70.0))
            temp_factor = math.exp(0.05 * (temperature_c - 15.0))
            roche_factor = min(rh_factor * temp_factor, 100.0)
        else:
            roche_factor = 1.0

        rate = base_rate * t_resp * h_resp * roche_factor * 100
        return max(0.0, rate)

    def predict_spore_concentration(self, current_spores: float, temperature_c: float,
                                     humidity: float, days: int) -> float:
        """预测未来的孢子浓度"""
        current_spores = self._clamp(current_spores, 0.0, 1_000_000.0)

        growth_rate = self.growth_rate(temperature_c, humidity)

        if growth_rate <= 0.001:
            return current_spores

        carrying_capacity = 100_000.0
        growth = growth_rate * (days / 30.0)
        predicted = current_spores + growth * (1 - current_spores / carrying_capacity)

        return self._clamp(predicted, 0.0, carrying_capacity)

    def is_active_mold(self, temperature_c: float, humidity: float,
                       current_spores: float) -> bool:
        """检测是否存在活性霉菌"""
        growth_rate = self.growth_rate(temperature_c, humidity)
        return growth_rate > 5.0 and current_spores > 1000.0

    def mold_risk_index(self, temperature_c: float, humidity: float,
                        current_spores: float) -> Dict[str, Any]:
        """综合霉菌风险评估"""
        growth_rate = self.growth_rate(temperature_c, humidity)

        predicted_7d = self.predict_spore_concentration(current_spores, temperature_c, humidity, 7)
        predicted_30d = self.predict_spore_concentration(current_spores, temperature_c, humidity, 30)

        is_active = self.is_active_mold(temperature_c, humidity, current_spores)

        if is_active:
            risk_score = 100.0
            risk_level = "critical"
        elif predicted_7d > 5000:
            risk_score = 80.0
            risk_level = "high"
        elif predicted_7d > 2000:
            risk_score = 60.0
            risk_level = "moderate"
        elif predicted_7d > 500:
            risk_score = 40.0
            risk_level = "low"
        else:
            risk_score = 20.0 * (predicted_7d / 500.0) if predicted_7d > 0 else 0.0
            risk_level = "negligible"

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "growth_rate": growth_rate,
            "predicted_spores_7d": predicted_7d,
            "predicted_spores_30d": predicted_30d,
            "is_active_mold": is_active,
            "temperature_response": self.temperature_response(temperature_c),
            "humidity_response": self.humidity_response(humidity),
        }


class MoldEngineService:
    """
    霉菌风险计算引擎服务
    监听预测请求队列，返回霉菌风险评估结果
    """

    def __init__(self):
        self._request_queue = queue_manager.create_async_queue("mold_requests", maxsize=1000)
        self._result_queue = queue_manager.create_async_queue("mold_results", maxsize=1000)
        self._alert_queue: Optional[AsyncQueueWrapper] = None

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = MoldEngineStats()

        self._model_cache: Dict[str, MoldGrowthModel] = {}

        engine_config = config.mold_engine
        self._default_mold_type = engine_config.get("default_mold_type", "mixed")
        self._prediction_days = engine_config.get("prediction_days", [7, 30])
        self._run_interval = engine_config.get("run_interval", 1800)

    def set_alert_queue(self, queue: AsyncQueueWrapper):
        """设置告警队列"""
        self._alert_queue = queue

    def get_request_queue(self) -> AsyncQueueWrapper:
        """获取请求队列"""
        return self._request_queue

    def get_result_queue(self) -> AsyncQueueWrapper:
        """获取结果队列"""
        return self._result_queue

    async def submit_prediction(self, request: MoldPredictionRequest) -> bool:
        """提交预测请求"""
        return await self._request_queue.put(request)

    async def _process_request(self, request: MoldPredictionRequest) -> MoldPredictionResult:
        """处理单个预测请求"""
        mold_type = request.mold_type or self._default_mold_type

        if mold_type not in self._model_cache:
            self._model_cache[mold_type] = MoldGrowthModel(mold_type=mold_type)

        model = self._model_cache[mold_type]

        risk = model.mold_risk_index(
            temperature_c=request.temperature,
            humidity=request.humidity,
            current_spores=request.current_spores,
        )

        result = MoldPredictionResult(
            shelf_id=request.shelf_id,
            slot_id=request.slot_id,
            risk_score=risk["risk_score"],
            risk_level=risk["risk_level"],
            growth_rate=risk["growth_rate"],
            predicted_spores_7d=risk["predicted_spores_7d"],
            predicted_spores_30d=risk["predicted_spores_30d"],
            is_active_mold=risk["is_active_mold"],
        )

        if risk["is_active_mold"]:
            self._stats.active_mold_detected += 1
            if self._alert_queue:
                alert = AlertMessage(
                    shelf_id=request.shelf_id,
                    slot_id=request.slot_id,
                    alert_level="red",
                    alert_type="active_mold",
                    alert_value=risk["predicted_spores_7d"],
                    threshold=1000.0,
                    message=f"检测到活性霉菌生长，预测7天后孢子浓度: {risk['predicted_spores_7d']:.0f} CFU/m³",
                )
                await self._alert_queue.put(alert)

        if risk["risk_level"] in ("high", "moderate"):
            self._stats.high_risk_alerts += 1

        return result

    async def _process_loop(self):
        """主处理循环"""
        logger.info("霉菌风险计算引擎已启动")
        while self._running:
            try:
                request = await self._request_queue.get(timeout=1.0)
                if request is None:
                    continue

                start_time = time.time()

                if isinstance(request, MoldPredictionRequest):
                    result = await self._process_request(request)
                    await self._result_queue.put(result)

                    self._stats.total_predictions += 1
                    self._stats.last_prediction_time = datetime.now().isoformat()

                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.debug(f"霉菌预测完成 {request.shelf_id}/{request.slot_id}: {elapsed_ms:.1f}ms")

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._stats.total_errors += 1
                logger.error(f"霉菌预测异常: {e}")
                await asyncio.sleep(0.1)
        logger.info("霉菌风险计算引擎已停止")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("霉菌风险计算引擎服务已启动")

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
        logger.info("霉菌风险计算引擎服务已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "stats": self._stats.__dict__,
            "queues": {
                "request_queue_size": self._request_queue.qsize(),
                "result_queue_size": self._result_queue.qsize(),
            },
            "model_cache_size": len(self._model_cache),
        }
