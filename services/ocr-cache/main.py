"""
OCR Cache 独立服务
负责 OCR 文本提取、元数据解析与缓存管理

架构：
- 独立进程，不依赖主服务
- 内存模拟 Redis，支持 TTL 缓存
- 每晚 2:00 定时批处理
- FastAPI HTTP 接口
- NamedConnectionPool 连接 ClickHouse
"""
import asyncio
import logging
import math
import random
import queue
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from clickhouse_driver import Client
import uvicorn

from config import config

logger = logging.getLogger(__name__)


# ============================================================================
# 复用算法类 - 从 backend/app/text_miner/service.py
# ============================================================================

class OCRSimulator:
    """OCR模拟器 - 模拟文本提取过程"""

    def __init__(self, min_confidence: float = 0.7):
        self.min_confidence = min_confidence
        self._text_templates = [
            "{}，{}撰，{}年{}刻本。{}，{}，{}。{}。",
            "《{}》，{}著，{}刊本。{}，{}，{}。",
            "{}卷，{}编，{}版。{}，{}，{}，{}。",
        ]

    def simulate_ocr(self, book_title: str, book_info: Dict[str, Any]) -> Tuple[str, float]:
        author = book_info.get("author", "佚名")
        dynasty = book_info.get("dynasty", "明")
        year = book_info.get("publication_year", "万历")
        material = book_info.get("material", "竹纸")
        condition = book_info.get("condition", "完好")

        template = random.choice(self._text_templates)
        text = template.format(book_title, author, dynasty, year, material, condition,
                               "字体工整", "墨迹清晰", "版式开阔", "钤印累累")

        confidence = round(random.uniform(self.min_confidence, 0.99), 4)
        return text, confidence

    def extract_text_features(self, text: str) -> List[float]:
        features = np.zeros(8, dtype=np.float64)

        if not text:
            return features.tolist()

        features[0] = min(1.0, len(text) / 500.0)
        features[1] = min(1.0, len(text.split('。')) / 20.0)

        punct_count = sum(1 for c in text if c in '，。；：！？、')
        features[2] = punct_count / max(1, len(text))

        digit_count = sum(1 for c in text if c.isdigit())
        features[3] = digit_count / max(1, len(text))

        rare_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' and ord(c) > 0x6000)
        features[4] = rare_chars / max(1, len(text))

        features[5] = random.uniform(0.3, 0.9)
        features[6] = random.uniform(0.2, 0.8)
        features[7] = random.uniform(0.4, 0.95)

        return features.tolist()


class ProportionalHazardsModel:
    """比例风险模型 (Cox模型)
    用于根据书籍元数据调整老化速率"""

    def __init__(self):
        self.beta_binding = 0.15
        self.beta_repair = 0.10
        self.beta_fiber = -0.30
        self.beta_ink = 0.25

        self.binding_factors = {
            "线装": 0.8,
            "蝴蝶装": 1.0,
            "包背装": 0.9,
            "梵夹装": 1.2,
            "卷轴装": 1.1,
        }

        self.ink_acidic_map = {
            "松烟墨": 0.3,
            "油烟墨": 0.5,
            "墨汁": 0.8,
            "朱砂": 0.1,
            "天然颜料": 0.2,
        }

    def _get_binding_factor(self, binding_type: str) -> float:
        return self.binding_factors.get(binding_type, 1.0)

    def _get_ink_acidic(self, ink_type: str) -> float:
        return self.ink_acidic_map.get(ink_type, 0.5)

    def calculate_hazard_ratio(self, book_meta: Dict[str, Any]) -> float:
        binding_type = book_meta.get("binding_type", "线装")
        repair_count = len(book_meta.get("repair_records", []))
        fiber_density = book_meta.get("fiber_density", 0.7)
        ink_type = book_meta.get("ink_type", "油烟墨")

        binding_factor = self._get_binding_factor(binding_type)
        ink_acidic = self._get_ink_acidic(ink_type)

        linear_predictor = (
            self.beta_binding * binding_factor +
            self.beta_repair * repair_count +
            self.beta_fiber * fiber_density +
            self.beta_ink * ink_acidic
        )

        hr = math.exp(linear_predictor)
        hr = max(0.5, min(2.5, hr))

        return hr

    def adjust_decay_rate(self, base_decay_rate: float, book_meta: Dict[str, Any]) -> float:
        hr = self.calculate_hazard_ratio(book_meta)
        return base_decay_rate * hr


class BookMetaExtractor:
    """书籍元数据提取器"""

    def __init__(self):
        self.paper_type_keywords = {
            "竹纸": "bamboo",
            "棉纸": "cotton",
            "皮纸": "cotton",
            "宣纸": "rice",
            "开化纸": "kaihua",
            "雪连纸": "xuelian",
        }

        self.binding_types = ["线装", "蝴蝶装", "包背装", "梵夹装", "卷轴装"]

        self.repair_keywords = ["修复", "重装", "补缀", "托裱", "衬纸"]

        self.ink_types = ["松烟墨", "油烟墨", "墨汁", "朱砂", "天然颜料"]

        self.title_patterns = [
            ("明万历", "竹纸"),
            ("明嘉靖", "棉纸"),
            ("明崇祯", "竹纸"),
            ("清康熙", "皮纸"),
            ("清乾隆武英殿", "开化纸"),
            ("清乾隆", "开化纸"),
            ("清嘉庆", "竹纸"),
            ("清道光", "竹纸"),
            ("宋刻", "皮纸"),
            ("元刻", "棉纸"),
            ("民国", "机制纸"),
            ("抄本", "棉纸"),
            ("稿本", "宣纸"),
        ]

    def extract_paper_type(self, title: str, book_info: Dict[str, Any]) -> str:
        for pattern, paper in self.title_patterns:
            if pattern in title:
                return self.paper_type_keywords.get(paper, "bamboo")

        material = book_info.get("material", "")
        if material:
            for keyword, paper_type in self.paper_type_keywords.items():
                if keyword in material:
                    return paper_type

        return "bamboo"

    def extract_binding_type(self, title: str, ocr_text: str) -> str:
        combined_text = title + ocr_text
        for binding in self.binding_types:
            if binding in combined_text:
                return binding

        if "卷" in title or "卷轴" in ocr_text:
            return "卷轴装"
        if "册" in title or "线订" in ocr_text:
            return "线装"

        return "线装"

    def extract_repair_records(self, ocr_text: str) -> List[str]:
        records = []
        for keyword in self.repair_keywords:
            if keyword in ocr_text:
                records.append(f"发现{keyword}痕迹")

        if random.random() < 0.3:
            year = random.choice(["1985", "1992", "2001", "2010", "2018"])
            records.append(f"{year}年修复")

        return records

    def extract_fiber_density(self, paper_type: str, text_features: List[float]) -> float:
        base_density = {
            "bamboo": 0.65,
            "cotton": 0.75,
            "rice": 0.55,
            "kaihua": 0.85,
            "xuelian": 0.80,
        }

        base = base_density.get(paper_type, 0.7)
        variation = (text_features[5] + text_features[7]) / 2 - 0.5
        density = base + variation * 0.2

        return round(max(0.3, min(0.95, density)), 4)

    def extract_ink_type(self, title: str, ocr_text: str) -> str:
        combined_text = title + ocr_text

        if "朱砂" in combined_text or "朱印" in combined_text:
            return "朱砂"
        if "彩绘本" in combined_text or "彩绘" in combined_text:
            return "天然颜料"
        if "明" in title and "万历" in title:
            return "松烟墨"
        if "清" in title:
            return "油烟墨"
        if "民国" in title or "现代" in combined_text:
            return "墨汁"

        return random.choice(self.ink_types)


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class BookMetaExtractResult:
    """医籍元数据提取结果"""
    book_id: str = ""
    shelf_id: str = ""
    slot_id: str = ""
    paper_type: str = ""
    binding_type: str = ""
    repair_records: List[str] = field(default_factory=list)
    fiber_density: float = 0.0
    ink_type: str = ""
    ocr_confidence: float = 0.0
    text_features: List[float] = field(default_factory=list)
    ocr_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# NamedConnectionPool - 从 backend/app/database.py
# ============================================================================

class NamedConnectionPool:
    """命名ClickHouse连接池"""

    def __init__(self, name: str, max_connections: int = 4):
        self.name = name
        self.max_connections = max_connections
        self._pool: "queue.Queue[Client]" = queue.Queue(maxsize=max_connections)
        self._created_count = 0
        self._lock = threading.Lock()
        self._total_checkouts = 0
        self._total_returns = 0
        self._timeouts = 0

    def _create_client(self) -> Optional[Client]:
        try:
            client = Client(
                host=config.CLICKHOUSE_HOST,
                port=config.CLICKHOUSE_PORT,
                user=config.CLICKHOUSE_USER,
                password=config.CLICKHOUSE_PASSWORD,
                database=config.CLICKHOUSE_DATABASE,
                connect_timeout=10,
                send_receive_timeout=30,
            )
            logger.info(f"[{self.name}] 创建ClickHouse连接 (池大小={self.max_connections}, "
                        f"已创建={self._created_count + 1})")
            return client
        except Exception as e:
            logger.error(f"[{self.name}] 创建ClickHouse连接失败: {e}")
            return None

    def acquire(self, timeout: float = 5.0) -> Optional[Client]:
        start_time = time.time()

        try:
            client = self._pool.get_nowait()
            self._total_checkouts += 1
            return client
        except queue.Empty:
            pass

        with self._lock:
            if self._created_count < self.max_connections:
                client = self._create_client()
                if client:
                    self._created_count += 1
                    self._total_checkouts += 1
                    return client

        wait_start = time.time()
        try:
            remaining = timeout - (time.time() - start_time)
            if remaining > 0:
                client = self._pool.get(timeout=remaining)
                self._total_checkouts += 1
                return client
        except queue.Empty:
            pass

        self._timeouts += 1
        logger.warning(f"[{self.name}] 连接池获取超时 (已等待{time.time()-wait_start:.1f}s, "
                       f"超时总数={self._timeouts})")
        return None

    def release(self, client: Client) -> None:
        if client is None:
            return
        try:
            self._pool.put_nowait(client)
            self._total_returns += 1
        except queue.Full:
            try:
                client.disconnect()
            except Exception:
                pass
            with self._lock:
                    self._created_count -= 1

    def close_all(self) -> None:
        closed = 0
        while not self._pool.empty():
            try:
                client = self._pool.get_nowait()
                client.disconnect()
                closed += 1
            except (queue.Empty, Exception):
                pass
        logger.info(f"[{self.name}] 连接池已关闭，释放{closed}个连接")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "max_connections": self.max_connections,
            "created": self._created_count,
            "idle": self._pool.qsize(),
            "checkouts": self._total_checkouts,
            "returns": self._total_returns,
            "timeouts": self._timeouts,
        }


# ============================================================================
# 模拟 Redis - 内存 dict + TTL
# ============================================================================

class MockRedis:
    """内存模拟 Redis，支持 TTL"""

    def __init__(self, ttl_seconds: int = 86400):
        self._data: Dict[str, Tuple[Any, float]] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        with self._lock:
            ttl = ex if ex is not None else self._ttl_seconds
            self._data[key] = (value, time.time() + ttl)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._data:
                return None
            value, expire_at = self._data[key]
            if time.time() > expire_at:
                self._data.pop(key, None)
                return None
            return value

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                self._data.pop(key, None)
                return True
            return False

    def exists(self, key: str) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            _, expire_at = self._data[key]
            if time.time() > expire_at:
                self._data.pop(key, None)
                return False
            return True

    def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        with self._lock:
            self._cleanup_expired()
            return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]

    def flushdb(self) -> None:
        with self._lock:
            self._data.clear()

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, expire_at) in self._data.items() if now > expire_at]
        for k in expired:
            self._data.pop(k, None)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_expired()
            return {
                "total_keys": len(self._data),
                "ttl_seconds": self._ttl_seconds,
            }


# ============================================================================
# OCR Cache 服务
# ============================================================================

class OCRCacheService:
    """OCR 缓存服务"""

    def __init__(self):
        self.ocr_simulator = OCRSimulator()
        self.meta_extractor = BookMetaExtractor()
        self.hazards_model = ProportionalHazardsModel()

        self.pool = NamedConnectionPool(
            name=config.CLICKHOUSE_POOL_NAME,
            max_connections=config.CLICKHOUSE_POOL_SIZE
        )

        self.cache = MockRedis(ttl_seconds=config.CACHE_TTL_SECONDS)

        self._stats = {
            "total_extracted": 0,
            "total_errors": 0,
            "last_extraction_time": None,
            "cache_hits": 0,
            "cache_misses": 0,
            "last_batch_run": None,
            "total_batches_run": 0,
        }

        self._lock = threading.Lock()

        self._ensure_book_meta_table()

    def _ensure_book_meta_table(self) -> None:
        """确保 book_meta 表存在"""
        client = self.pool.acquire(timeout=10.0)
        if client is None:
            logger.error("无法获取连接，跳过表创建")
            return
        try:
            client.execute(f"""
                CREATE TABLE IF NOT EXISTS {config.CLICKHOUSE_DATABASE}.book_meta (
                    book_id String,
                    shelf_id String,
                    slot_id String,
                    paper_type String,
                    binding_type String,
                    repair_records Array(String),
                    fiber_density Float64,
                    ink_type String,
                    ocr_confidence Float64,
                    text_features Array(Float64),
                    ocr_text String,
                    create_time DateTime DEFAULT now(),
                    update_time DateTime DEFAULT now()
                ) ENGINE = MergeTree()
                ORDER BY (book_id, shelf_id, slot_id)
            """)
            logger.info("book_meta 表检查完成")
        except Exception as e:
            logger.warning(f"创建 book_meta 表失败: {e}")
        finally:
            self.pool.release(client)

    def _execute_query(self, query: str, params: Dict = None) -> List:
        """执行查询，自动管理连接"""
        client = self.pool.acquire(timeout=5.0)
        if client is None:
            logger.error("连接池耗尽，查询失败")
            return []
        try:
            return client.execute(query, params or {})
        except Exception as e:
            logger.error(f"执行查询失败: {e}")
            return []
        finally:
            self.pool.release(client)

    def _execute_insert(self, query: str, values: List[Tuple]) -> None:
        """执行插入，自动管理连接"""
        client = self.pool.acquire(timeout=5.0)
        if client is None:
            logger.error("连接池耗尽，插入失败")
            return
        try:
            client.execute(query, values)
        except Exception as e:
            logger.error(f"执行插入失败: {e}")
        finally:
            self.pool.release(client)

    def _get_books_info(self) -> List[Dict[str, Any]]:
        """获取所有书籍信息"""
        query = f"""
            SELECT book_id, shelf_id, slot_id, title, dynasty,
                   author, category, material, publication_year,
                   condition
            FROM books_info
            ORDER BY shelf_id, slot_id
        """
        results = self._execute_query(query)
        columns = ["book_id", "shelf_id", "slot_id", "title", "dynasty",
                   "author", "category", "material", "publication_year",
                   "condition"]
        return [dict(zip(columns, row)) for row in results]

    def extract_meta(self, book_id: str, shelf_id: str, slot_id: str,
                      book_info: Dict[str, Any]) -> Optional[BookMetaExtractResult]:
        """提取单本书的元数据"""
        start_time = time.time()

        try:
            title = book_info.get("title", f"古籍-{book_id}")

            ocr_text, ocr_confidence = self.ocr_simulator.simulate_ocr(title, book_info)
            text_features = self.ocr_simulator.extract_text_features(ocr_text)

            paper_type = self.meta_extractor.extract_paper_type(title, book_info)
            binding_type = self.meta_extractor.extract_binding_type(title, ocr_text)
            repair_records = self.meta_extractor.extract_repair_records(ocr_text)
            fiber_density = self.meta_extractor.extract_fiber_density(paper_type, text_features)
            ink_type = self.meta_extractor.extract_ink_type(title, ocr_text)

            result = BookMetaExtractResult(
                book_id=book_id,
                shelf_id=shelf_id,
                slot_id=slot_id,
                paper_type=paper_type,
                binding_type=binding_type,
                repair_records=repair_records,
                fiber_density=fiber_density,
                ink_type=ink_type,
                ocr_confidence=ocr_confidence,
                text_features=text_features,
                ocr_text=ocr_text,
            )

            cache_key = f"{shelf_id}:{slot_id}"
            self.cache.set(cache_key, result.to_dict())
            self.cache.set(book_id, result.to_dict())

            self._save_to_clickhouse(result)

            with self._lock:
                self._stats["total_extracted"] += 1
                self._stats["last_extraction_time"] = datetime.now().isoformat()

            logger.info(f"书籍元数据提取完成: book_id={book_id}, paper_type={paper_type}, "
                       f"binding={binding_type}, confidence={ocr_confidence:.3f}")

            return result

        except Exception as e:
            with self._lock:
                self._stats["total_errors"] += 1
            logger.error(f"书籍元数据提取失败: book_id={book_id}, error={e}")
            return None

    def _save_to_clickhouse(self, result: BookMetaExtractResult) -> None:
        """保存到 ClickHouse"""
        query = f"""
            INSERT INTO book_meta (
                book_id, shelf_id, slot_id, paper_type, binding_type,
                repair_records, fiber_density, ink_type,
                ocr_confidence, text_features, ocr_text
            ) VALUES
        """
        values = [(
            result.book_id,
            result.shelf_id,
            result.slot_id,
            result.paper_type,
            result.binding_type,
            result.repair_records,
            result.fiber_density,
            result.ink_type,
            result.ocr_confidence,
            result.text_features,
            result.ocr_text,
        )]
        self._execute_insert(query, values)

    def get_cached_meta(self, shelf_id: str, slot_id: str) -> Optional[Dict[str, Any]]:
        """获取缓存的元数据"""
        cache_key = f"{shelf_id}:{slot_id}"
        cached = self.cache.get(cache_key)

        if cached is not None:
            with self._lock:
                self._stats["cache_hits"] += 1
            return cached

        with self._lock:
            self._stats["cache_misses"] += 1

        query = f"""
            SELECT book_id, shelf_id, slot_id, paper_type, binding_type,
                   repair_records, fiber_density, ink_type,
                   ocr_confidence, text_features, ocr_text
            FROM book_meta
            WHERE shelf_id = %(shelf_id)s AND slot_id = %(slot_id)s
            ORDER BY update_time DESC
            LIMIT 1
        """
        params = {"shelf_id": shelf_id, "slot_id": slot_id}
        results = self._execute_query(query, params)

        if results:
            row = results[0]
            result = {
                "book_id": row[0],
                "shelf_id": row[1],
                "slot_id": row[2],
                "paper_type": row[3],
                "binding_type": row[4],
                "repair_records": list(row[5]),
                "fiber_density": row[6],
                "ink_type": row[7],
                "ocr_confidence": row[8],
                "text_features": list(row[9]),
                "ocr_text": row[10],
            }
            self.cache.set(cache_key, result)
            return result

        return None

    def process_all_books(self) -> int:
        """批量处理所有书籍"""
        logger.info("开始批量处理所有书籍元数据...")

        books = self._get_books_info()
        if not books:
            logger.info("没有找到需要处理的书籍")
            return 0

        processed_count = 0

        for book in books:
            book_id = book.get("book_id")
            shelf_id = book.get("shelf_id", "")
            slot_id = book.get("slot_id", "")

            if not book_id:
                continue

            result = self.extract_meta(book_id, shelf_id, slot_id, book)
            if result:
                processed_count += 1

        with self._lock:
            self._stats["last_batch_run"] = datetime.now().isoformat()
            self._stats["total_batches_run"] += 1

        logger.info(f"批量处理完成: 处理{processed_count}本，共{len(books)}本")
        return processed_count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            stats = dict(self._stats)
        stats.update({
            "cache_stats": self.cache.get_stats(),
            "pool_stats": self.pool.get_stats(),
        })
        return stats

    def refresh_cache(self) -> Dict[str, Any]:
        """刷新所有缓存"""
        self.cache.flushdb()
        count = self.process_all_books()
        return {"refreshed": count}

    def close(self) -> None:
        """关闭服务"""
        self.pool.close_all()


# ============================================================================
# 定时任务
# ============================================================================

class ScheduledTask:
    """定时任务调度器"""

    def __init__(self, service: OCRCacheService):
        self.service = service
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _should_run_now(self) -> bool:
        now = datetime.now()
        return (now.hour == config.SCHEDULED_HOUR and
                now.minute == config.SCHEDULED_MINUTE)

    def _scheduler_loop(self) -> None:
        logger.info(f"定时任务已启动，每天 {config.SCHEDULED_HOUR:02d}:{config.SCHEDULED_MINUTE:02d} 运行 OCR 批处理")

        last_run_date = None

        while self._running:
            try:
                today = datetime.now().date()

                if self._should_run_now() and last_run_date != today:
                    logger.info("触发定时 OCR 批处理任务")
                    self.service.process_all_books()
                    last_run_date = today
                    logger.info("定时 OCR 批处理任务完成")

                time.sleep(30)

            except Exception as e:
                logger.error(f"定时任务异常: {e}")
                time.sleep(60)

        logger.info("定时任务已停止")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="ocr-cache-scheduler"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(title="OCR Cache Service", version="1.0.0")

_service: Optional[OCRCacheService] = None
_scheduler: Optional[ScheduledTask] = None


@app.on_event("startup")
async def startup_event():
    global _service, _scheduler
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    _service = OCRCacheService()
    _scheduler = ScheduledTask(_service)
    _scheduler.start()

    logger.info("OCR Cache 服务已启动")


@app.on_event("shutdown")
async def shutdown_event():
    if _scheduler:
        _scheduler.stop()
    if _service:
        _service.close()
    logger.info("OCR Cache 服务已停止")


@app.get("/cache/{shelf_id}:{slot_id}")
async def get_cache(shelf_id: str, slot_id: str):
    """获取指定 shelf_id:slot_id 的缓存数据"""
    if _service is None:
        raise HTTPException(status_code=503, detail="服务未就绪")

    result = _service.get_cached_meta(shelf_id, slot_id)
    if result is None:
        raise HTTPException(status_code=404, detail="缓存未找到")

    return JSONResponse(content={
    "success": True,
    "data": result,
})


@app.post("/cache/refresh")
async def refresh_cache():
    """刷新所有缓存"""
    if _service is None:
        raise HTTPException(status_code=503, detail="服务未就绪")

    result = _service.refresh_cache()
    return JSONResponse(content={
        "success": True,
        "data": result,
    })


@app.get("/cache/stats")
async def get_stats():
    """获取服务统计信息"""
    if _service is None:
        raise HTTPException(status_code=503, detail="服务未就绪")

    stats = _service.get_stats()
    return JSONResponse(content={
        "success": True,
        "data": stats,
    })


@app.get("/health")
async def health_check():
    """健康检查"""
    return JSONResponse(content={
        "status": "healthy",
        "service": "ocr-cache",
        "version": "1.0.0",
    })


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.FASTAPI_HOST,
        port=config.FASTAPI_PORT,
    )
