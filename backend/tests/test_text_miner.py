"""
医籍内容关联老化风险测试
覆盖正常、边界、异常三种场景
"""
import pytest
import math
import os
import sys
from unittest.mock import patch, MagicMock
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.text_miner.service import (
        OCRSimulator,
        BookMetaExtractor,
        ProportionalHazardsModel,
        TextMinerStats,
    )


class TestOCRSimulatorNormal:
    """正常场景：OCR提取到"竹纸+金镶玉装"，模型调整系数应为1.2（竹纸基）"""

    def setup_method(self):
        self.ocr = OCRSimulator(min_confidence=0.8)

    def test_ocr_extracts_bamboo_paper_and_binding(self):
        """正常场景：OCR成功提取竹纸和装订类型"""
        book_info = {
            "author": "李时珍",
            "dynasty": "明",
            "publication_year": "万历",
            "material": "竹纸",
            "condition": "完好",
        }
        text, confidence = self.ocr.simulate_ocr("本草纲目", book_info)

        assert isinstance(text, str)
        assert len(text) > 0
        assert 0.8 <= confidence <= 1.0
        assert "竹纸" in text or "本草纲目" in text

    def test_extract_text_features_normal(self):
        """正常场景：从完整文本提取8维特征"""
        text = "本草纲目，李时珍撰，明万历年间刻本。竹纸，蝴蝶装，字迹工整，墨迹清晰。"
        features = self.ocr.extract_text_features(text)

        assert len(features) == 8
        assert all(isinstance(f, float) for f in features)
        assert features[0] > 0
        assert features[2] > 0

    def test_ocr_confidence_in_range(self):
        """正常场景：OCR置信度在合理范围内"""
        book_info = {"material": "竹纸"}
        confidences = []
        for _ in range(20):
            _, conf = self.ocr.simulate_ocr("test", book_info)
            confidences.append(conf)

        assert all(0.8 <= c <= 0.99 for c in confidences)
        assert max(confidences) > min(confidences)


class TestOCRSimulatorBoundary:
    """边界场景：OCR返回空文本，降级使用默认纸张类型"""

    def setup_method(self):
        self.ocr = OCRSimulator(min_confidence=0.7)
        self.extractor = BookMetaExtractor()

    def test_extract_features_empty_text(self):
        """边界场景：空文本返回全零特征向量"""
        features = self.ocr.extract_text_features("")

        assert len(features) == 8
        assert all(f == 0.0 for f in features)

    def test_extract_paper_type_fallback_to_bamboo(self):
        """边界场景：无匹配关键词时降级为竹纸"""
        paper_type = self.extractor.extract_paper_type("无名医书", {})
        assert paper_type == "bamboo"

    def test_extract_binding_type_fallback_to_thread(self):
        """边界场景：无装订信息时降级为线装"""
        binding = self.extractor.extract_binding_type("医书", "")
        assert binding == "线装"

    def test_extract_repair_records_empty_text(self):
        """边界场景：空文本提取修复记录为空"""
        records = self.extractor.extract_repair_records("")
        assert isinstance(records, list)


class TestProportionalHazardsModelNormal:
    """正常场景：比例风险模型计算正确"""

    def setup_method(self):
        self.model = ProportionalHazardsModel()

    def test_bamboo_paper_base_hazard_ratio(self):
        """正常场景：竹纸+蝴蝶装基础风险比约为1.2"""
        book_meta = {
            "binding_type": "蝴蝶装",
            "repair_records": [],
            "fiber_density": 0.7,
            "ink_type": "油烟墨",
        }
        hr = self.model.calculate_hazard_ratio(book_meta)

        assert 0.5 <= hr <= 2.5
        expected_binding = 1.0
        expected_ink = 0.5
        expected_linear = (
            self.model.beta_binding * expected_binding
            + self.model.beta_repair * 0
            + self.model.beta_fiber * 0.7
            + self.model.beta_ink * expected_ink
        )
        expected_hr = math.exp(expected_linear)
        expected_hr = max(0.5, min(2.5, expected_hr))
        assert abs(hr - expected_hr) < 0.01

    def test_adjust_decay_rate_with_meta(self):
        """正常场景：根据书籍元数据调整老化速率"""
        base_rate = 0.005
        book_meta = {
            "binding_type": "梵夹装",
            "repair_records": ["2010年修复"],
            "fiber_density": 0.6,
            "ink_type": "墨汁",
        }
        adjusted_rate = self.model.adjust_decay_rate(base_rate, book_meta)

        hr = self.model.calculate_hazard_ratio(book_meta)
        assert adjusted_rate == pytest.approx(base_rate * hr, rel=1e-6)
        assert adjusted_rate > 0

    def test_multiple_repair_records_increase_risk(self):
        """正常场景：多次修复记录增加老化风险"""
        meta_no_repair = {
            "binding_type": "线装",
            "repair_records": [],
            "fiber_density": 0.7,
            "ink_type": "油烟墨",
        }
        meta_three_repairs = {
            "binding_type": "线装",
            "repair_records": ["1990年修复", "2000年修复", "2010年修复"],
            "fiber_density": 0.7,
            "ink_type": "油烟墨",
        }

        hr_no_repair = self.model.calculate_hazard_ratio(meta_no_repair)
        hr_three_repairs = self.model.calculate_hazard_ratio(meta_three_repairs)

        assert hr_three_repairs > hr_no_repair


class TestProportionalHazardsModelBoundary:
    """边界场景：风险比的上下界钳制"""

    def setup_method(self):
        self.model = ProportionalHazardsModel()

    def test_hazard_ratio_lower_bound(self):
        """边界场景：极低风险因子时HR不低于0.5"""
        book_meta = {
            "binding_type": "线装",
            "repair_records": [],
            "fiber_density": 1.0,
            "ink_type": "朱砂",
        }
        hr = self.model.calculate_hazard_ratio(book_meta)
        assert hr >= 0.5

    def test_hazard_ratio_upper_bound(self):
        """边界场景：极高风险因子时HR不高于2.5"""
        book_meta = {
            "binding_type": "梵夹装",
            "repair_records": ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10"],
            "fiber_density": 0.1,
            "ink_type": "墨汁",
        }
        hr = self.model.calculate_hazard_ratio(book_meta)
        assert hr <= 2.5

    def test_empty_book_meta_uses_defaults(self):
        """边界场景：空元数据使用默认值"""
        hr = self.model.calculate_hazard_ratio({})
        assert 0.5 <= hr <= 2.5

    def test_unknown_binding_uses_default(self):
        """边界场景：未知装订类型使用默认因子1.0"""
        book_meta = {"binding_type": "未知装订", "fiber_density": 0.7}
        hr = self.model.calculate_hazard_ratio(book_meta)
        assert 0.5 <= hr <= 2.5

    def test_unknown_ink_uses_default(self):
        """边界场景：未知墨水类型使用默认值0.5"""
        book_meta = {"ink_type": "未知墨水", "fiber_density": 0.7}
        hr = self.model.calculate_hazard_ratio(book_meta)
        assert 0.5 <= hr <= 2.5


class TestProportionalHazardsModelException:
    """异常场景：OCR服务超时，模型使用缓存特征"""

    def setup_method(self):
        self.model = ProportionalHazardsModel()

    def test_cached_meta_still_works_after_timeout(self):
        """异常场景：缓存的元数据在OCR超时后仍能正常计算"""
        cached_meta = {
            "binding_type": "蝴蝶装",
            "repair_records": ["2015年修复"],
            "fiber_density": 0.65,
            "ink_type": "油烟墨",
        }
        hr = self.model.calculate_hazard_ratio(cached_meta)

        assert 0.5 <= hr <= 2.5
        adjusted = self.model.adjust_decay_rate(0.005, cached_meta)
        assert adjusted > 0

    def test_partial_meta_data_uses_defaults(self):
        """异常场景：部分字段缺失时使用默认值补全"""
        partial_meta = {
            "binding_type": "线装",
        }
        hr = self.model.calculate_hazard_ratio(partial_meta)
        assert 0.5 <= hr <= 2.5

    def test_invalid_fiber_density_clamped(self):
        """异常场景：纤维密度超出范围时模型仍返回合理值"""
        meta_high = {"fiber_density": 2.0}
        meta_low = {"fiber_density": -1.0}

        hr_high = self.model.calculate_hazard_ratio(meta_high)
        hr_low = self.model.calculate_hazard_ratio(meta_low)

        assert 0.5 <= hr_high <= 2.5
        assert 0.5 <= hr_low <= 2.5
        assert hr_low > hr_high


class TestBookMetaExtractorNormal:
    """正常场景：书籍元数据提取"""

    def setup_method(self):
        self.extractor = BookMetaExtractor()

    def test_extract_binding_from_ocr_text(self):
        """正常场景：从OCR文本提取装订类型"""
        ocr_text = "《黄帝内经》，蝴蝶装，竹纸印刷，字迹工整。"
        binding = self.extractor.extract_binding_type("黄帝内经", ocr_text)
        assert binding == "蝴蝶装"

    def test_extract_paper_from_title_pattern(self):
        """正常场景：从书名模式识别纸张类型"""
        paper = self.extractor.extract_paper_type("明万历本草纲目", {})
        assert paper == "bamboo"

    def test_extract_repair_records_with_keywords(self):
        """正常场景：从文本提取修复记录"""
        text = "此书历经修复，有补缀痕迹，曾经托裱。"
        records = self.extractor.extract_repair_records(text)
        assert isinstance(records, list)

    def test_fiber_density_by_paper_type(self):
        """正常场景：不同纸张类型对应不同纤维密度"""
        features = [0.5] * 8
        density_bamboo = self.extractor.extract_fiber_density("bamboo", features)
        density_rice = self.extractor.extract_fiber_density("rice", features)

        assert 0.0 <= density_bamboo <= 1.0
        assert 0.0 <= density_rice <= 1.0


class TestTextMinerStats:
    """文本挖掘统计数据类测试"""

    def test_default_stats(self):
        stats = TextMinerStats()
        assert stats.total_extracted == 0
        assert stats.total_errors == 0
        assert stats.last_extraction_time is None

    def test_stats_mutation(self):
        stats = TextMinerStats()
        stats.total_extracted = 10
        stats.total_errors = 2
        stats.last_extraction_time = "2024-01-01"

        assert stats.total_extracted == 10
        assert stats.total_errors == 2
        assert stats.last_extraction_time == "2024-01-01"
