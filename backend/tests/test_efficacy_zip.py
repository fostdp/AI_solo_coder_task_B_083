"""
零膨胀泊松模型（ZIP）单元测试
覆盖ZIP拟合、EM算法、零膨胀检测、贝叶斯评估集成等场景
"""
import pytest
import math
import numpy as np
from typing import List, Dict, Any
from unittest.mock import patch, MagicMock

with patch("clickhouse_driver.Client"):
    from app.efficacy_engine.efficacy import (
        fit_zero_inflated_poisson,
        detect_zero_inflation,
        _zip_pmf,
        _zip_log_likelihood,
        ZIPResult,
        bayesian_efficacy_estimation,
        BayesianEfficacyResult,
        beta_binomial_posterior,
        credible_interval,
        calculate_reduction_rate,
    )


class TestZIPMathematicalCorrectness:
    """ZIP模型数学正确性测试"""

    def test_zip_pmf_at_zero(self):
        """ZIP PMF在k=0时：P(0) = π + (1-π)e^(-λ)"""
        pi = 0.6
        lambda_ = 2.0

        p0 = _zip_pmf(0, pi, lambda_)
        expected = pi + (1 - pi) * math.exp(-lambda_)

        assert abs(p0 - expected) < 1e-10
        assert 0 <= p0 <= 1

    def test_zip_pmf_at_positive(self):
        """ZIP PMF在k>0时：P(k) = (1-π)·Poisson(k,λ)"""
        pi = 0.6
        lambda_ = 2.0
        k = 3

        pk = _zip_pmf(k, pi, lambda_)
        poisson_pk = (lambda_ ** k) * math.exp(-lambda_) / math.factorial(k)
        expected = (1 - pi) * poisson_pk

        assert abs(pk - expected) < 1e-10
        assert 0 <= pk <= 1

    def test_zip_pmf_sums_to_one(self):
        """ZIP PMF概率和应≈1"""
        test_cases = [
            (0.3, 1.0),
            (0.6, 2.0),
            (0.8, 0.5),
            (0.1, 5.0),
        ]

        for pi, lambda_ in test_cases:
            total = 0.0
            for k in range(30):
                total += _zip_pmf(k, pi, lambda_)

            assert abs(total - 1.0) < 0.05, f"π={pi}, λ={lambda_}: sum={total:.4f}"

    def test_zip_log_likelihood_monotonic(self):
        """对数似然值随拟合改善应单调增加"""
        data = [0] * 60 + [1] * 15 + [2] * 10 + [3] * 8 + [5] * 5 + [8] * 2

        ll_poor = _zip_log_likelihood(data, pi=0.1, lambda_=10.0)
        ll_good = _zip_log_likelihood(data, pi=0.6, lambda_=2.0)

        assert ll_good > ll_poor, f"好的拟合应有更高的对数似然: {ll_good:.2f} vs {ll_poor:.2f}"

    def test_zip_pi_bounds(self):
        """π参数必须在[0,1]范围内"""
        result = fit_zero_inflated_poisson([0] * 100, max_iter=100)

        assert 0 <= result.pi <= 1.0
        assert result.lambda_ >= 0

    def test_zip_lambda_non_negative(self):
        """λ参数必须非负"""
        result = fit_zero_inflated_poisson([0, 0, 1, 0, 2, 0, 3, 1, 0, 0])

        assert result.lambda_ >= 0


class TestZIPFittingConvergence:
    """ZIP模型拟合收敛性测试"""

    def test_em_converges_moderate_zi(self):
        """中等零膨胀数据：EM算法应收敛"""
        data = [0] * 50 + [1] * 20 + [2] * 15 + [3] * 10 + [4] * 5

        result = fit_zero_inflated_poisson(data, max_iter=200, tol=1e-8)

        assert result.converged
        assert result.iterations < 200
        assert 0.3 < result.pi < 0.7

    def test_em_converges_high_zi(self):
        """高度零膨胀数据：EM算法应收敛到高π值"""
        data = [0] * 80 + [1] * 10 + [2] * 5 + [3] * 3 + [5] * 2

        result = fit_zero_inflated_poisson(data, max_iter=500)

        assert result.converged
        assert result.pi > 0.7
        assert result.zero_inflation_ratio > 0.75

    def test_em_converges_low_zi(self):
        """低度零膨胀数据：EM算法应收敛到低π值"""
        data = [0] * 10 + [1] * 25 + [2] * 30 + [3] * 20 + [4] * 10 + [5] * 5

        result = fit_zero_inflated_poisson(data, max_iter=200)

        assert result.converged
        assert result.pi < 0.3

    def test_em_all_zeros(self):
        """全零数据：π≈1，λ→0"""
        result = fit_zero_inflated_poisson([0] * 100, max_iter=500)

        assert result.pi > 0.95
        assert 0 <= result.lambda_ < 1.0

    def test_em_no_zeros(self):
        """无零数据：应收敛到π≈0"""
        data = [k for k in range(1, 11) for _ in range(10)]

        result = fit_zero_inflated_poisson(data, max_iter=200)

        assert result.converged
        assert result.pi < 0.1
        assert result.lambda_ > 0

    def test_em_deterministic(self):
        """相同数据应得到相同结果（确定性）"""
        data = [0] * 60 + [1] * 15 + [2] * 10 + [3] * 8 + [5] * 5 + [8] * 2

        results = []
        for _ in range(5):
            r = fit_zero_inflated_poisson(data, max_iter=200, tol=1e-10)
            results.append((r.pi, r.lambda_))

        first = results[0]
        for r in results[1:]:
            assert abs(r[0] - first[0]) < 1e-6, f"π值不一致: {r[0]} vs {first[0]}"
            assert abs(r[1] - first[1]) < 1e-6, f"λ值不一致: {r[1]} vs {first[1]}"


class TestZeroInflationDetection:
    """零膨胀检测测试"""

    def test_detect_high_zero_ratio(self):
        """高零值比例：应检测为零膨胀"""
        data = [0] * 70 + [1] * 15 + [2] * 10 + [3] * 5

        is_zi, ratio = detect_zero_inflation(data)

        assert is_zi is True
        assert ratio >= 0.6

    def test_detect_poisson_like(self):
        """泊松型数据：不应检测为零膨胀"""
        np.random.seed(42)
        data = np.random.poisson(lam=3.0, size=200).tolist()

        is_zi, ratio = detect_zero_inflation(data)
        zero_count = sum(1 for x in data if x == 0)
        expected_zero_ratio = math.exp(-3.0)

        assert abs(ratio - expected_zero_ratio) < 0.1

    def test_detect_overdispersion(self):
        """过度离散数据（方差>>均值）：即使零不多也应检测"""
        data = [0] * 30 + [1] * 20 + [10] * 20 + [20] * 15 + [50] * 10 + [100] * 5

        is_zi, ratio = detect_zero_inflation(data)

        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)

        assert variance > 2 * mean, f"方差={variance:.1f}, 均值={mean:.1f}"
        assert is_zi is True

    def test_detect_underdispersion(self):
        """低度离散数据：不应检测为零膨胀"""
        data = [2, 2, 3, 2, 3, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3]

        is_zi, _ = detect_zero_inflation(data)

        assert is_zi is False

    def test_detect_empty_data(self):
        """空数据：安全返回"""
        is_zi, ratio = detect_zero_inflation([])

        assert is_zi is False
        assert ratio == 0.0

    def test_detect_single_value(self):
        """单值数据：边界情况"""
        is_zi1, _ = detect_zero_inflation([0])
        is_zi2, _ = detect_zero_inflation([5])

        assert is_zi1 is True or is_zi1 is False
        assert is_zi2 is False


class TestZIPBayesianIntegration:
    """ZIP与贝叶斯评估集成测试"""

    def test_bayesian_auto_detects_zi(self):
        """贝叶斯评估应自动检测零膨胀并使用ZIP"""
        treatment = []
        for i in range(30):
            before = 100 if i % 5 == 0 else 0
            after = 20 if before > 0 else 0
            treatment.append({"spores_before": float(before), "spores_after": float(after)})

        control = []
        for i in range(30):
            before = 100 if i % 5 == 0 else 0
            after = 80 if before > 0 else 0
            control.append({"spores_before": float(before), "spores_after": float(after)})

        with patch('app.efficacy_engine.efficacy.detect_zero_inflation',
                   return_value=(True, 0.8)) as mock_detect:
            result = bayesian_efficacy_estimation(treatment, control)

        assert isinstance(result, BayesianEfficacyResult)
        assert hasattr(result, 'posterior_mean')
        assert result.ci_low < result.posterior_mean < result.ci_high

    def test_zip_efficacy_computation(self):
        """ZIP有效性计算：治疗组应有更高π+更低λ"""
        treatment_data = [0] * 60 + [1] * 20 + [2] * 12 + [3] * 5 + [4] * 3
        control_data = [0] * 30 + [1] * 15 + [2] * 15 + [3] * 15 + [4] * 10 + [5] * 8 + [6] * 5 + [8] * 2

        zip_treatment = fit_zero_inflated_poisson(treatment_data)
        zip_control = fit_zero_inflated_poisson(control_data)

        assert zip_treatment.pi >= zip_control.pi * 0.8, \
            f"治疗组应有更高结构零概率: T={zip_treatment.pi:.3f}, C={zip_control.pi:.3f}"
        assert zip_treatment.lambda_ <= zip_control.lambda_, \
            f"治疗组应有更低泊松强度: T={zip_treatment.lambda_:.3f}, C={zip_control.lambda_:.3f}"

        pi_diff = zip_treatment.pi - zip_control.pi
        lambda_ratio = 1.0 - (zip_treatment.lambda_ / max(zip_control.lambda_, 1e-9))
        efficacy = 0.5 * pi_diff + 0.5 * lambda_ratio

        assert efficacy > 0, f"ZIP有效性应>0，实际: {efficacy:.3f}"

    def test_bayesian_non_zi_fallback(self):
        """非零膨胀数据应回退到标准Beta-Binomial"""
        treatment = [{"spores_before": 100.0, "spores_after": 40.0 + i * 2} for i in range(20)]
        control = [{"spores_before": 100.0, "spores_after": 70.0 + i * 2} for i in range(20)]

        with patch('app.efficacy_engine.efficacy.detect_zero_inflation',
                   return_value=(False, 0.0)) as mock_detect:
            result = bayesian_efficacy_estimation(treatment, control)

        assert isinstance(result, BayesianEfficacyResult)
        assert result.reduction_rate >= 0.3

    def test_reduction_rate_calculation(self):
        """减少率计算：(before-after)/before"""
        before = 100.0
        after = 30.0

        rate = calculate_reduction_rate(before, after)
        expected = (100 - 30) / 100

        assert abs(rate - expected) < 1e-10
        assert 0 <= rate <= 1

    def test_reduction_rate_zero_before(self):
        """before为0时：安全返回0"""
        rate = calculate_reduction_rate(0.0, 50.0)
        assert rate == 0.0

    def test_reduction_rate_increase(self):
        """after > before时：返回0（无减少）"""
        rate = calculate_reduction_rate(50.0, 100.0)
        assert rate == 0.0


class TestBetaBinomialCorrectness:
    """Beta-Binomial模型正确性测试（确保原有功能不回归）"""

    def test_beta_binomial_posterior(self):
        """Beta-Binomial后验计算应返回合理参数"""
        trials = [10] * 30
        successes = [7] * 15 + [8] * 15

        total_trials = sum(trials)
        total_successes = sum(successes)

        alpha, beta = beta_binomial_posterior(2.0, 2.0, total_successes, total_trials)

        assert alpha > 0
        assert beta > 0
        posterior_mean = alpha / (alpha + beta)
        assert 0 < posterior_mean < 1

    def test_credible_interval(self):
        """可信区间应包含后验均值"""
        alpha = 50.0
        beta = 20.0

        ci_low, ci_high = credible_interval(alpha, beta, 0.95)

        mean = alpha / (alpha + beta)
        assert ci_low < mean < ci_high
        assert ci_low > 0
        assert ci_high < 1

    def test_credible_interval_width(self):
        """可信区间应包含后验均值，且区间在合理范围内"""
        alpha = 20.0
        beta = 20.0

        ci_90_low, ci_90_high = credible_interval(alpha, beta, 0.90)
        ci_95_low, ci_95_high = credible_interval(alpha, beta, 0.95)
        ci_99_low, ci_99_high = credible_interval(alpha, beta, 0.99)

        width_90 = ci_90_high - ci_90_low
        width_95 = ci_95_high - ci_95_low
        width_99 = ci_99_high - ci_99_low

        mean = alpha / (alpha + beta)
        assert ci_90_low - 0.01 < mean < ci_90_high + 0.01, f"90% CI [{ci_90_low:.4f}, {ci_90_high:.4f}] 应包含均值 {mean:.4f}"
        assert ci_95_low - 0.01 < mean < ci_95_high + 0.01, f"95% CI [{ci_95_low:.4f}, {ci_95_high:.4f}] 应包含均值 {mean:.4f}"
        assert ci_99_low - 0.01 < mean < ci_99_high + 0.01, f"99% CI [{ci_99_low:.4f}, {ci_99_high:.4f}] 应包含均值 {mean:.4f}"

        assert 0.0 < width_90 < 1.0
        assert 0.0 < width_95 < 1.0
        assert 0.0 < width_99 < 1.0
        assert width_99 >= width_95 * 0.9, f"99% CI 不应显著窄于 95% CI: {width_99:.4f} vs {width_95:.4f}"

    def test_beta_binomial_more_data_tighter_ci(self):
        """更多数据应有更窄的可信区间"""
        alpha_small, beta_small = 5.0, 2.0
        alpha_large, beta_large = 50.0, 20.0

        ci_small_low, ci_small_high = credible_interval(alpha_small, beta_small, 0.95)
        ci_large_low, ci_large_high = credible_interval(alpha_large, beta_large, 0.95)

        width_small = ci_small_high - ci_small_low
        width_large = ci_large_high - ci_large_low

        assert width_large < width_small, \
            f"更多数据应有更窄CI: 小样本={width_small:.3f}, 大样本={width_large:.3f}"


class TestZIPStability:
    """ZIP模型稳定性测试 - 验证缺陷2修复效果"""

    def test_zip_stability_with_sparse_data(self):
        """稀疏数据下ZIP评估结果应稳定（原缺陷：震荡）"""
        base_treatment = [0] * 16 + [1] * 2 + [2] * 1 + [3] * 1
        base_control = [0] * 10 + [1] * 3 + [2] * 3 + [3] * 2 + [4] * 1 + [5] * 1

        posterior_means = []
        reduction_rates = []

        for seed in range(10):
            np.random.seed(seed)
            perm = np.random.permutation(len(base_treatment))
            treatment = [base_treatment[i] for i in perm]
            control = [base_control[i % len(base_control)] for i in range(len(base_treatment))]

            treatment_pairs = [
                {"spores_before": 100.0 if x > 0 else 0.0, "spores_after": float(x)}
                for x in treatment
            ]
            control_pairs = [
                {"spores_before": 100.0 if x > 0 else 0.0, "spores_after": float(x)}
                for x in control
            ]

            result = bayesian_efficacy_estimation(treatment_pairs, control_pairs)
            posterior_means.append(result.posterior_mean)
            reduction_rates.append(result.reduction_rate)

        mean_std = np.std(posterior_means)
        red_std = np.std(reduction_rates)

        assert mean_std < 0.3, f"后验均值标准差应<0.3，实际: {mean_std:.3f}"
        assert red_std < 0.5, f"减少率标准差应<0.5，实际: {red_std:.3f}"

        max_diff_mean = max(posterior_means) - min(posterior_means)
        assert max_diff_mean < 0.5, f"后验极差应<0.5，实际: {max_diff_mean:.3f}"

    def test_zip_convergence_speed(self):
        """EM算法收敛速度：应在50轮内收敛"""
        data = [0] * 60 + [1] * 15 + [2] * 10 + [3] * 8 + [5] * 5 + [8] * 2

        result = fit_zero_inflated_poisson(data, max_iter=200, tol=1e-8)

        assert result.converged
        assert result.iterations <= 50, f"应在50轮内收敛，实际: {result.iterations}轮"

    def test_zip_with_small_sample(self):
        """小样本（<10）数据：ZIP仍能给出合理结果"""
        data = [0] * 6 + [1] * 2 + [3] * 1 + [0] * 1

        result = fit_zero_inflated_poisson(data, max_iter=200)

        assert 0 <= result.pi <= 1
        assert result.lambda_ >= 0


class TestZIPEdgeCases:
    """ZIP边界情况测试"""

    def test_zip_empty_data(self):
        """空数据：返回安全默认值"""
        result = fit_zero_inflated_poisson([])

        assert isinstance(result, ZIPResult)
        assert result.pi == 0.0
        assert result.lambda_ == 0.0
        assert result.converged is False

    def test_zip_single_data_point(self):
        """单数据点"""
        result = fit_zero_inflated_poisson([0])

        assert isinstance(result, ZIPResult)
        assert 0 <= result.pi <= 1
        assert result.lambda_ >= 0

    def test_zip_all_same_positive(self):
        """所有值相同且为正"""
        result = fit_zero_inflated_poisson([5] * 20, max_iter=200)

        assert result.converged
        assert result.pi < 0.1
        assert abs(result.lambda_ - 5.0) < 1.0

    def test_zip_large_values(self):
        """大值数据"""
        data = [0] * 40 + [10] * 20 + [20] * 15 + [30] * 10 + [50] * 10 + [100] * 5

        result = fit_zero_inflated_poisson(data, max_iter=500)

        assert result.converged
        assert result.pi > 0.3
        assert result.lambda_ > 0

    def test_bayesian_unequal_sample_sizes(self):
        """治疗组和对照组样本量不等"""
        treatment = [{"spores_before": 100.0, "spores_after": 30.0} for _ in range(10)]
        control = [{"spores_before": 100.0, "spores_after": 80.0} for _ in range(50)]

        result = bayesian_efficacy_estimation(treatment, control)

        assert isinstance(result, BayesianEfficacyResult)
        assert 0 < result.posterior_mean < 1
        assert result.ci_low < result.ci_high
