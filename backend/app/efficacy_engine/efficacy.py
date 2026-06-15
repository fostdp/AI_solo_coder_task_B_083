"""
贝叶斯药效评估算法
基于Beta-Binomial共轭先验模型评估三方药方的防霉效果
"""
import math
import logging
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BayesianEfficacyResult:
    """贝叶斯药效评估结果"""
    posterior_alpha: float
    posterior_beta: float
    posterior_mean: float
    posterior_var: float
    ci_low: float
    ci_high: float
    reduction_rate: float
    sample_size: int


def beta_binomial_posterior(alpha: float, beta: float, successes: int, trials: int) -> Tuple[float, float]:
    """
    计算Beta-Binomial共轭后验分布参数
    
    Args:
        alpha: Beta分布先验参数alpha
        beta: Beta分布先验参数beta
        successes: 成功次数（孢子减少数）
        trials: 试验次数（总样本数）
    
    Returns:
        (posterior_alpha, posterior_beta) 后验分布参数
    """
    if trials < 0:
        raise ValueError("trials不能为负数")
    if successes < 0 or successes > trials:
        raise ValueError("successes必须在0到trials之间")
    
    posterior_alpha = alpha + successes
    posterior_beta = beta + trials - successes
    
    return posterior_alpha, posterior_beta


def _incomplete_beta(x: float, a: float, b: float) -> float:
    """
    正则化不完全Beta函数 I_x(a, b) 的数值近似
    使用连分式近似算法
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    
    log_beta_ab = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    log_beta_axb = math.lgamma(a + b) - math.lgamma(a + 1) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_beta_axb) * _beta_cf(x, a, b) / a
    else:
        return 1.0 - math.exp(log_beta_ab) * math.exp(log_beta_axb) * _beta_cf(1.0 - x, b, a) / b


def _beta_cf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 3e-7) -> float:
    """连分式算法计算Beta函数"""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < eps:
        d = eps
    d = 1.0 / d
    h = d
    
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < eps:
            d = eps
        c = 1.0 + aa / c
        if abs(c) < eps:
            c = eps
        d = 1.0 / d
        h *= d * c
        
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < eps:
            d = eps
        c = 1.0 + aa / c
        if abs(c) < eps:
            c = eps
        d = 1.0 / d
        delta = d * c
        h *= delta
        
        if abs(delta - 1.0) < eps:
            break
    
    return h


def _beta_ppf(p: float, a: float, b: float) -> float:
    """
    Beta分布分位数函数（逆CDF）
    使用牛顿迭代法近似求解
    """
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    
    x = 0.5
    if a > 1 and b > 1:
        x = (a - 1/3) / (a + b - 2/3)
    
    for _ in range(100):
        f = _incomplete_beta(x, a, b) - p
        if abs(f) < 1e-10:
            break
        
        log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        pdf = math.exp(log_beta) * (x ** (a - 1)) * ((1 - x) ** (b - 1))
        if pdf < 1e-10:
            break
        
        dx = f / pdf
        x_new = x - dx
        
        if x_new <= 0.0:
            x = x / 2.0
        elif x_new >= 1.0:
            x = (x + 1.0) / 2.0
        else:
            x = x_new
    
    return max(0.0, min(1.0, x))


def credible_interval(alpha: float, beta: float, level: float = 0.95) -> Tuple[float, float]:
    """
    计算Beta分布的可信区间
    
    Args:
        alpha: Beta分布参数alpha
        beta: Beta分布参数beta
        level: 可信水平，默认0.95
    
    Returns:
        (ci_low, ci_high) 可信区间上下限
    """
    if alpha <= 0 or beta <= 0:
        raise ValueError("alpha和beta必须为正数")
    if level <= 0 or level >= 1:
        raise ValueError("level必须在(0, 1)之间")
    
    tail_prob = (1.0 - level) / 2.0
    ci_low = _beta_ppf(tail_prob, alpha, beta)
    ci_high = _beta_ppf(1.0 - tail_prob, alpha, beta)
    
    return ci_low, ci_high


def bayesian_efficacy_estimation(
    treatment_data: List[Dict[str, Any]],
    control_data: List[Dict[str, Any]],
    prior_alpha: float = 2.0,
    prior_beta: float = 2.0,
    ci_level: float = 0.95
) -> BayesianEfficacyResult:
    """
    贝叶斯药效评估
    
    比较治疗组与对照组的霉菌孢子浓度，使用Beta-Binomial共轭先验模型
    评估药方的防霉效果。
    
    Args:
        treatment_data: 治疗组数据，每个元素包含spores_before和spores_after
        control_data: 对照组数据，每个元素包含spores_before和spores_after
        prior_alpha: Beta先验分布参数alpha，默认2.0
        prior_beta: Beta先验分布参数beta，默认2.0
        ci_level: 可信区间水平，默认0.95
    
    Returns:
        BayesianEfficacyResult 包含所有药效评估指标
    """
    if not treatment_data:
        raise ValueError("治疗组数据不能为空")
    if not control_data:
        raise ValueError("对照组数据不能为空")
    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("先验参数必须为正数")
    
    treatment_before = sum(d["spores_before"] for d in treatment_data) / len(treatment_data)
    treatment_after = sum(d["spores_after"] for d in treatment_data) / len(treatment_data)
    control_before = sum(d["spores_before"] for d in control_data) / len(control_data)
    control_after = sum(d["spores_after"] for d in control_data) / len(control_data)
    
    if treatment_before <= 0:
        reduction_rate = 0.0
    else:
        treatment_reduction = (treatment_before - treatment_after) / treatment_before
        control_reduction = (control_before - control_after) / max(control_before, 1e-10)
        reduction_rate = max(0.0, treatment_reduction - control_reduction)
    
    n = len(treatment_data)
    
    base_reduction = 0.0
    if control_before > 0:
        base_reduction = (control_before - control_after) / control_before
    
    success_count = 0
    for d in treatment_data:
        if d["spores_before"] > 0:
            reduction = (d["spores_before"] - d["spores_after"]) / d["spores_before"]
            if reduction > base_reduction:
                success_count += 1
    
    posterior_alpha, posterior_beta = beta_binomial_posterior(
        prior_alpha, prior_beta, success_count, n
    )
    
    posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
    posterior_var = (posterior_alpha * posterior_beta) / (
        (posterior_alpha + posterior_beta) ** 2 * (posterior_alpha + posterior_beta + 1)
    )
    
    ci_low, ci_high = credible_interval(posterior_alpha, posterior_beta, ci_level)
    
    result = BayesianEfficacyResult(
        posterior_alpha=posterior_alpha,
        posterior_beta=posterior_beta,
        posterior_mean=posterior_mean,
        posterior_var=posterior_var,
        ci_low=ci_low,
        ci_high=ci_high,
        reduction_rate=reduction_rate,
        sample_size=n
    )
    
    logger.debug(f"贝叶斯评估完成: 成功率={success_count}/{n}, "
                 f"后验均值={posterior_mean:.4f}, "
                 f"95%CI=[{ci_low:.4f}, {ci_high:.4f}], "
                 f"相对减少率={reduction_rate:.4f}")
    
    return result


def calculate_reduction_rate(spores_before: float, spores_after: float) -> float:
    """
    计算孢子减少率
    
    Args:
        spores_before: 处理前孢子浓度
        spores_after: 处理后孢子浓度
    
    Returns:
        减少率 (0-1之间)
    """
    if spores_before <= 0:
        return 0.0
    return max(0.0, min(1.0, (spores_before - spores_after) / spores_before))
