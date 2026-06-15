"""
基础任务类
为未来 Celery 集成预留兼容接口

设计说明:
- 不实际导入 celery 包，避免未安装时的依赖问题
- 使用装饰器模式预留 Celery 兼容接口
- 保持与现有代码的完全向后兼容
- 未来迁移到 Celery 时只需修改底层实现
"""
import logging
import asyncio
import functools
from typing import Dict, Any, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class TaskResult:
    """任务结果包装"""
    task_id: str
    status: str = "PENDING"
    result: Any = None
    error: Optional[Exception] = None
    date_done: Optional[str] = None
    traceback: Optional[str] = None

    def ready(self) -> bool:
        return self.status in ("SUCCESS", "FAILURE")

    def successful(self) -> bool:
        return self.status == "SUCCESS"

    def failed(self) -> bool:
        return self.status == "FAILURE"

    def get(self, timeout: Optional[float] = None, propagate: bool = True) -> Any:
        if self.status == "FAILURE" and propagate and self.error:
            raise self.error
        return self.result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": str(self.error) if self.error else None,
            "date_done": self.date_done,
        }


@dataclass
class TaskConfig:
    """任务配置"""
    name: str
    max_retries: int = 3
    default_retry_delay: int = 60
    soft_time_limit: Optional[int] = None
    time_limit: Optional[int] = None
    ignore_result: bool = False
    queue: str = "default"
    routing_key: Optional[str] = None


class BaseTask(Generic[T, R]):
    """
    基础任务类（预留 Celery 兼容接口）
    
    设计说明:
    - 模拟 Celery Task 的核心接口
    - 不依赖实际的 Celery 包
    - 使用装饰器模式 @app.task 风格的接口预留
    - 未来迁移到 Celery 时只需修改底层实现
    
    预留接口与 Celery 兼容的方法:
    - delay(*args, **kwargs) - 异步执行任务
    - apply_async(args, kwargs, **options) - 带选项的异步执行
    - apply(args, kwargs) - 同步执行
    - retry() - 重试任务
    """

    _name: str = ""
    _config: TaskConfig = TaskConfig(name="base_task")
    _registry: Dict[str, "BaseTask"] = {}

    def __init__(self, task_config: Optional[TaskConfig] = None):
        if task_config:
            self._config = task_config
            self._name = task_config.name
        self._results: Dict[str, TaskResult] = {}
        self._running = False
        self._async_results: Dict[str, asyncio.Future] = {}

    @classmethod
    def register(cls, task_name: str, task: "BaseTask") -> None:
        """注册任务到全局注册表"""
        cls._registry[task_name] = task
        logger.debug(f"任务已注册: {task_name}")

    @classmethod
    def get_task(cls, task_name: str) -> Optional["BaseTask"]:
        """从注册表获取任务"""
        return cls._registry.get(task_name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> TaskConfig:
        return self._config

    def run(self, *args, **kwargs) -> R:
        """
        任务执行逻辑
        子类必须重写此方法
        """
        raise NotImplementedError("子类必须实现 run() 方法")

    def __call__(self, *args, **kwargs) -> R:
        """同步调用任务"""
        return self.run(*args, **kwargs)

    def delay(self, *args, **kwargs) -> TaskResult:
        """
        异步执行任务（Celery 兼容接口）
        
        说明: 当前实现为本地异步执行，未来迁移到 Celery 时无需修改调用方
        """
        return self.apply_async(args=args, kwargs=kwargs)

    def apply_async(
        self,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        countdown: Optional[int] = None,
        eta: Optional[str] = None,
        expires: Optional[int] = None,
        retry: bool = False,
        queue: Optional[str] = None,
        **options,
    ) -> TaskResult:
        """
        带选项的异步执行（Celery 兼容接口）
        
        说明: 当前实现仅模拟部分参数，未来迁移到 Celery 时完整支持
        """
        task_id = str(uuid.uuid4())
        args = args or ()
        kwargs = kwargs or {}

        result = TaskResult(task_id=task_id, status="PENDING")
        self._results[task_id] = result

        async def _execute_async():
            try:
                if countdown:
                    await asyncio.sleep(countdown)

                loop = asyncio.get_running_loop()
                task_result = await loop.run_in_executor(
                    None,
                    functools.partial(self.run, *args, **kwargs),
                )

                result.status = "SUCCESS"
                result.result = task_result
                result.date_done = datetime.now().isoformat()

                logger.debug(f"任务 {self._name}[{task_id}] 执行成功")
                return task_result

            except Exception as e:
                result.status = "FAILURE"
                result.error = e
                result.date_done = datetime.now().isoformat()
                logger.error(f"任务 {self._name}[{task_id}] 执行失败: {e}")
                raise

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.create_task(_execute_async())
                self._async_results[task_id] = future
            else:
                loop.run_until_complete(_execute_async())
        except RuntimeError:
            import threading
            thread = threading.Thread(target=self._run_sync, args=(args, kwargs, result))
            thread.daemon = True
            thread.start()

        return result

    def _run_sync(self, args: tuple, kwargs: Dict[str, Any], result: TaskResult) -> None:
        """同步线程执行包装"""
        try:
            task_result = self.run(*args, **kwargs)
            result.status = "SUCCESS"
            result.result = task_result
            result.date_done = datetime.now().isoformat()
        except Exception as e:
            result.status = "FAILURE"
            result.error = e
            result.date_done = datetime.now().isoformat()

    def apply(self, args: Optional[tuple] = None, kwargs: Optional[Dict[str, Any]] = None) -> TaskResult:
        """
        同步执行任务（Celery 兼容接口）
        """
        args = args or ()
        kwargs = kwargs or {}
        task_id = str(uuid.uuid4())

        result = TaskResult(task_id=task_id, status="PENDING")
        self._results[task_id] = result

        try:
            task_result = self.run(*args, **kwargs)
            result.status = "SUCCESS"
            result.result = task_result
            result.date_done = datetime.now().isoformat()
        except Exception as e:
            result.status = "FAILURE"
            result.error = e
            result.date_done = datetime.now().isoformat()

        return result

    def retry(
        self,
        exc: Optional[Exception] = None,
        countdown: Optional[int] = None,
        max_retries: Optional[int] = None,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        重试任务（Celery 兼容接口）
        
        说明: 当前实现为简单重试逻辑，未来迁移到 Celery 时完整支持
        """
        if countdown is None:
            countdown = self._config.default_retry_delay

        max_retries = max_retries or self._config.max_retries

        logger.warning(
            f"任务 {self._name} 准备重试 (exc={exc}, "
            f"countdown={countdown}s, max_retries={max_retries})"
        )

        self.apply_async(
            args=args,
            kwargs=kwargs,
            countdown=countdown,
        )

    def AsyncResult(self, task_id: str) -> TaskResult:
        """
        获取任务异步结果（Celery 兼容接口）
        """
        return self._results.get(task_id, TaskResult(task_id=task_id, status="PENDING"))

    def get_result(self, task_id: str) -> TaskResult:
        """获取任务结果"""
        return self._results.get(task_id, TaskResult(task_id=task_id, status="PENDING"))

    def forget_result(self, task_id: str) -> None:
        """清除任务结果"""
        if task_id in self._results:
            del self._results[task_id]
        if task_id in self._async_results:
            future = self._async_results.pop(task_id)
            if not future.done():
                future.cancel()

    def start(self) -> None:
        """启动任务处理（预留 Celery worker 启动接口）"""
        if self._running:
            return
        self._running = True
        logger.info(f"任务 {self._name} 已启动")

    def stop(self) -> None:
        """停止任务处理（预留 Celery worker 停止接口）"""
        if not self._running:
            return
        self._running = False

        for task_id, future in list(self._async_results.items()):
            if not future.done():
                future.cancel()
        self._async_results.clear()

        logger.info(f"任务 {self._name} 已停止")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def task(*args, **kwargs):
    """
    装饰器：定义任务（预留 Celery @app.task 风格接口）
    
    用法:
        @task(name="my_task")
        def my_task(*args, **kwargs):
            ...
    
    说明: 当前实现返回 BaseTask 包装对象，未来迁移到 Celery 时无需修改代码
    """
    def decorator(func: Callable[..., R]) -> BaseTask:
        task_name = kwargs.get("name") or func.__name__
        config = TaskConfig(
            name=task_name,
            max_retries=kwargs.get("max_retries", 3),
            default_retry_delay=kwargs.get("default_retry_delay", 60),
        )

        class _FunctionTask(BaseTask):
            def run(self, *task_args, **task_kwargs) -> R:
                return func(*task_args, **task_kwargs)

        task_instance = _FunctionTask(task_config=config)
        BaseTask.register(task_name, task_instance)
        return task_instance

    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])

    return decorator


class TaskApp:
    """
    任务应用类（预留 Celery Celery 类接口）
    
    说明: 模拟 Celery 的 app 实例，提供 task 装饰器和 send_task 接口
    """

    def __init__(self, name: str = "app", broker: Optional[str] = None, backend: Optional[str] = None):
        self.name = name
        self.broker = broker
        self.backend = backend
        self._tasks: Dict[str, BaseTask] = {}
        logger.info(f"TaskApp[{name}] 初始化完成（预留 Celery 接口）")

    def task(self, *args, **kwargs) -> Callable:
        """
        任务装饰器（Celery 兼容接口）
        
        用法:
            @app.task
            def my_task():
                ...
            
            @app.task(name="custom_name", max_retries=5)
            def my_task():
                ...
        """
        def decorator(func: Callable[..., R]) -> BaseTask:
            task_name = kwargs.get("name") or func.__name__
            config = TaskConfig(
                name=task_name,
                max_retries=kwargs.get("max_retries", 3),
                default_retry_delay=kwargs.get("default_retry_delay", 60),
                queue=kwargs.get("queue", "default"),
            )

            class _FunctionTask(BaseTask):
                def run(self, *task_args, **task_kwargs) -> R:
                    return func(*task_args, **task_kwargs)

            task_instance = _FunctionTask(task_config=config)
            self._tasks[task_name] = task_instance
            BaseTask.register(task_name, task_instance)
            return task_instance

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def send_task(
        self,
        name: str,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        **options,
    ) -> TaskResult:
        """
        发送任务到队列（Celery 兼容接口）
        """
        if name not in self._tasks:
            raise KeyError(f"任务 {name} 未注册")

        task_instance = self._tasks[name]
        return task_instance.apply_async(args=args, kwargs=kwargs, **options)

    def register_task(self, task_instance: BaseTask) -> None:
        """注册任务实例"""
        self._tasks[task_instance.name] = task_instance
        BaseTask.register(task_instance.name, task_instance)

    def get_tasks(self) -> Dict[str, BaseTask]:
        """获取所有已注册任务"""
        return dict(self._tasks)
