"""
Celery 任务模块（预留）
为未来集成 Celery 分布式任务队列预留接口

设计说明:
- 不实际依赖 celery 包
- 使用装饰器模式预留 Celery 兼容接口
- 包含资源调度优化等计算密集任务
"""

from .base_task import (
    BaseTask,
    TaskResult,
    TaskConfig,
    TaskApp,
    task,
)

from .resource_scheduling import (
    ResourceSchedulingTask,
    ShelfAllocation,
    OptimizationConstraints,
    OptimizationResult,
    get_resource_scheduling_task,
)

__all__ = [
    "BaseTask",
    "TaskResult",
    "TaskConfig",
    "TaskApp",
    "task",
    "ResourceSchedulingTask",
    "ShelfAllocation",
    "OptimizationConstraints",
    "OptimizationResult",
    "get_resource_scheduling_task",
]
