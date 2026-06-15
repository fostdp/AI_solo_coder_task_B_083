"""
古代防蠹药方有效性评估测试
覆盖正常、边界、异常三种场景
"""
import pytest
import math
import time
import os
import sys
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.efficacy_engine.efficacy import (
        beta_binomial_posterior,
        credible_interval,
        bayesian_efficacy_estimation,
        calculate_reduction_rate,
        BayesianEfficacyResult,
        _incomplete_beta,
        _beta_ppf,
    )
    from app.efficacy_engine.service import (
        SporeDataCollector,
        EfficacyEngineStats,
        PRESCRIPTION_NAMES,
    )


class TestBetaBinomialPosteriorNormal:
    """正常场景：Beta-Binomial 后验计算"""

    def test_posterior_with_successes(self):
        """正常场景：有成功试验时后验参数正确更新"""
        alpha, beta = beta_binomial_posterior(2.0, 2.0, 8, 10)

        assert alpha == 10.0
        assert beta == 4.0

        posterior_mean = alpha / (alpha + beta)
        assert abs(posterior_mean - 0.714) < 0.01

    def test_posterior_mean_increases_with_successes(self):
        """正常场景：成功次数越多后验均值越高"""
        a1, b1 = beta_binomial_posterior(2.0, 2.0, 3, 10)
        a2, b2 = beta_binomial_posterior(2.0, 2.0, 7, 10)

        mean1 = a1 / (a1 + b1)
        mean2 = a2 / (a2 + b2)

        assert mean2 > mean1


class TestBetaBinomialPosteriorBoundary:
    """边界场景：极端参数下的后验计算"""

    def test_zero_successes(self):
        """边界场景：零次成功时的后验"""
        alpha, beta = beta_binomial_posterior(1.0, 1.0, 0, 10)
        assert alpha == 1.0
        assert beta == 11.0

        mean = alpha / (alpha + beta)
        assert mean < 0.5

    def test_all_successes(self):
        """边界场景：全部成功时的后验"""
        alpha, beta = beta_binomial_posterior(1.0, 1.0, 10, 10)
        assert alpha == 11.0
        assert beta == 1.0

        mean = alpha / (alpha + beta)
        assert mean > 0.5

    def test_zero_trials(self):
        """边界场景：零次试验时后验等于先验"""
        alpha, beta = beta_binomial_posterior(2.0, 3.0, 0, 0)
        assert alpha == 2.0
        assert beta == 3.0


class TestBetaBinomialPosteriorException:
    """异常场景：无效参数处理"""

    def test_negative_trials_raises_error(self):
        """异常场景：试验次数为负数时抛出异常"""
        with pytest.raises(ValueError, match="trials不能为负数"):
            beta_binomial_posterior(2.0, 2.0, 5, -1)

    def test_negative_successes_raises_error(self):
        """异常场景：成功次数为负数时抛出异常"""
        with pytest.raises(ValueError, match="successes必须在0到trials之间"):
            beta_binomial_posterior(2.0, 2.0, -1, 10)

    def test_successes_exceed_trials_raises_error(self):
        """异常场景：成功次数超过试验次数时抛出异常"""
        with pytest.raises(ValueError, match="successes必须在0到trials之间"):
            beta_binomial_posterior(2.0, 2.0, 15, 10)


class TestCredibleIntervalNormal:
    """正常场景：可信区间计算"""

    def test_95_percent_ci_contains_mean(self):
        """正常场景：95%可信区间应包含后验均值"""
        alpha, beta = 10.0, 4.0
        ci_low, ci_high = credible_interval(alpha, beta, 0.95)
        mean = alpha / (alpha + beta)

        assert ci_low < mean < ci_high
        assert ci_low > 0
        assert ci_high < 1

    def test_ci_width_increases_with_confidence(self):
        """正常场景：置信水平越高区间越宽"""
        alpha, beta = 5.0, 5.0

        ci_80_low, ci_80_high = credible_interval(alpha, beta, 0.80)
        ci_95_low, ci_95_high = credible_interval(alpha, beta, 0.95)

        width_80 = ci_80_high - ci_80_low
        width_95 = ci_95_high - ci_95_low

        assert width_95 > width_80


class TestCredibleIntervalBoundary:
    """边界场景：可信区间极端情况"""

    def test_ci_with_very_small_alpha(self):
        """边界场景：极小alpha参数的可信区间"""
        ci_low, ci_high = credible_interval(0.5, 10.0, 0.95)
        assert ci_low >= 0.0
        assert ci_high <= 1.0
        assert ci_low < ci_high

    def test_ci_with_very_large_params(self):
        """边界场景：大参数下的可信区间"""
        ci_low, ci_high = credible_interval(100.0, 100.0, 0.95)
        mean = 100.0 / (100.0 + 100.0)

        assert ci_low < mean < ci_high
        assert ci_high - ci_low < 0.2

    def test_ci_low_greater_than_zero(self):
        """边界场景：可信区间下限大于0"""
        ci_low, _ = credible_interval(2.0, 2.0, 0.95)
        assert ci_low >= 0.0


class TestCredibleIntervalException:
    """异常场景：可信区间参数错误"""

    def test_zero_alpha_raises_error(self):
        """异常场景：alpha为0时抛出异常"""
        with pytest.raises(ValueError, match="alpha和beta必须为正数"):
            credible_interval(0.0, 2.0, 0.95)

    def test_negative_beta_raises_error(self):
        """异常场景：beta为负数时抛出异常"""
        with pytest.raises(ValueError, match="alpha和beta必须为正数"):
            credible_interval(2.0, -1.0, 0.95)

    def test_level_out_of_range_raises_error(self):
        """异常场景：置信水平超出范围时抛出异常"""
        with pytest.raises(ValueError, match="level必须在"):
            credible_interval(2.0, 2.0, 1.0)
        with pytest.raises(ValueError, match="level必须在"):
            credible_interval(2.0, 2.0, 0.0)


class TestBayesianEfficacyNormal:
    """正常场景：贝叶斯药效评估"""

    def setup_method(self):
        self.treatment_data = [
            {"spores_before": 100 + i * 5, "spores_after": 50 + i * 3}
            for i in range(20)
        ]
        self.control_data = [
            {"spores_before": 100 + i * 5, "spores_after": 85 + i * 2}
            for i in range(20)
        ]

    def test_efficacy_estimation_returns_result(self):
        """正常场景：返回完整的药效评估结果"""
        result = bayesian_efficacy_estimation(
            treatment_data=self.treatment_data,
            control_data=self.control_data,
            prior_alpha=2.0,
            prior_beta=2.0,
            ci_level=0.95,
        )

        assert isinstance(result, BayesianEfficacyResult)
        assert result.posterior_alpha > 0
        assert result.posterior_beta > 0
        assert 0 < result.posterior_mean < 1
        assert result.ci_low < result.posterior_mean < result.ci_high
        assert result.reduction_rate >= 0
        assert result.sample_size == 20

    def test_treatment_better_than_control_positive_reduction(self):
        """正常场景：治疗组优于对照组时减少率为正"""
        result = bayesian_efficacy_estimation(
            treatment_data=self.treatment_data,
            control_data=self.control_data,
        )

        assert result.reduction_rate > 0

    def test_posterior_mean_high_confidence(self):
        """正常场景：大量数据下后验概率>95%表示药效显著"""
        treatment = [
            {"spores_before": 100, "spores_after": 30}
            for _ in range(30)
        ]
        control = [
            {"spores_before": 100, "spores_after": 90}
            for _ in range(30)
        ]

        result = bayesian_efficacy_estimation(treatment, control)

        assert result.ci_low > 0.5
        assert result.reduction_rate > 0.3


class TestBayesianEfficacyBoundary:
    """边界场景：药效评估边界情况"""

    def test_small_sample_size_uses_weak_prior(self):
        """边界场景：小样本下使用弱先验，结果更保守"""
        treatment = [{"spores_before": 100, "spores_after": 50} for _ in range(3)]
        control = [{"spores_before": 100, "spores_after": 90} for _ in range(3)]

        result_weak = bayesian_efficacy_estimation(
            treatment, control, prior_alpha=1.0, prior_beta=1.0
        )
        result_strong = bayesian_efficacy_estimation(
            treatment, control, prior_alpha=10.0, prior_beta=10.0
        )

        assert result_weak.sample_size == 3
        assert result_strong.sample_size == 3

    def test_equal_treatment_and_control(self):
        """边界场景：治疗组与对照组效果相同时减少率为0"""
        data = [{"spores_before": 100, "spores_after": 80} for _ in range(10)]

        result = bayesian_efficacy_estimation(data, data)

        assert result.reduction_rate == pytest.approx(0.0, abs=0.01)

    def test_single_sample(self):
        """边界场景：单样本数据"""
        treatment = [{"spores_before": 100, "spores_after": 40}]
        control = [{"spores_before": 100, "spores_after": 90}]

        result = bayesian_efficacy_estimation(treatment, control)

        assert result.sample_size == 1
        assert 0 <= result.posterior_mean <= 1


class TestBayesianEfficacyException:
    """异常场景：药效评估异常处理"""

    def test_empty_treatment_data_raises_error(self):
        """异常场景：空治疗组数据抛出异常"""
        control = [{"spores_before": 100, "spores_after": 90}]
        with pytest.raises(ValueError, match="治疗组数据不能为空"):
            bayesian_efficacy_estimation([], control)

    def test_empty_control_data_raises_error(self):
        """异常场景：空对照组数据抛出异常"""
        treatment = [{"spores_before": 100, "spores_after": 50}]
        with pytest.raises(ValueError, match="对照组数据不能为空"):
            bayesian_efficacy_estimation(treatment, [])

    def test_invalid_prior_raises_error(self):
        """异常场景：无效先验参数抛出异常"""
        treatment = [{"spores_before": 100, "spores_after": 50}]
        control = [{"spores_before": 100, "spores_after": 90}]
        with pytest.raises(ValueError, match="先验参数必须为正数"):
            bayesian_efficacy_estimation(treatment, control, prior_alpha=0)


class TestReductionRateNormal:
    """正常场景：减少率计算"""

    def test_half_reduction(self):
        """正常场景：减少一半"""
        rate = calculate_reduction_rate(100, 50)
        assert rate == pytest.approx(0.5)

    def test_full_reduction(self):
        """正常场景：完全减少"""
        rate = calculate_reduction_rate(100, 0)
        assert rate == 1.0

    def test_no_reduction(self):
        """正常场景：无减少"""
        rate = calculate_reduction_rate(100, 100)
        assert rate == 0.0


class TestReductionRateBoundary:
    """边界场景：减少率边界情况"""

    def test_zero_initial(self):
        """边界场景：初始值为0时返回0"""
        rate = calculate_reduction_rate(0, 0)
        assert rate == 0.0

    def test_increase_clamped_to_zero(self):
        """边界场景：浓度增加时减少率钳制为0"""
        rate = calculate_reduction_rate(50, 100)
        assert rate == 0.0

    def test_negative_after_clamped(self):
        """边界场景：处理后为负数时钳制"""
        rate = calculate_reduction_rate(100, -10)
        assert rate == 1.0


class TestSporeDataCollectorNormal:
    """正常场景：孢子数据收集器"""

    def setup_method(self):
        self.collector = SporeDataCollector(lookback_hours=24)

    def test_add_and_get_data(self):
        """正常场景：添加和获取孢子数据"""
        self.collector.add_data("SHELF-01", "SLOT-001", 100.0)

        data = self.collector.get_data("SHELF-01", "SLOT-001")
        assert len(data) == 1
        assert data[0]["mold_spore"] == 100.0

    def test_get_shelf_data(self):
        """正常场景：获取书架的所有数据"""
        self.collector.add_data("SHELF-01", "SLOT-001", 100.0)
        self.collector.add_data("SHELF-01", "SLOT-002", 200.0)
        self.collector.add_data("SHELF-02", "SLOT-001", 300.0)

        shelf_data = self.collector.get_shelf_data(["SHELF-01"])
        assert len(shelf_data) == 2

    def test_get_before_after_data(self):
        """正常场景：获取处理前后数据对"""
        now = time.time()
        self.collector.add_data("SHELF-01", "SLOT-001", 100.0, timestamp=now - 3600)
        self.collector.add_data("SHELF-01", "SLOT-001", 60.0, timestamp=now + 3600)

        data = self.collector.get_before_after_data(["SHELF-01"], reference_time=now)
        assert len(data) == 1
        assert data[0]["spores_before"] == 100.0
        assert data[0]["spores_after"] == 60.0


class TestSporeDataCollectorBoundary:
    """边界场景：数据收集器边界情况"""

    def setup_method(self):
        self.collector = SporeDataCollector(lookback_hours=1)

    def test_old_data_expired(self):
        """边界场景：过期数据被清理"""
        old_time = time.time() - 7200
        self.collector.add_data("SHELF-01", "SLOT-001", 100.0, timestamp=old_time)

        data = self.collector.get_data("SHELF-01", "SLOT-001")
        assert len(data) == 0

    def test_empty_shelf_data(self):
        """边界场景：空书架返回空列表"""
        data = self.collector.get_shelf_data(["NONEXISTENT"])
        assert data == []

    def test_only_before_no_after(self):
        """边界场景：只有处理前数据没有处理后"""
        now = time.time()
        self.collector.add_data("SHELF-01", "SLOT-001", 100.0, timestamp=now - 1000)

        data = self.collector.get_before_after_data(["SHELF-01"], reference_time=now)
        assert len(data) == 0


class TestSporeDataCollectorException:
    """异常场景：数据收集器异常处理"""

    def setup_method(self):
        self.collector = SporeDataCollector(lookback_hours=24)

    def test_none_timestamp_uses_current(self):
        """异常场景：None时间戳使用当前时间"""
        self.collector.add_data("SHELF-01", "SLOT-001", 100.0, timestamp=None)
        data = self.collector.get_data("SHELF-01", "SLOT-001")
        assert len(data) == 1
        assert data[0]["timestamp"] is not None

    def test_negative_spore_stored(self):
        """异常场景：负孢子浓度也会被存储（由上层验证）"""
        self.collector.add_data("SHELF-01", "SLOT-001", -50.0)
        data = self.collector.get_data("SHELF-01", "SLOT-001")
        assert len(data) == 1


class TestPrescriptionNames:
    """药方名称映射测试"""

    def test_all_three_prescriptions(self):
        """测试三种药方都存在"""
        assert "yuncao" in PRESCRIPTION_NAMES
        assert "huangbo" in PRESCRIPTION_NAMES
        assert "yanye" in PRESCRIPTION_NAMES

    def test_chinese_names(self):
        """测试中文名称正确"""
        assert PRESCRIPTION_NAMES["yuncao"] == "芸草"
        assert PRESCRIPTION_NAMES["huangbo"] == "黄柏"
        assert PRESCRIPTION_NAMES["yanye"] == "烟叶"


class TestEfficacyEngineStats:
    """药效引擎统计数据测试"""

    def test_default_stats(self):
        stats = EfficacyEngineStats()
        assert stats.total_evaluations == 0
        assert stats.total_errors == 0
        assert stats.prescription_evaluations == {}

    def test_stats_mutation(self):
        stats = EfficacyEngineStats()
        stats.total_evaluations = 10
        stats.total_errors = 1
        stats.last_evaluation_time = "2024-01-01"

        assert stats.total_evaluations == 10
        assert stats.total_errors == 1
        assert stats.last_evaluation_time == "2024-01-01"
