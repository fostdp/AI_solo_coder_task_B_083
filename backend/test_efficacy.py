#!/usr/bin/env python3
"""测试药效评估引擎"""
import sys
import time
sys.path.insert(0, '.')

print("=== 测试1: 模块导入 ===")
try:
    from app.efficacy_engine import EfficacyEngineService
    from app.efficacy_engine.efficacy import (
        beta_binomial_posterior,
        credible_interval,
        bayesian_efficacy_estimation,
        calculate_reduction_rate,
    )
    print("✓ 所有模块导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== 测试2: Beta-Binomial 后验计算 ===")
try:
    alpha, beta = beta_binomial_posterior(2.0, 2.0, 8, 10)
    print(f"  先验: Beta(2, 2)")
    print(f"  试验: 8次成功, 10次试验")
    print(f"  后验: Beta({alpha}, {beta})")
    posterior_mean = alpha / (alpha + beta)
    print(f"  后验均值: {posterior_mean:.4f}")
    expected_mean = 10.0 / (10.0 + 4.0)
    assert abs(posterior_mean - expected_mean) < 0.01, f"后验均值计算错误: {posterior_mean}"
    print("✓ Beta-Binomial 后验计算正确")
except Exception as e:
    print(f"✗ Beta-Binomial 后验计算失败: {e}")
    sys.exit(1)

print("\n=== 测试3: 可信区间计算 ===")
try:
    ci_low, ci_high = credible_interval(10.0, 4.0, 0.95)
    mean = 10.0 / (10.0 + 4.0)
    print(f"  Beta(10, 4) 的 95% 可信区间: [{ci_low:.4f}, {ci_high:.4f}]")
    print(f"  后验均值: {mean:.4f}")
    assert ci_low < mean < ci_high, "均值应该在可信区间内"
    assert ci_low > 0.5, f"可信区间下限过低: {ci_low}"
    assert ci_high < 0.9, f"可信区间上限过高: {ci_high}"
    assert ci_low < ci_high, "可信区间下限必须小于上限"
    
    ci_low2, ci_high2 = credible_interval(2.0, 2.0, 0.95)
    print(f"  Beta(2, 2) 的 95% 可信区间: [{ci_low2:.4f}, {ci_high2:.4f}]")
    assert ci_low2 < 0.5 < ci_high2, "Beta(2,2)的均值0.5应该在可信区间内"
    
    print("✓ 可信区间计算正确")
except Exception as e:
    print(f"✗ 可信区间计算失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== 测试4: 贝叶斯药效评估 ===")
try:
    treatment_data = [
        {"spores_before": 100.0, "spores_after": 50.0}
        for _ in range(15)
    ]
    control_data = [
        {"spores_before": 100.0, "spores_after": 85.0}
        for _ in range(15)
    ]
    
    result = bayesian_efficacy_estimation(
        treatment_data=treatment_data,
        control_data=control_data,
        prior_alpha=2.0,
        prior_beta=2.0,
        ci_level=0.95
    )
    
    print(f"  治疗组: 平均减少 {((100-50)/100)*100:.0f}%")
    print(f"  对照组: 平均减少 {((100-85)/100)*100:.0f}%")
    print(f"  后验均值: {result.posterior_mean:.4f}")
    print(f"  后验方差: {result.posterior_var:.6f}")
    print(f"  95%CI: [{result.ci_low:.4f}, {result.ci_high:.4f}]")
    print(f"  相对减少率: {result.reduction_rate:.4f}")
    print(f"  样本量: {result.sample_size}")
    
    assert result.posterior_mean > 0.5, f"后验均值应该显著大于0.5: {result.posterior_mean}"
    assert result.reduction_rate > 0.3, f"减少率应该显著: {result.reduction_rate}"
    assert result.sample_size == 15, f"样本量错误: {result.sample_size}"
    print("✓ 贝叶斯药效评估正确")
except Exception as e:
    print(f"✗ 贝叶斯药效评估失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== 测试5: 减少率计算 ===")
try:
    rate1 = calculate_reduction_rate(100, 50)
    rate2 = calculate_reduction_rate(100, 100)
    rate3 = calculate_reduction_rate(0, 0)
    
    print(f"  100->50: {rate1:.4f}")
    print(f"  100->100: {rate2:.4f}")
    print(f"  0->0: {rate3:.4f}")
    
    assert abs(rate1 - 0.5) < 0.01, f"减少率计算错误: {rate1}"
    assert rate2 == 0.0, f"减少率计算错误: {rate2}"
    assert rate3 == 0.0, f"减少率计算错误: {rate3}"
    print("✓ 减少率计算正确")
except Exception as e:
    print(f"✗ 减少率计算失败: {e}")
    sys.exit(1)

print("\n=== 测试6: 传感器模拟器处方效果 ===")
try:
    from simulator.sensor_simulator import SensorSimulator
    
    sim = SensorSimulator(prescription="none")
    original = 100.0
    result_none = sim._apply_prescription_effect(original, "none")
    print(f"  none: {original} -> {result_none:.1f}")
    assert result_none == original, f"none 处方不应该有效果: {result_none}"
    
    sim_yuncao = SensorSimulator(prescription="yuncao")
    result_yuncao = sim_yuncao._apply_prescription_effect(original, "yuncao")
    print(f"  yuncao: {original} -> {result_yuncao:.1f}")
    assert 50 <= result_yuncao <= 70, f"yuncao 效果范围错误: {result_yuncao}"
    
    sim_huangbo = SensorSimulator(prescription="huangbo")
    result_huangbo = sim_huangbo._apply_prescription_effect(original, "huangbo")
    print(f"  huangbo: {original} -> {result_huangbo:.1f}")
    assert 40 <= result_huangbo <= 60, f"huangbo 效果范围错误: {result_huangbo}"
    
    sim_yanye = SensorSimulator(prescription="yanye")
    result_yanye = sim_yanye._apply_prescription_effect(original, "yanye")
    print(f"  yanye: {original} -> {result_yanye:.1f}")
    assert 60 <= result_yanye <= 80, f"yanye 效果范围错误: {result_yanye}"
    
    print("✓ 传感器模拟器处方效果正确")
except Exception as e:
    print(f"✗ 传感器模拟器处方效果测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== 测试7: EfficacyEngineService 初始化 ===")
try:
    import asyncio
    
    service = EfficacyEngineService()
    print(f"  运行间隔: {service._run_interval}s")
    print(f"  对照组书架: {service._control_group_shelves}")
    print(f"  先验参数: Alpha={service._prior_alpha}, Beta={service._prior_beta}")
    print(f"  最小样本量: {service._min_sample_size}")
    
    summary = service.get_efficacy_summary()
    print(f"  摘要包含药方数: {len(summary['prescriptions'])}")
    assert "yuncao" in summary["prescriptions"]
    assert "huangbo" in summary["prescriptions"]
    assert "yanye" in summary["prescriptions"]
    print("✓ EfficacyEngineService 初始化正确")
except Exception as e:
    print(f"✗ EfficacyEngineService 初始化失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== 测试8: 数据收集器 ===")
try:
    service = EfficacyEngineService()
    
    for i in range(20):
        service.record_spore_data("SHELF-03", f"SLOT-A{i%6}", 100.0 - i * 2, time.time() - 3600 + i * 100)
        service.record_spore_data("SHELF-01", f"SLOT-A{i%6}", 100.0 - i * 0.5, time.time() - 3600 + i * 100)
    
    result = asyncio.run(service.evaluate_prescription("yuncao"))
    if result:
        print(f"  评估结果: 减少率={result.reduction_rate:.4f}, 后验均值={result.posterior_mean:.4f}")
        print("✓ 数据收集和评估正常")
    else:
        print("  数据不足，跳过评估（预期行为）")
        print("✓ 数据收集正常")
except Exception as e:
    print(f"✗ 数据收集器测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("所有测试通过! ✓")
print("=" * 60)
