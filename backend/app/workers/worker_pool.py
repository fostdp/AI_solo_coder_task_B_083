"""
Worker 池管理
管理多个 ProcessPoolExecutor，支持不同任务类型资源隔离
"""
import logging
import os
import time
import atexit
from typing import Dict, Any, Optional, Callable, TypeVar, Generic
from concurrent.futures import ProcessPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class PoolStats:
    """池统计信息"""
    pool_name: str
    max_workers: int
    active_tasks: int = 0
    pending_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_runtime_ms: float = 0.0
    last_task_time: Optional[str] = None


@dataclass
class PoolConfig:
    """池配置"""
    name: str
    max_workers: Optional[int] = None
    max_tasks_per_child: Optional[int] = None
    init_timeout: int = 60
    shutdown_timeout: int = 10


class WorkerPool(Generic[T, R]):
    """
    Worker 池管理类
    为不同任务类型（如传播模拟、优化算法）提供独立的进程池，实现资源隔离
    
    设计说明:
    - 不同任务类型使用不同的进程池，避免资源竞争
    - 支持动态调整进程数
    - 提供统一的提交和监控接口
    - 支持优雅关闭
    """

    _instances: Dict[str, "WorkerPool"] = {}
    _default_configs: Dict[str, PoolConfig] = {
        "spread": PoolConfig(name="spread", max_workers=None),
        "optimization": PoolConfig(name="optimization", max_workers=2),
    }

    def __init__(self, pool_config: PoolConfig):
        self._config = pool_config
        self._name = pool_config.name
        self._max_workers = pool_config.max_workers or max(1, os.cpu_count() or 1)
        self._executor: Optional[ProcessPoolExecutor] = None
        self._stats = PoolStats(pool_name=self._name, max_workers=self._max_workers)
        self._lock = __import__("threading").Lock()
        self._running = False

        logger.info(f"WorkerPool[{self._name}] 创建完成，max_workers={self._max_workers}")

    @classmethod
    def get_pool(cls, pool_type: str) -> "WorkerPool":
        """
        获取指定类型的 Worker 池（单例模式）
        """
        if pool_type not in cls._instances:
            config = cls._default_configs.get(
                pool_type,
                PoolConfig(name=pool_type, max_workers=None)
            )
            cls._instances[pool_type] = cls(config)
        return cls._instances[pool_type]

    @classmethod
    def register_config(cls, pool_type: str, config: PoolConfig) -> None:
        """注册自定义池配置"""
        cls._default_configs[pool_type] = config
        logger.info(f"WorkerPool 配置已注册: {pool_type}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def is_running(self) -> bool:
        return self._running and self._executor is not None

    def start(self) -> None:
        """启动进程池"""
        if self._running:
            return

        with self._lock:
            if self._running:
                return

            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                max_tasks_per_child=self._config.max_tasks_per_child,
            )
            self._running = True
            logger.info(f"WorkerPool[{self._name}] 已启动，max_workers={self._max_workers}")

    def shutdown(self, wait: bool = True) -> None:
        """关闭进程池"""
        if not self._running:
            return

        with self._lock:
            if not self._running:
                return

            if self._executor:
                self._executor.shutdown(wait=wait)
                self._executor = None

            self._running = False
            logger.info(f"WorkerPool[{self._name}] 已关闭")

    def restart(self) -> None:
        """重启进程池"""
        self.shutdown(wait=True)
        self.start()
        logger.info(f"WorkerPool[{self._name}] 已重启")

    def resize(self, new_max_workers: int) -> None:
        """
        调整进程池大小
        注意：这会重启进程池
        """
        if new_max_workers <= 0:
            raise ValueError(f"max_workers 必须大于0，当前值: {new_max_workers}")

        if new_max_workers == self._max_workers:
            return

        logger.info(f"WorkerPool[{self._name}] 调整大小: {self._max_workers} -> {new_max_workers}")
        self._max_workers = new_max_workers
        self._stats.max_workers = new_max_workers
        self.restart()

    def submit(
        self,
        func: Callable[..., R],
        *args,
        callback: Optional[Callable[[Future], None]] = None,
        error_callback: Optional[Callable[[Future], None]] = None,
        **kwargs,
    ) -> Future:
        """
        提交任务到进程池
        
        参数:
            func: 要执行的函数（必须是模块级函数，支持 pickle 序列化）
            *args: 函数位置参数
            callback: 成功回调
            error_callback: 错误回调
            **kwargs: 函数关键字参数
            
        返回:
            Future 对象
        """
        if not self._running:
            self.start()

        assert self._executor is not None, "进程池未初始化"

        with self._lock:
            self._stats.pending_tasks += 1

        start_time = time.time()
        future = self._executor.submit(func, *args, **kwargs)

        def _done_callback(fut: Future):
            try:
                with self._lock:
                    self._stats.pending_tasks -= 1
                    runtime_ms = (time.time() - start_time) * 1000
                    self._stats.total_runtime_ms += runtime_ms
                    self._stats.last_task_time = datetime.now().isoformat()

                    if fut.exception() is not None:
                        self._stats.failed_tasks += 1
                        logger.error(
                            f"WorkerPool[{self._name}] 任务失败: {func.__name__}, "
                            f"耗时: {runtime_ms:.1f}ms, 错误: {fut.exception()}"
                        )
                        if error_callback:
                            try:
                                error_callback(fut)
                            except Exception as e:
                                logger.error(f"错误回调执行失败: {e}")
                    else:
                        self._stats.completed_tasks += 1
                        logger.debug(
                            f"WorkerPool[{self._name}] 任务完成: {func.__name__}, "
                            f"耗时: {runtime_ms:.1f}ms"
                        )
                        if callback:
                            try:
                                callback(fut)
                            except Exception as e:
                                logger.error(f"成功回调执行失败: {e}")

            except Exception as e:
                logger.error(f"任务回调处理异常: {e}")

        future.add_done_callback(_done_callback)
        return future

    def map(
        self,
        func: Callable[..., R],
        iterable,
        timeout: Optional[float] = None,
        chunksize: int = 1,
    ):
        """
        批量提交任务并获取结果
        """
        if not self._running:
            self.start()

        assert self._executor is not None, "进程池未初始化"

        total_tasks = len(list(iterable)) if hasattr(iterable, "__len__") else 0
        with self._lock:
            self._stats.pending_tasks += total_tasks

        start_time = time.time()
        try:
            results = self._executor.map(
                func,
                iterable,
                timeout=timeout,
                chunksize=chunksize,
            )
            results_list = list(results)

            with self._lock:
                self._stats.pending_tasks -= total_tasks
                self._stats.completed_tasks += total_tasks
                runtime_ms = (time.time() - start_time) * 1000
                self._stats.total_runtime_ms += runtime_ms
                self._stats.last_task_time = datetime.now().isoformat()

            return results_list

        except Exception as e:
            with self._lock:
                self._stats.pending_tasks -= total_tasks
                self._stats.failed_tasks += total_tasks
            logger.error(f"WorkerPool[{self._name}] map 执行失败: {e}")
            raise

    def get_stats(self) -> Dict[str, Any]:
        """获取池统计信息"""
        with self._lock:
            stats_dict = self._stats.__dict__.copy()
            stats_dict["is_running"] = self._running
            return stats_dict

    def reset_stats(self) -> None:
        """重置统计信息"""
        with self._lock:
            self._stats = PoolStats(pool_name=self._name, max_workers=self._max_workers)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)

    @classmethod
    def shutdown_all(cls, wait: bool = True) -> None:
        """关闭所有进程池"""
        for pool in cls._instances.values():
            pool.shutdown(wait=wait)
        cls._instances.clear()
        logger.info("所有 WorkerPool 已关闭")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有池的统计信息"""
        return {name: pool.get_stats() for name, pool in cls._instances.items()}


atexit.register(WorkerPool.shutdown_all)
