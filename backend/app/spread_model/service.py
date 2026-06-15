"""
霉菌传播模型服务
基于SEIR传染病模型的书架间霉菌传播预测服务
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np

from ..core.config import config
from ..core.messages import (
    SpreadPredictionRequest,
    SpreadPredictionResult,
)
from ..core.queue_manager import queue_manager, AsyncQueueWrapper
from ..batch_writer.service import BatchWriterService
from .seir import (
    ShelfGraph,
    SEIRModel,
    simulate_spread,
    identify_hotspots,
    SimulationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class SpreadModelStats:
    """传播模型统计"""
    total_simulations: int = 0
    total_errors: int = 0
    last_simulation_time: Optional[str] = None
    total_hotspots_identified: int = 0
    total_results_written: int = 0


class SpreadModelService:
    """
    霉菌传播模型服务
    基于SEIR传染病模型预测书架间霉菌传播
    异步服务，每2小时自动运行一次
    """

    def __init__(self, batch_writer_service: Optional[BatchWriterService] = None):
        self._request_queue = queue_manager.create_async_queue("spread_requests", maxsize=1000)
        self._result_queue = queue_manager.create_async_queue("spread_results", maxsize=1000)
        self._batch_writer_service = batch_writer_service

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._stats = SpreadModelStats()

        self._shelf_graph: Optional[ShelfGraph] = None
        self._seir_params: Dict[str, float] = {}
        self._edge_params: Dict[str, Any] = {}
        self._last_simulation_results: List[SimulationResult] = []
        self._hotspots: List[Dict[str, Any]] = []

        spread_config = config.spread_engine
        self._run_interval = spread_config.get("run_interval", 7200)
        self._prediction_days = spread_config.get("prediction_days", 30)
        self._model_type = spread_config.get("model_type", "SEIR")
        self._seir_params = spread_config.get("seir_params", {
            "beta": 0.3,
            "sigma": 0.2,
            "gamma": 0.1,
            "mu": 0.01,
        })
        self._edge_params = spread_config.get("edge_weight_params", {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        })
        self._hotspot_threshold = spread_config.get("hotspot_threshold", 0.5)
        self._edge_params["ventilation_default"] = spread_config.get("ventilation_default", 0.5)
        self._edge_params["shelf_distance_default"] = spread_config.get("shelf_distance_default", 1.0)

    def set_batch_writer_service(self, service: BatchWriterService):
        """设置批量写入服务"""
        self._batch_writer_service = service
        if service:
            service.register_input_queue(self._result_queue)

    def get_request_queue(self) -> AsyncQueueWrapper:
        """获取请求队列"""
        return self._request_queue

    def get_result_queue(self) -> AsyncQueueWrapper:
        """获取结果队列"""
        return self._result_queue

    def build_shelf_graph(self) -> ShelfGraph:
        """
        构建书架图结构
        从shelf_layout配置读取，10个书架，5列，6层
        """
        shelf_layout = config.shelf_layout
        self._shelf_graph = ShelfGraph(shelf_layout, self._edge_params)
        logger.info("书架图结构已构建")
        return self._shelf_graph

    async def _init_shelf_graph_table(self) -> None:
        """初始化shelf_graph表，存储图结构"""
        if not self._shelf_graph or not self._batch_writer_service:
            return

        try:
            graph_data = self._shelf_graph.to_dict()
            timestamp = datetime.now().isoformat()

            for node in graph_data["nodes"]:
                record = {
                    "timestamp": timestamp,
                    "shelf_id": node["shelf_id"],
                    "row": node["row"],
                    "col": node["col"],
                    "ventilation": node["ventilation"],
                    "node_type": "shelf",
                }
                self._batch_writer_service.writer.add("shelf_graph_nodes", record)

            for edge in graph_data["edges"]:
                record = {
                    "timestamp": timestamp,
                    "from_shelf": edge["from"],
                    "to_shelf": edge["to"],
                    "weight": edge["weight"],
                    "distance": edge["distance"],
                }
                self._batch_writer_service.writer.add("shelf_graph_edges", record)

            logger.info("shelf_graph表初始化完成")
        except Exception as e:
            logger.error(f"初始化shelf_graph表失败: {e}")

    async def run_seir_simulation(
        self,
        start_shelf: str,
        days: Optional[int] = None
    ) -> List[SimulationResult]:
        """
        运行SEIR模拟
        从指定书架开始，模拟指定天数的传播

        参数:
            start_shelf: 起始感染书架ID
            days: 模拟天数，默认使用配置值

        返回:
            模拟结果列表
        """
        if self._shelf_graph is None:
            self.build_shelf_graph()

        simulation_days = days or self._prediction_days
        initial_infected = [start_shelf] if start_shelf else []

        logger.info(f"开始SEIR模拟: 起始书架={start_shelf}, 天数={simulation_days}")

        try:
            results = simulate_spread(
                graph=self._shelf_graph,
                initial_infected=initial_infected,
                days=simulation_days,
                seir_params=self._seir_params,
                edge_params=self._edge_params,
            )

            self._last_simulation_results = results
            self._stats.total_simulations += 1
            self._stats.last_simulation_time = datetime.now().isoformat()

            logger.info(f"SEIR模拟完成: {len(results)} 条结果")
            return results

        except Exception as e:
            self._stats.total_errors += 1
            logger.error(f"SEIR模拟失败: {e}")
            raise

    async def predict_spread(
        self,
        initial_infected: List[str]
    ) -> List[SpreadPredictionResult]:
        """
        预测传播，生成SpreadPredictionResult消息
        预测30天传播，识别热点

        参数:
            initial_infected: 初始感染书架ID列表

        返回:
            SpreadPredictionResult消息列表
        """
        if self._shelf_graph is None:
            self.build_shelf_graph()

        logger.info(f"开始传播预测: 初始感染书架={initial_infected}")

        try:
            prediction_date = datetime.now().isoformat()
            results = simulate_spread(
                graph=self._shelf_graph,
                initial_infected=initial_infected,
                days=self._prediction_days,
                seir_params=self._seir_params,
                edge_params=self._edge_params,
            )

            self._last_simulation_results = results

            hotspots = identify_hotspots(results, self._hotspot_threshold)
            self._hotspots = hotspots
            self._stats.total_hotspots_identified += len(hotspots)

            hotspot_shelves = {h["shelf_id"]: h for h in hotspots}

            prediction_results: List[SpreadPredictionResult] = []
            for result in results:
                is_hotspot = result.shelf_id in hotspot_shelves
                infection_prob = result.state.infection_prob

                msg = SpreadPredictionResult(
                    prediction_date=prediction_date,
                    model_type=self._model_type,
                    day=result.day,
                    shelf_id=result.shelf_id,
                    slot_id="",
                    S=result.state.S,
                    E=result.state.E,
                    I=result.state.I,
                    R=result.state.R,
                    infection_prob=infection_prob,
                    is_hotspot=is_hotspot,
                    spread_from=result.spread_from,
                    edge_weight=result.edge_weight,
                )
                prediction_results.append(msg)

            self._stats.total_simulations += 1
            self._stats.last_simulation_time = datetime.now().isoformat()

            logger.info(f"传播预测完成: {len(prediction_results)} 条结果, {len(hotspots)} 个热点")
            return prediction_results

        except Exception as e:
            self._stats.total_errors += 1
            logger.error(f"传播预测失败: {e}")
            raise

    async def get_hotspots(
        self,
        threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        获取热点书架
        基于最近一次模拟结果，识别感染概率超过阈值的书架

        参数:
            threshold: 感染概率阈值，默认使用配置值

        返回:
            热点书架列表
        """
        if not self._last_simulation_results:
            return []

        use_threshold = threshold or self._hotspot_threshold
        hotspots = identify_hotspots(self._last_simulation_results, use_threshold)

        return hotspots

    def get_spread_directions(self) -> List[Tuple[str, str, float]]:
        """
        获取传播方向箭头，用于前端展示
        返回: (from_shelf, to_shelf, weight) 列表
        """
        if self._shelf_graph is None:
            return []
        return self._shelf_graph.get_spread_directions()

    async def _process_request(self, request: SpreadPredictionRequest) -> List[SpreadPredictionResult]:
        """处理传播预测请求"""
        initial_infected = request.initial_infected
        if request.start_shelf_id and not initial_infected:
            initial_infected = [request.start_shelf_id]

        results = await self.predict_spread(initial_infected)

        for result in results:
            result.prediction_date = request.prediction_date or result.prediction_date
            if request.days:
                result.day = min(result.day, request.days)

        return results

    async def _write_results_to_batch(self, results: List[SpreadPredictionResult]) -> None:
        """将结果写入批量写入器"""
        for result in results:
            await self._result_queue.put(result)
        self._stats.total_results_written += len(results)

    async def _timer_loop(self):
        """定时运行循环，每2小时运行一次"""
        logger.info("传播模型定时任务已启动")
        while self._running:
            try:
                await asyncio.sleep(self._run_interval)

                if not self._running:
                    break

                default_initial = ["SHELF-01"]
                logger.info(f"定时运行传播预测，初始感染: {default_initial}")

                results = await self.predict_spread(default_initial)
                await self._write_results_to_batch(results)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"传播模型定时任务异常: {e}")
                await asyncio.sleep(1)
        logger.info("传播模型定时任务已停止")

    async def _process_loop(self):
        """主处理循环"""
        logger.info("传播模型服务已启动")
        while self._running:
            try:
                request = await self._request_queue.get(timeout=1.0)
                if request is None:
                    continue

                start_time = time.time()

                if isinstance(request, SpreadPredictionRequest):
                    results = await self._process_request(request)
                    await self._write_results_to_batch(results)

                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.debug(f"传播预测完成: {len(results)}条结果, 耗时{elapsed_ms:.1f}ms")

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._stats.total_errors += 1
                logger.error(f"传播预测异常: {e}")
                await asyncio.sleep(0.1)
        logger.info("传播模型服务已停止")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True

        self.build_shelf_graph()
        await self._init_shelf_graph_table()

        self._task = asyncio.create_task(self._process_loop())
        self._timer_task = asyncio.create_task(self._timer_loop())

        logger.info("传播模型服务已启动")

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

        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
            self._timer_task = None

        await queue_manager.flush_all_async()
        logger.info("传播模型服务已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "stats": self._stats.__dict__,
            "queues": {
                "request_queue_size": self._request_queue.qsize(),
                "result_queue_size": self._result_queue.qsize(),
            },
            "graph": {
                "nodes": len(self._shelf_graph.nodes) if self._shelf_graph else 0,
                "edges": len(self._shelf_graph.edges) if self._shelf_graph else 0,
            },
            "hotspots_count": len(self._hotspots),
            "last_results_count": len(self._last_simulation_results),
        }
