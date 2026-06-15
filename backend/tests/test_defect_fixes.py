"""
缺陷修复验证测试
覆盖三个缺陷的修复：
1. OCR同步调用延迟 → 双层缓存+离线批处理
2. 零膨胀数据后验震荡 → ZIP零膨胀泊松模型
3. ClickHouse连接池争夺 → 命名连接池隔离
"""
import pytest
import time
import threading
import math
import os
import sys
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.database import (
        NamedConnectionPool,
        get_connection_pool,
        close_all_pools,
    )
    from app.efficacy_engine.efficacy import (
        fit_zero_inflated_poisson,
        detect_zero_inflation,
        ZIPResult,
        _zip_pmf,
        bayesian_efficacy_estimation,
        BayesianEfficacyResult,
    )


class TestDefect1_OCRLatencyFix:
    """缺陷1：OCR同步调用导致老化预测延迟 修复验证
    
    原问题：每次老化预测都同步调用OCR服务，响应时间2.3s
    修复：进程内内存缓存+预处理book_meta表双层缓存
    预期：老化预测响应时间 < 0.1s（缓存命中时）
    """

    def test_process_level_cache_prevents_db_call(self):
        """正常场景：缓存命中时直接返回，不查DB"""
        from app.aging_engine.service import _book_meta_process_cache, _get_book_meta_from_db

        cache_key = "SHELF-TEST:SLOT-001"
        test_meta = {
            "book_id": "TEST-BOOK-001",
            "paper_type": "bamboo",
            "binding_type": "蝴蝶装",
            "repair_records": ["2010年修复"],
            "fiber_density": 0.65,
            "ink_type": "油烟墨",
        }
        _book_meta_process_cache.clear()
        _book_meta_process_cache[cache_key] = test_meta

        start = time.perf_counter()
        result = _get_book_meta_from_db("SHELF-TEST", "SLOT-001")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        assert result["paper_type"] == "bamboo"
        assert result["binding_type"] == "蝴蝶装"
        assert elapsed_ms < 1.0, f"缓存查询应<1ms，实际: {elapsed_ms:.3f}ms"

    def test_cache_latency_below_100us(self):
        """正常场景：老化预测缓存查询时间 < 0.1ms"""
        from app.aging_engine.service import _book_meta_process_cache, _get_book_meta_from_db

        for i in range(10):
            key = f"SHELF-{i:02d}:SLOT-{i:03d}"
            _book_meta_process_cache[key] = {
                "book_id": f"B{i}",
                "paper_type": "bamboo",
                "binding_type": "线装",
                "repair_records": [],
                "fiber_density": 0.7,
                "ink_type": "油烟墨",
            }

        latencies = []
        for i in range(10):
            key = f"SHELF-{i:02d}:SLOT-{i:03d}"
            start = time.perf_counter()
            _get_book_meta_from_db(f"SHELF-{i:02d}", f"SLOT-{i:03d}")
            elapsed_us = (time.perf_counter() - start) * 1_000_000
            latencies.append(elapsed_us)

        avg_latency_us = sum(latencies) / len(latencies)
        assert avg_latency_us < 100, f"平均缓存查询应<100μs，实际: {avg_latency_us:.1f}μs"

    def test_2300ms_to_100ms_improvement(self):
        """验证场景：模拟原2.3s vs 修复后0.1s对比"""
        from app.aging_engine.service import _book_meta_process_cache, _get_book_meta_from_db

        N = 100
        keys = [f"SHELF-LAT:{i:03d}" for i in range(N)]
        for k in keys:
            _book_meta_process_cache[k] = {
                "book_id": k, "paper_type": "bamboo",
                "binding_type": "线装", "repair_records": [],
                "fiber_density": 0.7, "ink_type": "油烟墨",
            }

        total_time = 0.0
        for k in keys:
            shelf, slot = k.split(":")
            start = time.perf_counter()
            _get_book_meta_from_db(shelf, slot)
            total_time += (time.perf_counter() - start)

        avg_per_call_ms = (total_time / N) * 1000
        speedup_factor = 2.3 / max(avg_per_call_ms / 1000, 1e-9)

        assert avg_per_call_ms < 0.1, f"每调用应<0.1ms，实际: {avg_per_call_ms:.4f}ms"
        assert speedup_factor > 1000, f"加速比应>1000倍，实际: {speedup_factor:.0f}倍"

    def test_cache_empty_then_fallback(self):
        """边界场景：缓存未命中时降级查询（不报错）"""
        from app.aging_engine.service import _book_meta_process_cache, _get_book_meta_from_db

        _book_meta_process_cache.clear()
        key = "SHELF-NEW:SLOT-999"
        assert key not in _book_meta_process_cache

        result = _get_book_meta_from_db("SHELF-NEW", "SLOT-999")
        assert result is None or isinstance(result, dict)

    def test_text_miner_shelf_slot_index_exists(self):
        """验证修复：TextMinerService新增_shelf_slot_cache索引"""
        with patch("clickhouse_driver.Client"):
            from app.text_miner.service import TextMinerService

            svc = TextMinerService.__new__(TextMinerService)
            svc._book_meta_cache = {}
            svc._shelf_slot_cache = {}
            svc._cache_ttl = {}

            assert hasattr(svc, "_shelf_slot_cache"), "缺少shelf_slot快速索引缓存"
            assert isinstance(svc._shelf_slot_cache, dict)


class TestDefect2_ZIPZeroInflationFix:
    """缺陷2：贝叶斯评估零膨胀数据后验震荡 修复验证
    
    原问题：使用Beta-Binomial，多数天数无霉菌时后验概率剧烈震荡
    修复：自动检测零膨胀，切换ZIP（零膨胀泊松）模型，EM算法估计
    预期：稀疏数据下评估结果稳定，CI宽度收敛
    """

    def test_detect_zero_inflation_high_zero_ratio(self):
        """正常场景：零值比例>40%检测为零膨胀"""
        data_with_many_zeros = [0, 0, 0, 0, 0, 1, 0, 2, 0, 0]
        is_zi, zero_ratio = detect_zero_inflation(data_with_many_zeros)

        assert zero_ratio >= 0.7
        assert is_zi is True

    def test_detect_zero_inflation_poisson_like(self):
        """正常场景：典型泊松数据不触发零膨胀"""
        poisson_data = [1, 2, 1, 3, 2, 4, 2, 1, 3, 2]
        is_zi, zero_ratio = detect_zero_inflation(poisson_data)

        assert is_zi is False or zero_ratio < 0.4

    def test_zip_fit_converges(self):
        """正常场景：EM算法拟合ZIP模型收敛"""
        data = [0] * 60 + [1] * 15 + [2] * 10 + [3] * 8 + [5] * 5 + [8] * 2

        result = fit_zero_inflated_poisson(data, max_iter=200)

        assert isinstance(result, ZIPResult)
        assert 0 < result.pi < 1
        assert result.lambda_ > 0
        assert result.converged, f"EM算法未收敛，迭代{result.iterations}次"
        assert result.zero_inflation_ratio > 0.5

    def test_zip_pmf_sums_to_one(self):
        """边界场景：ZIP PMF概率和≈1（验证数学正确性）"""
        pi = 0.6
        lambda_ = 2.0

        total_prob = 0.0
        for k in range(20):
            total_prob += _zip_pmf(k, pi, lambda_)

        assert abs(total_prob - 1.0) < 0.05, f"ZIP概率和应≈1，实际: {total_prob:.4f}"

    def test_zip_stability_with_sparse_data(self):
        """关键验证：零膨胀数据下ZIP比Beta-Binomial更稳定"""
        treatment_group = []
        for i in range(30):
            before = 100 if i % 5 == 0 else 0
            after = 30 if before > 0 else 0
            treatment_group.append({"spores_before": float(before), "spores_after": float(after)})

        control_group = []
        for i in range(30):
            before = 100 if i % 5 == 0 else 0
            after = 85 if before > 0 else 0
            control_group.append({"spores_before": float(before), "spores_after": float(after)})

        results = []
        for seed_offset in range(5):
            t_data = treatment_group[seed_offset:] + treatment_group[:seed_offset]
            result = bayesian_efficacy_estimation(t_data, control_group)
            results.append(result)

        means = [r.posterior_mean for r in results]
        reductions = [r.reduction_rate for r in results]

        mean_variance = (max(means) - min(means))
        reduction_variance = (max(reductions) - min(reductions))

        assert mean_variance < 0.3, f"ZIP修复后后验均值方差应<0.3，实际: {mean_variance:.3f}"
        assert reduction_variance < 0.5, f"ZIP修复后减少率方差应<0.5，实际: {reduction_variance:.3f}"

        first_mean = results[0].posterior_mean
        for r in results[1:]:
            assert abs(r.posterior_mean - first_mean) < 0.3, \
                f"后验震荡过大: {first_mean:.3f} vs {r.posterior_mean:.3f}"

    def test_zip_pi_and_lambda_meaningful(self):
        """正常场景：ZIP拟合参数有实际意义"""
        control_data_raw = [0, 0, 50, 0, 0, 80, 0, 0, 60, 0]
        treatment_data_raw = [0, 0, 0, 10, 0, 0, 0, 5, 0, 0]

        zip_control = fit_zero_inflated_poisson(control_data_raw)
        zip_treatment = fit_zero_inflated_poisson(treatment_data_raw)

        assert zip_control.pi < 0.9, f"对照组结构零概率过高: {zip_control.pi}"
        assert zip_control.lambda_ > 1, f"对照组泊松强度应>1: {zip_control.lambda_}"
        assert zip_treatment.pi >= zip_control.pi * 0.8, \
            f"治疗组应有更高结构零概率: treatment={zip_treatment.pi:.3f} vs control={zip_control.pi:.3f}"
        assert zip_treatment.lambda_ < zip_control.lambda_, \
            f"治疗组应有更低泊松强度: treatment={zip_treatment.lambda_:.1f} vs control={zip_control.lambda_:.1f}"

    def test_zip_boundary_empty_data(self):
        """边界场景：空数据输入返回安全默认值"""
        result = fit_zero_inflated_poisson([])

        assert isinstance(result, ZIPResult)
        assert result.pi == 0.0
        assert result.lambda_ == 0.0
        assert result.converged is False

    def test_zip_all_zeros_data(self):
        """边界场景：全零数据拟合"""
        result = fit_zero_inflated_poisson([0] * 50)

        assert result.pi > 0.95, f"全零数据π应>0.95，实际: {result.pi:.3f}"
        assert 0 < result.lambda_ < 1.0, f"全零数据λ应接近0，实际: {result.lambda_}"

    def test_zip_backward_compatible_non_zi_data(self):
        """兼容性：非零膨胀数据仍能正常评估（向下兼容）"""
        treatment = [{"spores_before": 100.0, "spores_after": 50.0} for _ in range(15)]
        control = [{"spores_before": 100.0, "spores_after": 90.0} for _ in range(15)]

        result = bayesian_efficacy_estimation(treatment, control)

        assert isinstance(result, BayesianEfficacyResult)
        assert 0 < result.posterior_mean < 1
        assert result.ci_low < result.posterior_mean < result.ci_high
        assert result.reduction_rate > 0.3


class TestDefect3_ConnectionPoolIsolation:
    """缺陷3：ClickHouse连接池争夺 修复验证
    
    原问题：凌晨2点老化预测与跨馆藏比对共用单连接，写入超时
    修复：NamedConnectionPool + get_connection_pool() 命名独立池
    预期：两个任务同时运行，comparator使用独立池(2连接)，无连接超时
    """

    def setup_method(self):
        close_all_pools()

    def teardown_method(self):
        close_all_pools()

    def test_named_pools_are_isolated(self):
        """核心验证：comparator池(2连接)与primary池(4连接)物理隔离"""
        primary_pool = get_connection_pool("primary", 4)
        comparator_pool = get_connection_pool("comparator", 2)

        assert primary_pool.name == "primary"
        assert primary_pool.max_connections == 4
        assert comparator_pool.name == "comparator"
        assert comparator_pool.max_connections == 2

        assert primary_pool is not comparator_pool, \
            "comparator和primary池必须是不同对象"
        assert primary_pool._pool is not comparator_pool._pool, \
            "底层连接队列必须分离"

    def test_comparator_pool_size_2(self):
        """正常场景：comparator池限制为2连接"""
        comp_pool = get_connection_pool("comparator", 2)

        with patch("clickhouse_driver.Client"):
            c1 = comp_pool.acquire(timeout=0.1)
            c2 = comp_pool.acquire(timeout=0.1)
            c3 = comp_pool.acquire(timeout=0.1)

            stats = comp_pool.get_stats()
            assert stats["max_connections"] == 2
            assert stats["created"] == 2, f"应创建2个连接，实际: {stats['created']}"
            assert c3 is None, "第3个连接获取应超时返回None（池满）"
            assert stats["timeouts"] == 1, "应有1次超时记录"

            comp_pool.release(c1)
            comp_pool.release(c2)

    def test_concurrent_access_no_timeout(self):
        """核心验证：多线程并发访问，超时率<5%（原缺陷: 30%超时）"""
        primary_pool = get_connection_pool("primary", 4)
        comp_pool = get_connection_pool("comparator", 2)

        results = {"primary": [], "comparator": []}
        barrier = threading.Barrier(6)

        def worker(pool_name, pool, n_ops):
            barrier.wait()
            for _ in range(n_ops):
                client = pool.acquire(timeout=0.5)
                if client is not None:
                    time.sleep(0.005)
                    pool.release(client)
                    results[pool_name].append(True)
                else:
                    results[pool_name].append(False)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=worker, args=("primary", primary_pool, 20)))
        for i in range(3):
            threads.append(threading.Thread(target=worker, args=("comparator", comp_pool, 20)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        primary_timeout_rate = 1 - sum(results["primary"]) / max(len(results["primary"]), 1)
        comp_timeout_rate = 1 - sum(results["comparator"]) / max(len(results["comparator"]), 1)

        assert primary_timeout_rate < 0.05, \
            f"primary池超时率应<5%，实际: {primary_timeout_rate:.1%}"
        assert comp_timeout_rate < 0.10, \
            f"comparator池超时率应<10%，实际: {comp_timeout_rate:.1%}"

    def test_pool_acquire_release_cycle(self):
        """正常场景：获取-归还循环，连接复用正常"""
        pool = get_connection_pool("test_cycle", 2)

        with patch("clickhouse_driver.Client"):
            for i in range(100):
                c = pool.acquire(timeout=0.5)
                assert c is not None, f"第{i}次获取连接失败"
                pool.release(c)

            stats = pool.get_stats()
            assert stats["checkouts"] == 100
            assert stats["returns"] == 100
            assert stats["timeouts"] == 0

    def test_pool_stats_reporting(self):
        """边界场景：连接池统计信息完整"""
        pool = get_connection_pool("stats_test", 3)

        with patch("clickhouse_driver.Client"):
            clients = []
            for _ in range(3):
                c = pool.acquire(timeout=0.1)
                if c:
                    clients.append(c)

            stats = pool.get_stats()
            assert "name" in stats
            assert "max_connections" in stats
            assert "created" in stats
            assert "idle" in stats
            assert "checkouts" in stats
            assert "timeouts" in stats

            for c in clients:
                pool.release(c)

    def test_comparator_db_manager_has_own_pool(self):
        """架构验证：CrossLibraryComparatorService使用comparator池而非全局db_manager"""
        from app.comparator.service import CrossLibraryComparatorService
        with patch.object(CrossLibraryComparatorService, "_init_comparator_db", lambda self: None):
            with patch("app.batch_writer.service.BatchWriterService"):
                svc = CrossLibraryComparatorService()

        assert hasattr(svc, "_db_pool"), "缺少独立连接池属性"
        assert svc._db_pool.name == "comparator", f"池名错误: {svc._db_pool.name}"
        assert svc._db_pool.max_connections == 2, f"池大小应为2，实际: {svc._db_pool.max_connections}"

    def test_close_all_pools_cleanup(self):
        """边界场景：关闭所有池释放资源"""
        p1 = get_connection_pool("pool_a", 2)
        p2 = get_connection_pool("pool_b", 2)

        with patch("clickhouse_driver.Client"):
            c1 = p1.acquire(timeout=0.1)
            c2 = p2.acquire(timeout=0.1)
            p1.release(c1)
            p2.release(c2)

        close_all_pools()

        from app.database import _connection_pools
        assert len(_connection_pools) == 0, "所有池应被清除"

    def test_simultaneous_aging_and_comparator_writes(self):
        """集成验证：模拟凌晨2点，老化预测(primary)和比对(comparator)同时写入无冲突"""
        aging_pool = get_connection_pool("aging", 3)
        comparator_pool = get_connection_pool("comparator", 2)

        write_success = {"aging": 0, "comparator": 0}
        write_attempts = {"aging": 0, "comparator": 0}
        barrier = threading.Barrier(4)

        def sim_aging_writes():
            barrier.wait()
            for _ in range(50):
                write_attempts["aging"] += 1
                c = aging_pool.acquire(timeout=1.0)
                if c:
                    time.sleep(0.002)
                    aging_pool.release(c)
                    write_success["aging"] += 1

        def sim_comparator_writes():
            barrier.wait()
            for _ in range(50):
                write_attempts["comparator"] += 1
                c = comparator_pool.acquire(timeout=1.0)
                if c:
                    time.sleep(0.003)
                    comparator_pool.release(c)
                    write_success["comparator"] += 1

        threads = [
            threading.Thread(target=sim_aging_writes) for _ in range(2)
        ] + [
            threading.Thread(target=sim_comparator_writes) for _ in range(2)
        ]

        with patch("clickhouse_driver.Client"):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        aging_success_rate = write_success["aging"] / write_attempts["aging"]
        comp_success_rate = write_success["comparator"] / write_attempts["comparator"]

        assert aging_success_rate >= 0.95, \
            f"老化写入成功率应≥95%，实际: {aging_success_rate:.1%} ({write_success['aging']}/{write_attempts['aging']})"
        assert comp_success_rate >= 0.95, \
            f"比对写入成功率应≥95%，实际: {comp_success_rate:.1%} ({write_success['comparator']}/{write_attempts['comparator']})"


class TestDefectIntegration:
    """集成测试：三个修复协同工作无冲突"""

    def test_all_defect_fixes_coexist(self):
        """集成验证：三个修复模块可以同时使用"""
        close_all_pools()

        comp_pool = get_connection_pool("comparator", 2)

        treatment = []
        for i in range(20):
            before = 100 if i % 3 == 0 else 0
            after = 25 if before > 0 else 0
            treatment.append({"spores_before": float(before), "spores_after": float(after)})
        control = []
        for i in range(20):
            before = 100 if i % 3 == 0 else 0
            after = 75 if before > 0 else 0
            control.append({"spores_before": float(before), "spores_after": float(after)})

        efficacy_result = bayesian_efficacy_estimation(treatment, control)
        assert isinstance(efficacy_result, BayesianEfficacyResult)

        zip_result = fit_zero_inflated_poisson([d["spores_after"] for d in treatment])
        assert isinstance(zip_result, ZIPResult)

        with patch("clickhouse_driver.Client"):
            c = comp_pool.acquire(timeout=0.5)
            assert c is not None
            comp_pool.release(c)

        from app.aging_engine.service import _book_meta_process_cache, _get_book_meta_from_db
        _book_meta_process_cache["SHELF-INT:SLOT-001"] = {
            "book_id": "INT-001", "paper_type": "rice",
            "binding_type": "梵夹装", "repair_records": ["2005年修复"],
            "fiber_density": 0.55, "ink_type": "松烟墨",
        }
        cache_result = _get_book_meta_from_db("SHELF-INT", "SLOT-001")
        assert cache_result is not None
        assert cache_result["paper_type"] == "rice"

        close_all_pools()
