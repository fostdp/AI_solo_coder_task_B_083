"""
计算密集任务 Worker 模块
提供并行计算和蒙特卡洛模拟功能
"""

from .base_worker import (
    BaseWorker,
    WorkerTask,
    WorkerProgress,
    WorkerStats,
)

from .worker_pool import (
    WorkerPool,
    PoolConfig,
    PoolStats,
)

from .spread_worker import (
    SpreadSimulationWorker,
    MonteCarloConfig,
    AveragedResult,
    MonteCarloSimulationResult,
    _run_single_simulation,
    _run_single_simulation_by_graph,
)

__all__ = [
    "BaseWorker",
    "WorkerTask",
    "WorkerProgress",
    "WorkerStats",
    "WorkerPool",
    "PoolConfig",
    "PoolStats",
    "SpreadSimulationWorker",
    "MonteCarloConfig",
    "AveragedResult",
    "MonteCarloSimulationResult",
    "_run_single_simulation",
    "_run_single_simulation_by_graph",
]
