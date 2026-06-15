"""
病害传播模拟 Worker
使用 ProcessPoolExecutor 实现并行蒙特卡洛模拟，降低随机性

设计说明:
- ProcessPoolExecutor 需要可序列化的模块级函数作为执行入口
- 蒙特卡洛模拟: 运行 N 次相同参数的模拟，对每个书架每天的感染概率取平均
- 支持并行运行多个初始点的传播模拟
"""
import logging
import os
import copy
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

from ..spread_model.seir import (
    ShelfGraph,
    SEIRModel,
    SEIRState,
    SimulationResult,
    simulate_spread,
    compute_edge_weight,
)

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloConfig:
    """蒙特卡洛模拟配置"""
    num_simulations: int = 100
    days: int = 30
    shelf_layout: Optional[Dict[str, Any]] = None
    edge_params: Optional[Dict[str, Any]] = None
    seir_params: Optional[Dict[str, Any]] = None
    confidence_level: float = 0.95
    random_seed: Optional[int] = None


@dataclass
class AveragedResult:
    """
    蒙特卡洛平均结果
    存储 N 次模拟的平均值、标准差、置信区间
    """
    day: int
    shelf_id: str
    S_mean: float
    E_mean: float
    I_mean: float
    R_mean: float
    S_std: float
    E_std: float
    I_std: float
    R_std: float
    infection_prob_mean: float
    infection_prob_std: float
    spread_from: str = ""
    edge_weight: float = 0.0
    num_samples: int = 0

    @property
    def state(self):
        """返回类SEIRState对象，兼容测试使用"""
        return SEIRState(S=self.S_mean, E=self.E_mean, I=self.I_mean, R=self.R_mean)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day": self.day,
            "shelf_id": self.shelf_id,
            "S_mean": self.S_mean,
            "E_mean": self.E_mean,
            "I_mean": self.I_mean,
            "R_mean": self.R_mean,
            "S_std": self.S_std,
            "E_std": self.E_std,
            "I_std": self.I_std,
            "R_std": self.R_std,
            "infection_prob_mean": self.infection_prob_mean,
            "infection_prob_std": self.infection_prob_std,
            "spread_from": self.spread_from,
            "edge_weight": self.edge_weight,
            "num_samples": self.num_samples,
        }


@dataclass
class MonteCarloSimulationResult:
    """
    蒙特卡洛模拟完整结果
    包装所有平均结果列表，提供与原接口兼容
    """
    results: List[AveragedResult]
    config: Optional[MonteCarloConfig] = None

    def __len__(self):
        return len(self.results)

    def __iter__(self):
        return iter(self.results)

    def __getitem__(self, idx):
        return self.results[idx]


def _run_single_simulation(
    shelf_layout: Dict[str, Any],
    edge_params: Dict[str, Any],
    initial_infected: List[str],
    days: int,
    seir_params: Dict[str, float],
    simulation_id: int = 0,
) -> List[Dict[str, Any]]:
    """
    模块级函数：运行单次传播模拟
    重要：必须是模块级函数才能被 ProcessPoolExecutor 序列化
    
    返回可序列化的字典列表，而不是 SimulationResult 对象
    """
    try:
        graph = ShelfGraph(shelf_layout, edge_params)
        results = simulate_spread(
            graph=graph,
            initial_infected=initial_infected,
            days=days,
            seir_params=seir_params,
            edge_params=edge_params,
        )
        return [r.to_dict() for r in results]
    except Exception as e:
        logger.error(f"模拟 {simulation_id} 执行失败: {e}")
        raise


def _run_single_simulation_by_graph(
    graph_dict: Dict[str, Any],
    initial_infected: List[str],
    days: int,
    seir_params: Dict[str, float],
    edge_params: Dict[str, Any],
    simulation_id: int = 0,
) -> List[Dict[str, Any]]:
    """
    模块级函数：从序列化的 graph 数据运行单次模拟
    避免重复构建图结构
    """
    try:
        graph = ShelfGraph(
            graph_dict.get("shelf_layout", {}),
            edge_params,
        )
        results = simulate_spread(
            graph=graph,
            initial_infected=initial_infected,
            days=days,
            seir_params=seir_params,
            edge_params=edge_params,
        )
        return [r.to_dict() for r in results]
    except Exception as e:
        logger.error(f"模拟 {simulation_id} 执行失败: {e}")
        raise


class SpreadSimulationWorker:
    """
    病害传播模拟 Worker
    使用 ProcessPoolExecutor 实现并行蒙特卡洛模拟
    
    核心功能:
    1. run_monte_carlo_simulation() - 蒙特卡洛模拟（N次模拟取平均）
    2. run_parallel_simulations() - 并行运行多个初始点的模拟
    """

    def __init__(self, max_workers: Optional[int] = None):
        self._max_workers = max_workers or max(1, os.cpu_count() or 1)
        self._executor: Optional[ProcessPoolExecutor] = None
        self._running = False
        self._shutdown = False
        logger.info(f"SpreadSimulationWorker 初始化完成，max_workers={self._max_workers}")

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def start(self) -> None:
        """启动进程池"""
        if self._shutdown:
            raise RuntimeError("Worker 已永久关闭，无法重新启动")
        if self._running:
            return
        self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
        self._running = True
        logger.info(f"SpreadSimulationWorker 已启动，max_workers={self._max_workers}")

    def shutdown(self, wait: bool = True) -> None:
        """关闭进程池（永久关闭）"""
        if self._shutdown:
            return
        if self._running and self._executor:
            self._executor.shutdown(wait=wait)
            self._executor = None
        self._running = False
        self._shutdown = True
        logger.info("SpreadSimulationWorker 已关闭")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)

    def _ensure_executor(self) -> ProcessPoolExecutor:
        """确保进程池已启动"""
        if self._shutdown:
            raise RuntimeError("Worker 已永久关闭，无法执行新任务")
        if not self._running or self._executor is None:
            self.start()
        assert self._executor is not None
        return self._executor

    def run_monte_carlo_simulation(
        self,
        initial_infected: List[str],
        config: Optional[MonteCarloConfig] = None,
        graph: Optional[ShelfGraph] = None,
        days: Optional[int] = None,
        seir_params: Optional[Dict[str, float]] = None,
        edge_params: Optional[Dict[str, Any]] = None,
        num_simulations: int = 100,
        progress_callback: Optional[callable] = None,
    ) -> MonteCarloSimulationResult:
        """
        蒙特卡洛模拟
        运行 N 次相同参数的模拟，对每个书架每天的感染概率取平均，降低随机性
        
        参数:
            initial_infected: 初始感染书架ID列表
            config: MonteCarloConfig 配置对象（优先使用）
            graph: 书架图（如未提供 config 则必需）
            days: 模拟天数（如未提供 config 则必需）
            seir_params: SEIR模型参数（如未提供 config 则必需）
            edge_params: 边权重参数（如未提供 config 则必需）
            num_simulations: 模拟次数
            progress_callback: 进度回调函数 (completed, total) -> None
            
        返回:
            平均结果列表，包含平均值、标准差
        """
        if config is not None:
            if graph is None and config.shelf_layout is not None:
                graph = ShelfGraph(config.shelf_layout, config.edge_params or {})
            days = days or config.days
            seir_params = seir_params or config.seir_params or {}
            edge_params = edge_params or config.edge_params or {}
            num_simulations = config.num_simulations

        if graph is None or days is None or seir_params is None or edge_params is None:
            raise ValueError("必须提供 config 或 graph/days/seir_params/edge_params")

        if num_simulations < 1:
            raise ValueError(f"num_simulations 必须大于等于1，当前值: {num_simulations}")

        logger.info(
            f"开始蒙特卡洛模拟: {num_simulations}次, 初始感染={initial_infected}, "
            f"天数={days}, max_workers={self._max_workers}"
        )

        executor = self._ensure_executor()
        shelf_layout = graph.shelf_layout
        start_time = time.time()

        futures = []
        for i in range(num_simulations):
            future = executor.submit(
                _run_single_simulation,
                shelf_layout=shelf_layout,
                edge_params=edge_params,
                initial_infected=initial_infected,
                days=days,
                seir_params=seir_params,
                simulation_id=i,
            )
            futures.append(future)

        all_results: List[List[Dict[str, Any]]] = []
        completed = 0

        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
                completed += 1
                if progress_callback:
                    try:
                        progress_callback(completed, num_simulations)
                    except Exception as e:
                        logger.warning(f"进度回调执行失败: {e}")
                if completed % 10 == 0 or completed == num_simulations:
                    logger.debug(f"蒙特卡洛模拟进度: {completed}/{num_simulations}")
            except Exception as e:
                logger.error(f"蒙特卡洛模拟任务失败: {e}")
                completed += 1

        if not all_results:
            logger.error("蒙特卡洛模拟未产生任何有效结果")
            raise RuntimeError("蒙特卡洛模拟未产生任何有效结果")

        logger.info(
            f"蒙特卡洛模拟完成: {len(all_results)}/{num_simulations} 次成功, "
            f"耗时: {(time.time() - start_time):.1f}s"
        )

        averaged = self._aggregate_monte_carlo_results(all_results, len(all_results))
        return MonteCarloSimulationResult(results=averaged, config=config)

    def run_parallel_simulations(
        self,
        initial_infected_list: List[List[str]],
        config: Optional[MonteCarloConfig] = None,
        graph: Optional[ShelfGraph] = None,
        days: Optional[int] = None,
        seir_params: Optional[Dict[str, float]] = None,
        edge_params: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[callable] = None,
    ) -> List[MonteCarloSimulationResult]:
        """
        并行运行多个初始点的传播模拟
        
        参数:
            initial_infected_list: 多个初始感染组合列表
            config: MonteCarloConfig 配置对象（优先使用）
            graph: 书架图（如未提供 config 则必需）
            days: 模拟天数（如未提供 config 则必需）
            seir_params: SEIR模型参数（如未提供 config 则必需）
            edge_params: 边权重参数（如未提供 config 则必需）
            progress_callback: 进度回调函数 (completed, total) -> None
            
        返回:
            多组模拟结果列表
        """
        if config is not None:
            if graph is None and config.shelf_layout is not None:
                graph = ShelfGraph(config.shelf_layout, config.edge_params or {})
            days = days or config.days
            seir_params = seir_params or config.seir_params or {}
            edge_params = edge_params or config.edge_params or {}

        if graph is None or days is None or seir_params is None or edge_params is None:
            raise ValueError("必须提供 config 或 graph/days/seir_params/edge_params")

        if not initial_infected_list:
            return []

        logger.info(
            f"开始并行模拟: {len(initial_infected_list)} 个初始点, "
            f"天数={days}, max_workers={self._max_workers}"
        )

        executor = self._ensure_executor()
        shelf_layout = graph.shelf_layout
        start_time = time.time()

        futures = []
        for idx, initial_infected in enumerate(initial_infected_list):
            future = executor.submit(
                _run_single_simulation,
                shelf_layout=shelf_layout,
                edge_params=edge_params,
                initial_infected=initial_infected,
                days=days,
                seir_params=seir_params,
                simulation_id=idx,
            )
            futures.append(future)

        results_by_idx: Dict[int, List[SimulationResult]] = {}
        completed = 0

        for idx, future in enumerate(futures):
            try:
                result_dicts = future.result()
                results = [self._dict_to_simulation_result(d) for d in result_dicts]
                results_by_idx[idx] = results
                completed += 1
                if progress_callback:
                    try:
                        progress_callback(completed, len(initial_infected_list))
                    except Exception as e:
                        logger.warning(f"进度回调执行失败: {e}")
                logger.debug(f"并行模拟 {idx}/{len(initial_infected_list)} 完成")
            except Exception as e:
                logger.error(f"并行模拟任务 {idx} 失败: {e}")
                results_by_idx[idx] = []

        ordered_results = [
            MonteCarloSimulationResult(
                results=[self._simulation_result_to_averaged(r) for r in results_by_idx.get(idx, [])],
                config=config,
            )
            for idx in range(len(initial_infected_list))
        ]

        logger.info(
            f"并行模拟完成: {completed}/{len(initial_infected_list)} 个成功, "
            f"耗时: {(time.time() - start_time):.1f}s"
        )

        return ordered_results

    def _aggregate_monte_carlo_results(
        self,
        all_results: List[List[Dict[str, Any]]],
        num_samples: int,
    ) -> List[AveragedResult]:
        """
        聚合蒙特卡洛模拟结果
        对每个书架每天的状态计算平均值和标准差
        """
        import numpy as np

        grouped: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}

        for simulation_results in all_results:
            for result_dict in simulation_results:
                key = (result_dict["day"], result_dict["shelf_id"])
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(result_dict)

        averaged_results: List[AveragedResult] = []

        for key in sorted(grouped.keys()):
            day, shelf_id = key
            records = grouped[key]

            S_values = [r["S"] for r in records]
            E_values = [r["E"] for r in records]
            I_values = [r["I"] for r in records]
            R_values = [r["R"] for r in records]
            infection_prob_values = [r["infection_prob"] for r in records]

            spread_from = ""
            edge_weight = 0.0
            spread_counts: Dict[str, int] = {}
            for r in records:
                if r.get("spread_from"):
                    sf = r["spread_from"]
                    spread_counts[sf] = spread_counts.get(sf, 0) + 1
                    if r.get("edge_weight", 0) > edge_weight:
                        edge_weight = r["edge_weight"]
            if spread_counts:
                spread_from = max(spread_counts.items(), key=lambda x: x[1])[0]

            averaged = AveragedResult(
                day=day,
                shelf_id=shelf_id,
                S_mean=float(np.mean(S_values)),
                E_mean=float(np.mean(E_values)),
                I_mean=float(np.mean(I_values)),
                R_mean=float(np.mean(R_values)),
                S_std=float(np.std(S_values)),
                E_std=float(np.std(E_values)),
                I_std=float(np.std(I_values)),
                R_std=float(np.std(R_values)),
                infection_prob_mean=float(np.mean(infection_prob_values)),
                infection_prob_std=float(np.std(infection_prob_values)),
                spread_from=spread_from,
                edge_weight=edge_weight,
                num_samples=num_samples,
            )
            averaged_results.append(averaged)

        logger.info(f"聚合完成: {len(averaged_results)} 个平均结果点")
        return averaged_results

    @staticmethod
    def _dict_to_simulation_result(result_dict: Dict[str, Any]) -> SimulationResult:
        """将字典转换回 SimulationResult 对象"""
        return SimulationResult(
            day=result_dict["day"],
            shelf_id=result_dict["shelf_id"],
            state=SEIRState(
                S=result_dict["S"],
                E=result_dict["E"],
                I=result_dict["I"],
                R=result_dict["R"],
            ),
            spread_from=result_dict.get("spread_from", ""),
            edge_weight=result_dict.get("edge_weight", 0.0),
        )

    @staticmethod
    def _simulation_result_to_averaged(sim_result: SimulationResult) -> AveragedResult:
        """将 SimulationResult 转换为 AveragedResult（单个模拟结果）"""
        return AveragedResult(
            day=sim_result.day,
            shelf_id=sim_result.shelf_id,
            S_mean=sim_result.state.S,
            E_mean=sim_result.state.E,
            I_mean=sim_result.state.I,
            R_mean=sim_result.state.R,
            S_std=0.0,
            E_std=0.0,
            I_std=0.0,
            R_std=0.0,
            infection_prob_mean=sim_result.state.infection_prob,
            infection_prob_std=0.0,
            spread_from=sim_result.spread_from,
            edge_weight=sim_result.edge_weight,
            num_samples=1,
        )

    def run_monte_carlo_simulation_async(
        self,
        graph: ShelfGraph,
        initial_infected: List[str],
        days: int,
        seir_params: Dict[str, float],
        edge_params: Dict[str, Any],
        num_simulations: int = 100,
        callback: Optional[callable] = None,
        error_callback: Optional[callable] = None,
    ):
        """
        异步版本的蒙特卡洛模拟（非阻塞）
        返回 Future 对象
        """
        executor = self._ensure_executor()
        shelf_layout = graph.shelf_layout

        future = executor.submit(
            self.run_monte_carlo_simulation,
            graph=graph,
            initial_infected=initial_infected,
            days=days,
            seir_params=seir_params,
            edge_params=edge_params,
            num_simulations=num_simulations,
        )

        def _done(fut):
            try:
                result = fut.result()
                if callback:
                    callback(result)
            except Exception as e:
                if error_callback:
                    error_callback(e)
                logger.error(f"异步蒙特卡洛模拟失败: {e}")

        future.add_done_callback(_done)
        return future

    def get_stats(self) -> Dict[str, Any]:
        """获取 Worker 状态"""
        return {
            "max_workers": self._max_workers,
            "is_running": self._running,
        }
