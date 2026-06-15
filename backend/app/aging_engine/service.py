"""
老化预测引擎
在独立进程中运行CPU密集型的纸张老化预测计算
"""
import asyncio
import logging
import math
import multiprocessing
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from ..core.config import config
from ..core.messages import (
    AgingPredictionRequest,
    AgingPredictionResult,
    ControlMessage,
    deserialize_message,
    serialize_message,
)
from ..core.queue_manager import queue_manager, ProcessQueueWrapper

logger = logging.getLogger(__name__)


@dataclass
class AgingEngineStats:
    """老化引擎统计"""
    total_predictions: int = 0
    total_errors: int = 0
    last_prediction_time: Optional[str] = None
    avg_prediction_time_ms: float = 0.0
    fitted_models: int = 0
    failed_fits: int = 0


class ArrheniusAgingModel:
    """
    纸张老化动力学模型 - 基于Arrhenius方程
    从config.yaml加载所有参数，不再硬编码
    """

    def __init__(self, paper_type: str = "bamboo"):
        arr_config = config.get_arrhenius_config()

        self.R = arr_config.get("R", 8.314)
        self.A = arr_config.get("A", 1.0e10)
        self.pH_DECAY_RATE_REF = arr_config.get("pH_decay_rate_ref", 0.005)
        self.REF_TEMP = arr_config.get("ref_temp", 298.15)
        self.REF_HUMIDITY = arr_config.get("ref_humidity", 50.0)

        paper_type_map = arr_config.get("paper_type_map", {})
        paper_types = arr_config.get("paper_types", {})

        self.paper_type_key = paper_type_map.get(paper_type, paper_type)
        if self.paper_type_key not in paper_types:
            self.paper_type_key = "bamboo"

        self.paper_type = paper_type
        self._set_paper_parameters(paper_types.get(self.paper_type_key, paper_types.get("bamboo", {})))

    def _set_paper_parameters(self, params: Dict[str, Any]):
        """从配置加载纸张参数"""
        self.initial_ph = params.get("ph0", 6.5)
        self.Ea = params.get("Ea", 78.0)
        self.k_factor = params.get("k_factor", 1.0)
        self.strength_factor = params.get("strength_factor", 1.0)
        self.display_name = params.get("name", "竹纸")

    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """边界钳位，防止数值异常"""
        return max(min_val, min(max_val, value))

    def arrhenius_rate(self, temperature_c: float) -> float:
        """计算Arrhenius速率常数"""
        temperature_c = self._clamp(temperature_c, -50.0, 100.0)
        T_kelvin = temperature_c + 273.15
        if T_kelvin <= 0:
            T_kelvin = 273.15

        exponent = -self.Ea * 1000 / (self.R * T_kelvin)
        exponent = self._clamp(exponent, -700, 700)
        k = self.A * math.exp(exponent)
        return k

    def humidity_factor(self, humidity: float) -> float:
        """湿度影响因子"""
        humidity = self._clamp(humidity, 0.1, 100.0)
        h_factor = math.pow(humidity / self.REF_HUMIDITY, 1.5)
        return h_factor

    def ph_decay_rate(self, temperature_c: float, humidity: float, current_ph: float = None) -> float:
        """计算pH下降速率 (每年pH下降量)"""
        if current_ph is None:
            current_ph = self.initial_ph
        current_ph = self._clamp(current_ph, 3.0, 9.0)

        k_ref = self.pH_DECAY_RATE_REF * self.k_factor
        k_temp = self.arrhenius_rate(temperature_c) / self.arrhenius_rate(self.REF_TEMP - 273.15)
        k_humid = self.humidity_factor(humidity)

        autocatalytic_factor = math.pow(10, -0.1 * (current_ph - 7.0))

        decay_rate = k_ref * k_temp * k_humid * autocatalytic_factor
        return decay_rate

    def predict_ph(self, initial_ph: float, temperature_c: float, humidity: float,
                   days: int, temperature_history: List[Tuple[float, float]] = None) -> float:
        """预测未来某一天的pH值"""
        initial_ph = self._clamp(initial_ph, 3.0, 9.0)

        if temperature_history is None:
            avg_temp = temperature_c
            avg_humid = humidity
        else:
            total_temp = sum(t for t, _ in temperature_history)
            total_humid = sum(h for _, h in temperature_history)
            n = len(temperature_history)
            avg_temp = total_temp / n if n > 0 else temperature_c
            avg_humid = total_humid / n if n > 0 else humidity

        current_ph = initial_ph
        total_days = days
        step_days = 1
        steps = total_days // step_days

        for _ in range(steps):
            decay_rate = self.ph_decay_rate(avg_temp, avg_humid, current_ph)
            ph_change = decay_rate * (step_days / 365.0)
            current_ph -= ph_change
            if current_ph < 3.0:
                current_ph = 3.0
                break

        return round(current_ph, 3)

    def fit_pH_trend(self, ph_history: List[Dict[str, Any]],
                     min_points: int = 3) -> Tuple[float, float, List[Dict[str, Any]]]:
        """
        使用最小二乘法拟合pH时间序列，计算年下降速率
        这是CPU密集型操作，在独立进程中运行

        Args:
            ph_history: pH历史数据，每个元素包含"date"和"ph_value"
            min_points: 最少数据点数量要求

        Returns:
            (annual_decay_rate, r_squared, daily_data)
        """
        if len(ph_history) < min_points:
            raise ValueError(f"数据点不足，需要至少{min_points}个点，当前只有{len(ph_history)}个")

        dates = []
        ph_values = []

        for item in ph_history:
            try:
                if isinstance(item.get("date"), str):
                    dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
                else:
                    dt = item.get("date", datetime.now())

                day_num = (dt - datetime(2020, 1, 1)).total_seconds() / 86400
                ph = float(item["ph_value"])

                dates.append(day_num)
                ph_values.append(ph)
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"跳过无效数据点: {e}")
                continue

        if len(dates) < min_points:
            raise ValueError(f"有效数据点不足，需要至少{min_points}个")

        x = np.array(dates, dtype=np.float64)
        y = np.array(ph_values, dtype=np.float64)

        n = len(x)
        sum_x = np.sum(x)
        sum_y = np.sum(y)
        sum_xy = np.sum(x * y)
        sum_xx = np.sum(x * x)

        denominator = n * sum_xx - sum_x * sum_x
        if abs(denominator) < 1e-10:
            raise ValueError("数据点重合，无法拟合")

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 1e-10 else 0.0

        annual_decay_rate = abs(slope) * 365.0

        daily_data = []
        for i, item in enumerate(ph_history[:len(x)]):
            daily_data.append({
                "date": item.get("date"),
                "ph_value": ph_values[i] if i < len(ph_values) else None,
                "predicted_value": y_pred[i] if i < len(y_pred) else None,
            })

        return annual_decay_rate, r_squared, daily_data

    def predict_lifetime(self, current_ph: float, decay_rate: float,
                         threshold_ph: float = 5.0) -> float:
        """预测剩余寿命（年）"""
        if current_ph <= threshold_ph:
            return 0.0
        if decay_rate <= 0:
            return 100.0

        years = (current_ph - threshold_ph) / decay_rate
        return max(0.0, min(100.0, years))

    def get_severity(self, lifetime_years: float) -> str:
        """根据剩余寿命获取严重程度"""
        if lifetime_years >= 50:
            return "normal"
        elif lifetime_years >= 20:
            return "mild"
        elif lifetime_years >= 10:
            return "moderate"
        elif lifetime_years >= 5:
            return "severe"
        else:
            return "critical"

    def aging_index(self, temperature_c: float, humidity: float, current_ph: float) -> Dict[str, Any]:
        """综合老化指数"""
        decay_rate = self.ph_decay_rate(temperature_c, humidity, current_ph)
        lifetime = self.predict_lifetime(current_ph, decay_rate)

        return {
            "decay_rate": decay_rate,
            "predicted_lifetime_years": lifetime,
            "aging_severity": self.get_severity(lifetime),
            "paper_type": self.display_name,
            "activation_energy": self.Ea,
        }


def aging_process_main(input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue):
    """
    老化预测进程主函数
    在独立进程中运行，处理CPU密集型计算
    """
    logger.info("老化预测进程已启动")

    engine_config = config.aging_engine
    run_interval = engine_config.get("run_interval", 3600)
    lookback_days = engine_config.get("lookback_days", 7)
    min_data_points = engine_config.get("min_data_points", 3)
    prediction_days = engine_config.get("prediction_days", [30, 90, 180, 365])

    stats = AgingEngineStats()
    model_cache: Dict[str, ArrheniusAgingModel] = {}
    running = True

    while running:
        try:
            data = input_queue.get(timeout=1.0)
            if data is None:
                continue

            msg = deserialize_message(data)

            if isinstance(msg, ControlMessage):
                if msg.action == "stop":
                    logger.info("收到停止命令，老化预测进程退出")
                    running = False
                    break
                elif msg.action == "status":
                    status_msg = AgingPredictionResult(
                        message_type="status",
                        data={"stats": stats.__dict__}
                    )
                    output_queue.put(serialize_message(status_msg))
                continue

            if not isinstance(msg, AgingPredictionRequest):
                logger.debug(f"忽略非预测请求: {msg.message_type}")
                continue

            start_time = time.time()

            paper_type_key = msg.paper_type
            if paper_type_key not in model_cache:
                model_cache[paper_type_key] = ArrheniusAgingModel(paper_type=paper_type_key)
            model = model_cache[paper_type_key]

            try:
                ph_history = msg.ph_history
                if len(ph_history) >= min_data_points:
                    decay_rate, r_squared, daily_history = model.fit_pH_trend(
                        ph_history, min_points=min_data_points
                    )
                    stats.fitted_models += 1
                else:
                    decay_rate = model.ph_decay_rate(
                        msg.temperature, msg.humidity, msg.current_ph
                    )
                    daily_history = []

                lifetime = model.predict_lifetime(msg.current_ph, decay_rate)
                severity = model.get_severity(lifetime)

                ph_predictions = {}
                for days in prediction_days:
                    ph_predictions[days] = model.predict_ph(
                        msg.current_ph, msg.temperature, msg.humidity, days
                    )

                result = AgingPredictionResult(
                    shelf_id=msg.shelf_id,
                    slot_id=msg.slot_id,
                    paper_type=model.display_name,
                    ph_decay_rate=decay_rate,
                    predicted_lifetime_years=lifetime,
                    ph_predictions=ph_predictions,
                    severity=severity,
                    daily_history=daily_history,
                )

                output_queue.put(serialize_message(result))

                elapsed_ms = (time.time() - start_time) * 1000
                stats.total_predictions += 1
                stats.avg_prediction_time_ms = (
                    stats.avg_prediction_time_ms * (stats.total_predictions - 1) + elapsed_ms
                ) / stats.total_predictions
                stats.last_prediction_time = datetime.now().isoformat()

            except ValueError as e:
                stats.failed_fits += 1
                stats.total_errors += 1
                logger.warning(f"老化预测拟合失败 {msg.shelf_id}/{msg.slot_id}: {e}")

                decay_rate = model.ph_decay_rate(
                    msg.temperature, msg.humidity, msg.current_ph
                )
                lifetime = model.predict_lifetime(msg.current_ph, decay_rate)

                ph_predictions = {}
                for days in prediction_days:
                    ph_predictions[days] = model.predict_ph(
                        msg.current_ph, msg.temperature, msg.humidity, days
                    )

                result = AgingPredictionResult(
                    shelf_id=msg.shelf_id,
                    slot_id=msg.slot_id,
                    paper_type=model.display_name,
                    ph_decay_rate=decay_rate,
                    predicted_lifetime_years=lifetime,
                    ph_predictions=ph_predictions,
                    severity=model.get_severity(lifetime),
                    daily_history=[],
                )
                output_queue.put(serialize_message(result))

            except Exception as e:
                stats.total_errors += 1
                logger.error(f"老化预测异常 {msg.shelf_id}/{msg.slot_id}: {e}")

        except multiprocessing.queues.Empty:
            continue
        except Exception as e:
            logger.error(f"老化进程异常: {e}")

    logger.info(f"老化预测进程已停止，统计: {stats.__dict__}")


class AgingEngineService:
    """
    老化预测引擎服务
    管理独立进程，通过multiprocessing.Queue通信
    """

    def __init__(self):
        self._request_queue = queue_manager.create_process_queue("aging_requests", maxsize=1000)
        self._result_queue = queue_manager.create_process_queue("aging_results", maxsize=1000)
        self._process: Optional[multiprocessing.Process] = None
        self._running = False
        self._result_task: Optional[asyncio.Task] = None
        self._output_queues: List[asyncio.Queue] = []

    def register_output_queue(self, queue: asyncio.Queue):
        """注册结果输出队列"""
        self._output_queues.append(queue)
        logger.info(f"AgingEngine注册输出队列")

    async def _process_results(self):
        """处理老化预测结果"""
        logger.info("开始监听老化预测结果")
        while self._running:
            try:
                result = await asyncio.to_thread(self._result_queue.get, timeout=1.0)
                if result is None:
                    continue

                msg = deserialize_message(result)

                for q in self._output_queues:
                    await q.put(msg)

            except multiprocessing.queues.Empty:
                continue
            except Exception as e:
                logger.error(f"处理老化预测结果异常: {e}")
                await asyncio.sleep(0.1)
        logger.info("停止监听老化预测结果")

    async def submit_prediction(self, request: AgingPredictionRequest) -> bool:
        """提交预测请求"""
        return await asyncio.to_thread(self._request_queue.put, request)

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        logger.info("启动老化预测引擎...")

        self._process = multiprocessing.Process(
            target=aging_process_main,
            args=(self._request_queue._queue, self._result_queue._queue),
            name="aging-engine-process",
            daemon=True,
        )
        self._process.start()

        self._result_task = asyncio.create_task(self._process_results())
        logger.info("老化预测引擎已启动")

    async def stop(self):
        """停止服务"""
        self._running = False

        try:
            stop_msg = ControlMessage(action="stop")
            self._request_queue.put(stop_msg)
        except Exception:
            pass

        if self._result_task:
            self._result_task.cancel()
            try:
                await self._result_task
            except asyncio.CancelledError:
                pass

        if self._process and self._process.is_alive():
            self._process.join(timeout=5)
            if self._process.is_alive():
                self._process.terminate()

        queue_manager.close_all_process_queues()
        logger.info("老化预测引擎已停止")

    def is_alive(self) -> bool:
        """进程是否存活"""
        return self._process is not None and self._process.is_alive()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "process_alive": self.is_alive(),
            "request_queue_size": self._request_queue.qsize(),
            "result_queue_size": self._result_queue.qsize(),
        }
