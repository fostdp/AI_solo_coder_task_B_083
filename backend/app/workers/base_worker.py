"""
Worker 基类
定义计算密集任务 Worker 的抽象接口
"""
import logging
import asyncio
import queue
import threading
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable, Generic, TypeVar
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class WorkerTask:
    """Worker 任务包装"""
    task_id: str
    args: tuple
    kwargs: Dict[str, Any]
    callback: Optional[Callable[[Any], None]] = None
    error_callback: Optional[Callable[[Exception], None]] = None
    submitted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[Exception] = None
    status: str = "pending"


@dataclass
class WorkerProgress:
    """任务进度追踪"""
    task_id: str
    total: int = 0
    completed: int = 0
    current: int = 0
    percent: float = 0.0
    message: str = ""
    started_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class WorkerStats:
    """Worker 统计信息"""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    total_runtime_ms: float = 0.0
    last_task_time: Optional[str] = None


class BaseWorker(ABC, Generic[T, R]):
    """
    计算密集任务 Worker 抽象基类
    提供任务队列管理、进度追踪、结果聚合等通用功能
    """

    def __init__(self, max_workers: Optional[int] = None):
        self._max_workers = max_workers
        self._task_queue: "queue.Queue[WorkerTask]" = queue.Queue()
        self._progress_store: Dict[str, WorkerProgress] = {}
        self._result_store: Dict[str, Any] = {}
        self._stats = WorkerStats()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def max_workers(self) -> int:
        return self._max_workers or 1

    @abstractmethod
    def _execute_task(self, *args, **kwargs) -> R:
        """
        执行具体任务的抽象方法
        子类必须实现此方法
        """
        raise NotImplementedError

    def submit(self, *args, **kwargs) -> str:
        """
        提交任务到队列
        返回任务ID
        """
        import uuid
        task_id = str(uuid.uuid4())

        callback = kwargs.pop("callback", None)
        error_callback = kwargs.pop("error_callback", None)

        task = WorkerTask(
            task_id=task_id,
            args=args,
            kwargs=kwargs,
            callback=callback,
            error_callback=error_callback,
        )

        self._task_queue.put(task)
        self._stats.pending_tasks += 1
        self._progress_store[task_id] = WorkerProgress(
            task_id=task_id,
            started_at=datetime.now().isoformat(),
        )

        logger.debug(f"任务已提交: {task_id}")
        return task_id

    def get_progress(self, task_id: str) -> Optional[WorkerProgress]:
        """获取任务进度"""
        return self._progress_store.get(task_id)

    def get_result(self, task_id: str) -> Optional[Any]:
        """获取任务结果"""
        return self._result_store.get(task_id)

    def get_stats(self) -> Dict[str, Any]:
        """获取 Worker 统计信息"""
        return {
            "stats": self._stats.__dict__,
            "max_workers": self._max_workers,
            "queue_size": self._task_queue.qsize(),
        }

    def _update_progress(self, task_id: str, current: int, total: int, message: str = "") -> None:
        """更新任务进度"""
        with self._lock:
            if task_id in self._progress_store:
                progress = self._progress_store[task_id]
                progress.current = current
                progress.total = total
                progress.completed = current
                progress.percent = (current / total * 100) if total > 0 else 0.0
                progress.message = message
                progress.updated_at = datetime.now().isoformat()

    def _aggregate_results(self, results: List[Any]) -> Any:
        """
        聚合多个结果
        默认简单返回列表，子类可重写
        """
        return results

    def _process_queue(self) -> None:
        """后台处理循环"""
        logger.info(f"{self.__class__.__name__} 处理线程已启动")
        while self._running:
            try:
                task = self._task_queue.get(timeout=1.0)
                if task is None:
                    continue

                with self._lock:
                    self._stats.pending_tasks -= 1
                    self._stats.running_tasks += 1

                task.status = "running"
                start_time = datetime.now()

                try:
                    logger.debug(f"开始执行任务: {task.task_id}")
                    result = self._execute_task(*task.args, **task.kwargs)

                    with self._lock:
                        task.result = result
                        task.completed_at = datetime.now().isoformat()
                        task.status = "completed"
                        self._result_store[task.task_id] = result
                        self._stats.completed_tasks += 1
                        self._stats.running_tasks -= 1
                        self._stats.last_task_time = task.completed_at
                        self._stats.total_runtime_ms += (
                            datetime.now() - start_time
                        ).total_seconds() * 1000

                        if task.task_id in self._progress_store:
                            progress = self._progress_store[task.task_id]
                            progress.percent = 100.0
                            progress.completed = progress.total if progress.total > 0 else 1
                            progress.updated_at = task.completed_at

                    if task.callback:
                        try:
                            task.callback(result)
                        except Exception as e:
                            logger.error(f"任务回调执行失败 {task.task_id}: {e}")

                    logger.debug(f"任务完成: {task.task_id}")

                except Exception as e:
                    with self._lock:
                        task.error = e
                        task.completed_at = datetime.now().isoformat()
                        task.status = "failed"
                        self._stats.failed_tasks += 1
                        self._stats.running_tasks -= 1

                    if task.error_callback:
                        try:
                            task.error_callback(e)
                        except Exception as cb_e:
                            logger.error(f"任务错误回调执行失败 {task.task_id}: {cb_e}")

                    logger.error(f"任务执行失败 {task.task_id}: {e}")

                self._task_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker 处理循环异常: {e}")

    def start(self) -> None:
        """启动 Worker"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            daemon=True,
            name=f"{self.__class__.__name__}-worker",
        )
        self._worker_thread.start()
        logger.info(f"{self.__class__.__name__} 已启动，max_workers={self._max_workers}")

    def stop(self) -> None:
        """停止 Worker"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            self._worker_thread = None
        logger.info(f"{self.__class__.__name__} 已停止")

    async def wait_for_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        异步等待任务完成并返回结果
        """
        start_time = datetime.now()
        while True:
            if task_id in self._result_store:
                return self._result_store[task_id]

            task = next(
                (t for t in [task for task in []] if t.task_id == task_id),
                None,
            )
            if task and task.status == "failed":
                raise task.error

            if timeout and (datetime.now() - start_time).total_seconds() > timeout:
                raise TimeoutError(f"任务 {task_id} 超时")

            await asyncio.sleep(0.1)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
