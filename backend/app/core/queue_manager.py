"""
队列管理器
支持asyncio.Queue（同进程异步通信）和multiprocessing.Queue（跨进程通信）
"""
import asyncio
import logging
import queue
import multiprocessing
from typing import Dict, Any, Optional, TypeVar, Generic, Union
from dataclasses import dataclass, field

from .messages import Message, deserialize_message, serialize_message

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Message)


@dataclass
class QueueStats:
    """队列统计信息"""
    name: str
    size: int = 0
    max_size: int = 0
    total_put: int = 0
    total_get: int = 0
    total_dropped: int = 0


class AsyncQueueWrapper(Generic[T]):
    """asyncio.Queue包装器，添加统计和背压机制"""

    def __init__(self, name: str, maxsize: int = 0):
        self.name = name
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self.max_size = maxsize
        self._stats = QueueStats(name=name, max_size=maxsize)
        self._lock = asyncio.Lock()

    async def put(self, item: T, timeout: Optional[float] = None) -> bool:
        """异步放入消息，队列满时等待或丢弃最旧消息"""
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                    self._stats.total_dropped += 1
                    logger.warning(f"队列 {self.name} 已满，丢弃最旧消息")
                except asyncio.QueueEmpty:
                    pass

            if timeout is not None:
                await asyncio.wait_for(self._queue.put(item), timeout=timeout)
            else:
                await self._queue.put(item)

            async with self._lock:
                self._stats.total_put += 1
                self._stats.size = self._queue.qsize()
            return True
        except asyncio.TimeoutError:
            logger.warning(f"队列 {self.name} 放入超时")
            return False
        except Exception as e:
            logger.error(f"队列 {self.name} 放入失败: {e}")
            return False

    def put_nowait(self, item: T) -> bool:
        """非阻塞放入，队列满时丢弃最旧消息"""
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                    self._stats.total_dropped += 1
                except asyncio.QueueEmpty:
                    pass
            self._queue.put_nowait(item)
            self._stats.total_put += 1
            self._stats.size = self._queue.qsize()
            return True
        except Exception as e:
            logger.error(f"队列 {self.name} 非阻塞放入失败: {e}")
            return False

    async def get(self, timeout: Optional[float] = None) -> Optional[T]:
        """异步获取消息"""
        try:
            if timeout is not None:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            else:
                item = await self._queue.get()
            async with self._lock:
                self._stats.total_get += 1
                self._stats.size = self._queue.qsize()
            return item
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"队列 {self.name} 获取失败: {e}")
            return None

    def get_nowait(self) -> Optional[T]:
        """非阻塞获取"""
        try:
            item = self._queue.get_nowait()
            self._stats.total_get += 1
            self._stats.size = self._queue.qsize()
            return item
        except asyncio.QueueEmpty:
            return None
        except Exception as e:
            logger.error(f"队列 {self.name} 非阻塞获取失败: {e}")
            return None

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def get_stats(self) -> QueueStats:
        self._stats.size = self._queue.qsize()
        return self._stats


class ProcessQueueWrapper(Generic[T]):
    """multiprocessing.Queue包装器，用于跨进程通信"""

    def __init__(self, name: str, maxsize: int = 0):
        self.name = name
        self._queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=maxsize)
        self.max_size = maxsize
        self._stats = QueueStats(name=name, max_size=maxsize)
        self._lock = multiprocessing.Lock()

    def put(self, item: T, timeout: Optional[float] = None) -> bool:
        """跨进程放入消息"""
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                    with self._lock:
                        self._stats.total_dropped += 1
                    logger.warning(f"进程队列 {self.name} 已满，丢弃最旧消息")
                except queue.Empty:
                    pass

            data = serialize_message(item)
            if timeout is not None:
                self._queue.put(data, timeout=timeout)
            else:
                self._queue.put(data)

            with self._lock:
                self._stats.total_put += 1
            return True
        except Exception as e:
            logger.error(f"进程队列 {self.name} 放入失败: {e}")
            return False

    def get(self, timeout: Optional[float] = None) -> Optional[T]:
        """跨进程获取消息"""
        try:
            if timeout is not None:
                data = self._queue.get(timeout=timeout)
            else:
                data = self._queue.get()
            msg = deserialize_message(data)
            with self._lock:
                self._stats.total_get += 1
            return msg
        except queue.Empty:
            return None
        except Exception as e:
            logger.error(f"进程队列 {self.name} 获取失败: {e}")
            return None

    def qsize(self) -> int:
        try:
            return self._queue.qsize()
        except NotImplementedError:
            return 0

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def close(self) -> None:
        self._queue.close()
        self._queue.join_thread()

    def get_stats(self) -> QueueStats:
        self._stats.size = self.qsize()
        return self._stats


QueueType = Union[AsyncQueueWrapper, ProcessQueueWrapper]


class QueueManager:
    """队列管理器，统一管理所有通信队列"""

    def __init__(self):
        self._async_queues: Dict[str, AsyncQueueWrapper] = {}
        self._process_queues: Dict[str, ProcessQueueWrapper] = {}
        self._logger = logging.getLogger(__name__)

    def create_async_queue(self, name: str, maxsize: int = 0) -> AsyncQueueWrapper:
        """创建异步队列"""
        if name in self._async_queues:
            return self._async_queues[name]
        queue = AsyncQueueWrapper[T](name, maxsize)
        self._async_queues[name] = queue
        self._logger.info(f"创建异步队列: {name}, maxsize={maxsize}")
        return queue

    def create_process_queue(self, name: str, maxsize: int = 0) -> ProcessQueueWrapper:
        """创建跨进程队列"""
        if name in self._process_queues:
            return self._process_queues[name]
        queue = ProcessQueueWrapper[T](name, maxsize)
        self._process_queues[name] = queue
        self._logger.info(f"创建进程队列: {name}, maxsize={maxsize}")
        return queue

    def get_async_queue(self, name: str) -> Optional[AsyncQueueWrapper]:
        """获取异步队列"""
        return self._async_queues.get(name)

    def get_process_queue(self, name: str) -> Optional[ProcessQueueWrapper]:
        """获取跨进程队列"""
        return self._process_queues.get(name)

    def get_queue(self, name: str) -> Optional[QueueType]:
        """获取队列（先查异步，再查进程）"""
        if name in self._async_queues:
            return self._async_queues[name]
        if name in self._process_queues:
            return self._process_queues[name]
        return None

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有队列统计"""
        stats = {
            "async_queues": {},
            "process_queues": {},
        }
        for name, q in self._async_queues.items():
            s = q.get_stats()
            stats["async_queues"][name] = {
                "size": s.size,
                "max_size": s.max_size,
                "total_put": s.total_put,
                "total_get": s.total_get,
                "total_dropped": s.total_dropped,
            }
        for name, q in self._process_queues.items():
            s = q.get_stats()
            stats["process_queues"][name] = {
                "size": s.size,
                "max_size": s.max_size,
                "total_put": s.total_put,
                "total_get": s.total_get,
                "total_dropped": s.total_dropped,
            }
        return stats

    async def flush_all_async(self) -> None:
        """清空所有异步队列"""
        for name, q in self._async_queues.items():
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
            self._logger.info(f"清空异步队列: {name}")

    async def put(self, queue_name: str, item: T, timeout: Optional[float] = None) -> bool:
        """向队列放入数据（自动识别队列类型）"""
        queue = self.get_queue(queue_name)
        if queue is None:
            self._logger.error(f"队列不存在: {queue_name}")
            return False
        if isinstance(queue, AsyncQueueWrapper):
            return await queue.put(item, timeout)
        else:
            return queue.put(item, timeout)

    def put_sync(self, queue_name: str, item: T, timeout: Optional[float] = None) -> bool:
        """同步向队列放入数据（自动识别队列类型）"""
        queue = self.get_queue(queue_name)
        if queue is None:
            self._logger.error(f"队列不存在: {queue_name}")
            return False
        if isinstance(queue, AsyncQueueWrapper):
            raise RuntimeError(f"队列 {queue_name} 是异步队列，请使用 put 方法")
        return queue.put(item, timeout)

    async def get(self, queue_name: str, timeout: Optional[float] = None) -> Optional[T]:
        """从队列获取数据（自动识别队列类型）"""
        queue = self.get_queue(queue_name)
        if queue is None:
            self._logger.error(f"队列不存在: {queue_name}")
            return None
        if isinstance(queue, AsyncQueueWrapper):
            return await queue.get(timeout)
        else:
            return queue.get(timeout)

    def get_sync(self, queue_name: str, timeout: Optional[float] = None) -> Optional[T]:
        """同步从队列获取数据（自动识别队列类型）"""
        queue = self.get_queue(queue_name)
        if queue is None:
            self._logger.error(f"队列不存在: {queue_name}")
            return None
        if isinstance(queue, AsyncQueueWrapper):
            raise RuntimeError(f"队列 {queue_name} 是异步队列，请使用 get 方法")
        return queue.get(timeout)

    def close_all_process_queues(self) -> None:
        """关闭所有跨进程队列"""
        for name, q in self._process_queues.items():
            try:
                q.close()
                self._logger.info(f"关闭进程队列: {name}")
            except Exception as e:
                self._logger.error(f"关闭进程队列 {name} 失败: {e}")


queue_manager = QueueManager()
