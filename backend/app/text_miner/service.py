"""
文本挖掘服务
负责古籍OCR文本提取、元数据解析与老化速率调整
"""
import asyncio
import logging
import math
import random
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ..core.config import config
from ..core.messages import BookMetaExtractRequest, BookMetaExtractResult
from ..core.queue_manager import queue_manager, AsyncQueueWrapper
from ..database import db_manager

logger = logging.getLogger(__name__)


@dataclass
class TextMinerStats:
    """文本挖掘统计"""
    total_extracted: int = 0
    total_errors: int = 0
    last_extraction_time: Optional[str] = None
    avg_extraction_time_ms: float = 0.0
    books_processed: int = 0


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
        """
        模拟OCR文本提取

        Args:
            book_title: 书籍标题
            book_info: 书籍信息

        Returns:
            (提取的文本, OCR置信度)
        """
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
        """
        提取8维文本特征向量

        特征含义：
        0: 字符密度
        1: 句子平均长度
        2: 标点符号比例
        3: 数字比例
        4: 生僻字比例
        5: 行间距特征
        6: 字体大小变异系数
        7: 墨迹均匀度
        """
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
    """
    比例风险模型 (Cox模型)
    用于根据书籍元数据调整老化速率

    风险比 HR = exp(β1*binding_factor + β2*repair_count + β3*fiber_density + β4*ink_acidic)
    """

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
        """获取装订类型因子"""
        return self.binding_factors.get(binding_type, 1.0)

    def _get_ink_acidic(self, ink_type: str) -> float:
        """获取墨水酸性值"""
        return self.ink_acidic_map.get(ink_type, 0.5)

    def calculate_hazard_ratio(self, book_meta: Dict[str, Any]) -> float:
        """
        计算风险比 (HR)

        Args:
            book_meta: 书籍元数据，包含：
                - binding_type: 装订类型
                - repair_records: 修复记录列表
                - fiber_density: 纤维密度
                - ink_type: 墨水类型

        Returns:
            风险比 HR
        """
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
        """
        根据书籍元数据调整老化速率

        Args:
            base_decay_rate: 基础老化速率
            book_meta: 书籍元数据

        Returns:
            调整后的老化速率
        """
        hr = self.calculate_hazard_ratio(book_meta)
        return base_decay_rate * hr


class BookMetaExtractor:
    """书籍元数据提取器"""

    def __init__(self):
        tm_config = config.text_miner

        self.paper_type_keywords = tm_config.get("paper_type_keywords", {
            "竹纸": "bamboo",
            "棉纸": "cotton",
            "皮纸": "cotton",
            "宣纸": "rice",
            "开化纸": "kaihua",
            "雪连纸": "xuelian",
        })

        self.binding_types = tm_config.get("binding_types",
                                           ["线装", "蝴蝶装", "包背装", "梵夹装", "卷轴装"])

        self.repair_keywords = tm_config.get("repair_keywords",
                                             ["修复", "重装", "补缀", "托裱", "衬纸"])

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
        """
        从书名和书籍信息提取纸张类型

        Args:
            title: 书名
            book_info: 书籍信息

        Returns:
            纸张类型（英文标识）
        """
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
        """
        提取装订类型

        Args:
            title: 书名
            ocr_text: OCR提取的文本

        Returns:
            装订类型
        """
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
        """
        提取修复记录

        Args:
            ocr_text: OCR提取的文本

        Returns:
            修复记录列表
        """
        records = []
        for keyword in self.repair_keywords:
            if keyword in ocr_text:
                records.append(f"发现{keyword}痕迹")

        if random.random() < 0.3:
            year = random.choice(["1985", "1992", "2001", "2010", "2018"])
            records.append(f"{year}年修复")

        return records

    def extract_fiber_density(self, paper_type: str, text_features: List[float]) -> float:
        """
        估计纤维密度

        Args:
            paper_type: 纸张类型
            text_features: 文本特征

        Returns:
            纤维密度 (0.0-1.0)
        """
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
        """
        提取墨水类型

        Args:
            title: 书名
            ocr_text: OCR提取的文本

        Returns:
            墨水类型
        """
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


class TextMinerService:
    """
    文本挖掘服务
    异步服务，周期性处理所有书籍的元数据提取

    修复：OCR同步调用导致老化预测延迟问题
    方案：离线批处理+双层缓存（进程内内存+模拟Redis）
    - 每晚定时（run_interval=86400s）批量提取所有书籍OCR
    - 结果同时写入 book_id 索引和 shelf_slot 索引的快速缓存
    - 老化引擎通过同步快速查询（<0.1ms）直接读内存缓存，不触发OCR
    """

    def __init__(self, output_queue: AsyncQueueWrapper = None):
        tm_config = config.text_miner

        self.run_interval = tm_config.get("run_interval", 86400)
        self.min_confidence = tm_config.get("min_confidence", 0.7)
        self.ocr_simulate = tm_config.get("ocr_simulate", True)

        self.ocr_simulator = OCRSimulator(self.min_confidence)
        self.meta_extractor = BookMetaExtractor()
        self.hazards_model = ProportionalHazardsModel()

        self._output_queue = output_queue or queue_manager.create_async_queue(
            "book_meta_results", maxsize=1000
        )

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = TextMinerStats()

        self._book_meta_cache: Dict[str, BookMetaExtractResult] = {}
        self._shelf_slot_cache: Dict[str, BookMetaExtractResult] = {}
        self._lock = asyncio.Lock()
        self._cache_ttl: Dict[str, float] = {}

    async def extract_meta(self, book_id: str, shelf_id: str, slot_id: str,
                           book_info: Dict[str, Any]) -> Optional[BookMetaExtractResult]:
        """
        提取单本书的元数据

        Args:
            book_id: 书籍ID
            shelf_id: 书架ID
            slot_id: 槽位ID
            book_info: 书籍信息

        Returns:
            元数据提取结果
        """
        import time
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

            import time as _time
            _now = _time.time()

            async with self._lock:
                self._book_meta_cache[book_id] = result
                shelf_slot_key = f"{shelf_id}:{slot_id}"
                self._shelf_slot_cache[shelf_slot_key] = result
                self._cache_ttl[book_id] = _now
                self._cache_ttl[shelf_slot_key] = _now

            await self._output_queue.put(result)

            elapsed_ms = (time.time() - start_time) * 1000
            self._stats.total_extracted += 1
            self._stats.avg_extraction_time_ms = (
                self._stats.avg_extraction_time_ms * (self._stats.total_extracted - 1) + elapsed_ms
            ) / self._stats.total_extracted
            self._stats.last_extraction_time = datetime.now().isoformat()

            logger.info(f"书籍元数据提取完成: book_id={book_id}, paper_type={paper_type}, "
                       f"binding={binding_type}, confidence={ocr_confidence:.3f}")

            return result

        except Exception as e:
            self._stats.total_errors += 1
            logger.error(f"书籍元数据提取失败: book_id={book_id}, error={e}")
            return None

    async def process_all_books(self) -> int:
        """
        处理所有书籍的元数据提取

        Returns:
            成功处理的书籍数量
        """
        logger.info("开始处理所有书籍元数据...")

        try:
            books = db_manager.get_books_info()
        except Exception as e:
            logger.error(f"获取书籍列表失败: {e}")
            return 0

        if not books:
            logger.info("没有找到需要处理的书籍")
            return 0

        processed_count = 0

        for book in books:
            if not self._running:
                break

            book_id = book.get("book_id")
            shelf_id = book.get("shelf_id", "")
            slot_id = book.get("slot_id", "")

            if not book_id:
                continue

            result = await self.extract_meta(book_id, shelf_id, slot_id, book)
            if result:
                processed_count += 1

            await asyncio.sleep(0.1)

        self._stats.books_processed += processed_count
        logger.info(f"书籍元数据批量处理完成: 处理{processed_count}本，共{len(books)}本")

        return processed_count

    async def get_book_meta(self, book_id: str) -> Optional[BookMetaExtractResult]:
        """
        获取缓存的书籍元数据

        Args:
            book_id: 书籍ID

        Returns:
            书籍元数据提取结果
        """
        async with self._lock:
            if book_id in self._book_meta_cache:
                return self._book_meta_cache[book_id]

        try:
            books = db_manager.get_books_info()
            for book in books:
                if book.get("book_id") == book_id:
                    return await self.extract_meta(
                        book_id,
                        book.get("shelf_id", ""),
                        book.get("slot_id", ""),
                        book
                    )
        except Exception as e:
            logger.error(f"查询书籍元数据失败: book_id={book_id}, error={e}")

        return None

    def calculate_adjusted_decay_rate(self, base_decay_rate: float,
                                       book_meta: BookMetaExtractResult) -> float:
        """
        使用比例风险模型计算调整后的老化速率

        Args:
            base_decay_rate: 基础老化速率
            book_meta: 书籍元数据

        Returns:
            调整后的老化速率
        """
        meta_dict = {
            "binding_type": book_meta.binding_type,
            "repair_records": book_meta.repair_records,
            "fiber_density": book_meta.fiber_density,
            "ink_type": book_meta.ink_type,
        }
        return self.hazards_model.adjust_decay_rate(base_decay_rate, meta_dict)

    async def _periodic_process(self):
        """周期性处理任务"""
        logger.info(f"文本挖掘服务周期任务已启动，间隔: {self.run_interval}秒")

        while self._running:
            try:
                await self.process_all_books()
            except Exception as e:
                logger.error(f"周期处理任务异常: {e}")

            for _ in range(self.run_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

        logger.info("文本挖掘服务周期任务已停止")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._periodic_process())
        logger.info("文本挖掘服务已启动")

    async def stop(self):
        """停止服务"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await queue_manager.flush_all_async()
        logger.info("文本挖掘服务已停止")

    def get_output_queue(self) -> AsyncQueueWrapper:
        """获取输出队列"""
        return self._output_queue

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats.__dict__,
            "cache_size": len(self._book_meta_cache),
            "output_queue_size": self._output_queue.qsize(),
            "running": self._running,
        }
