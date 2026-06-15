"""
病害传播网络单元测试
覆盖边权重衰减、传播概率、图结构、蒙特卡洛模拟等场景
"""
import pytest
import math
import time
import threading
import numpy as np
from typing import List, Dict, Any, Tuple
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

with patch("clickhouse_driver.Client"):
    from app.spread_model.seir import (
        ShelfGraph,
        SEIRModel,
        SEIRState,
        SimulationResult,
        compute_edge_weight,
        simulate_spread,
        identify_hotspots,
        ShelfNode,
        Edge,
    )
    from app.workers.spread_worker import (
        SpreadSimulationWorker,
        _run_single_simulation,
        AveragedResult,
        MonteCarloConfig,
        MonteCarloSimulationResult,
    )


class TestEdgeWeightDecay:
    """边权重衰减测试 - 传播概率随距离衰减"""

    def test_edge_weight_monotonic_decay(self):
        """边权重应随距离增加单调递减"""
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }
        ventilation = 0.5

        weights = []
        for d in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            w = compute_edge_weight(d, ventilation, params)
            weights.append(w)

        for i in range(len(weights) - 1):
            assert weights[i] > weights[i + 1], \
                f"距离增加权重应递减: d={i + 1}时w={weights[i]:.4f}, d={i + 2}时w={weights[i + 1]:.4f}"

    def test_edge_weight_exponential_decay(self):
        """边权重应按指数衰减 exp(-α·d)"""
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }
        ventilation = 0.5

        w1 = compute_edge_weight(1.0, ventilation, params)
        w2 = compute_edge_weight(2.0, ventilation, params)

        ratio = w2 / w1
        expected_ratio = math.exp(-0.01 * (2.0 - 1.0))

        assert abs(ratio - expected_ratio) < 0.01, \
            f"衰减比应≈{expected_ratio:.4f}，实际: {ratio:.4f}"

    def test_edge_weight_ventilation_effect(self):
        """通风越好，传播概率越高（正相关）"""
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }
        distance = 1.0

        w_low = compute_edge_weight(distance, 0.1, params)
        w_medium = compute_edge_weight(distance, 0.5, params)
        w_high = compute_edge_weight(distance, 0.9, params)

        assert w_low < w_medium < w_high, \
            f"通风越好权重应越高: {w_low:.4f} < {w_medium:.4f} < {w_high:.4f}"

    def test_edge_weight_bounds(self):
        """边权重应在[0,1]范围内"""
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }

        test_cases = [
            (0.1, 0.0),
            (0.1, 1.0),
            (5.0, 0.0),
            (5.0, 1.0),
            (1.0, 0.5),
            (0.5, 0.9),
        ]

        for d, v in test_cases:
            w = compute_edge_weight(d, v, params)
            assert 0.0 <= w <= 1.0, f"d={d}, v={v}: w={w} 超出[0,1]范围"

    def test_edge_weight_adjacency_bonus(self):
        """邻接奖励系数应增大权重"""
        distance = 1.0
        ventilation = 0.5

        w_with_bonus = compute_edge_weight(distance, ventilation, {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        })

        w_without_bonus = compute_edge_weight(distance, ventilation, {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        })

        assert w_with_bonus > w_without_bonus, \
            f"邻接奖励应增大权重: {w_with_bonus:.4f} > {w_without_bonus:.4f}"

    def test_edge_weight_zero_distance(self):
        """零距离应返回有效权重（不自环）"""
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }

        w = compute_edge_weight(0.0, 0.5, params)

        assert 0 < w <= 1.0


class TestGraphStructure:
    """图结构测试"""

    @pytest.fixture
    def default_layout(self):
        return {
            "total_shelves": 10,
            "columns": 5,
            "layers": 6,
        }

    @pytest.fixture
    def default_edge_params(self):
        return {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }

    def test_graph_node_count(self, default_layout, default_edge_params):
        """图节点数量应与配置一致"""
        graph = ShelfGraph(default_layout, default_edge_params)

        assert len(graph.nodes) == 10

    def test_graph_node_ids(self, default_layout, default_edge_params):
        """节点ID格式应正确：SHELF-01, SHELF-02, ..."""
        graph = ShelfGraph(default_layout, default_edge_params)

        expected_ids = [f"SHELF-{i:02d}" for i in range(1, 11)]
        actual_ids = sorted(graph.nodes.keys())

        assert actual_ids == expected_ids

    def test_graph_edges_only_nearby(self, default_layout, default_edge_params):
        """只有距离≤2.0的书架之间有边"""
        graph = ShelfGraph(default_layout, default_edge_params)

        for edge in graph.edges:
            from_node = graph.nodes[edge.from_shelf]
            to_node = graph.nodes[edge.to_shelf]

            d_row = abs(from_node.row - to_node.row)
            d_col = abs(from_node.col - to_node.col)
            distance = math.sqrt(d_row ** 2 + d_col ** 2)

            assert distance <= 2.0, \
                f"边 {edge.from_shelf}→{edge.to_shelf} 距离={distance:.2f} > 2.0"

    def test_graph_adjacency_symmetric(self, default_layout, default_edge_params):
        """邻接关系应是对称的（无向图）"""
        graph = ShelfGraph(default_layout, default_edge_params)

        for from_id, neighbors in graph.adjacency.items():
            for to_id, weight in neighbors:
                found = False
                for back_id, back_weight in graph.adjacency[to_id]:
                    if back_id == from_id and abs(back_weight - weight) < 1e-10:
                        found = True
                        break
                assert found, f"邻接不对称: {from_id}→{to_id} 但反向不存在"

    def test_graph_no_self_loops(self, default_layout, default_edge_params):
        """图不应有自环边"""
        graph = ShelfGraph(default_layout, default_edge_params)

        for edge in graph.edges:
            assert edge.from_shelf != edge.to_shelf, \
                f"发现自环边: {edge.from_shelf}→{edge.to_shelf}"

        for node_id, neighbors in graph.adjacency.items():
            for neighbor_id, _ in neighbors:
                assert neighbor_id != node_id

    def test_graph_get_neighbors(self, default_layout, default_edge_params):
        """获取邻居方法应返回正确的邻居列表"""
        graph = ShelfGraph(default_layout, default_edge_params)

        neighbors = graph.get_neighbors("SHELF-01")

        assert isinstance(neighbors, list)
        for neighbor_id, weight in neighbors:
            assert isinstance(neighbor_id, str)
            assert isinstance(weight, float)
            assert 0 <= weight <= 1
            assert neighbor_id in graph.nodes

    def test_graph_spread_directions(self, default_layout, default_edge_params):
        """传播方向应返回所有边的列表"""
        graph = ShelfGraph(default_layout, default_edge_params)

        directions = graph.get_spread_directions()

        assert len(directions) == len(graph.edges)
        for from_id, to_id, weight in directions:
            assert from_id in graph.nodes
            assert to_id in graph.nodes
            assert 0 <= weight <= 1

    def test_graph_to_dict(self, default_layout, default_edge_params):
        """转换为字典应包含所有必要信息"""
        graph = ShelfGraph(default_layout, default_edge_params)

        d = graph.to_dict()

        assert "nodes" in d
        assert "edges" in d
        assert "spread_directions" in d
        assert len(d["nodes"]) == len(graph.nodes)
        assert len(d["edges"]) == len(graph.edges)


class TestSEIRDynamics:
    """SEIR模型动力学测试"""

    @pytest.fixture
    def seir_params(self):
        return {"beta": 0.3, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}

    def test_seir_state_conservation(self, seir_params):
        """SEIR状态总和应保持≈1（归一化）"""
        model = SEIRModel(seir_params)
        initial = SEIRState(S=1.0, E=0.0, I=0.0, R=0.0)

        for _ in range(100):
            new_state = model.step(initial)
            total = new_state.S + new_state.E + new_state.I + new_state.R
            assert abs(total - 1.0) < 1e-10, f"状态和={total:.6f} ≠ 1"
            initial = new_state

    def test_seir_state_bounds(self, seir_params):
        """所有状态值应在[0,1]范围内"""
        model = SEIRModel(seir_params)
        initial = SEIRState(S=0.5, E=0.2, I=0.2, R=0.1)

        for _ in range(100):
            new_state = model.step(initial)
            for attr in ['S', 'E', 'I', 'R']:
                val = getattr(new_state, attr)
                assert 0.0 <= val <= 1.0, f"{attr}={val} 超出[0,1]"
            initial = new_state

    def test_seir_infection_growth(self, seir_params):
        """存在感染压力时，E+I应先增长后下降"""
        model = SEIRModel(seir_params)
        state = SEIRState(S=0.99, E=0.01, I=0.0, R=0.0)

        infection_probs = []
        for _ in range(50):
            state = model.step(state, infection_pressure=0.1)
            infection_probs.append(state.infection_prob)

        peak = max(infection_probs)
        assert peak >= 0.009, f"感染概率应有峰值: max={peak:.4f}"

    def test_seir_infection_prob_property(self):
        """infection_prob应为E+I"""
        state = SEIRState(S=0.5, E=0.2, I=0.2, R=0.1)

        assert abs(state.infection_prob - 0.4) < 1e-10

    def test_seir_state_to_dict(self):
        """转换为字典应包含所有字段"""
        state = SEIRState(S=0.5, E=0.2, I=0.2, R=0.1)
        d = state.to_dict()

        assert d == {"S": 0.5, "E": 0.2, "I": 0.2, "R": 0.1}

    def test_seir_beta_effect(self):
        """β越高，传播越快"""
        params_low = {"beta": 0.1, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}
        params_high = {"beta": 0.5, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}

        model_low = SEIRModel(params_low)
        model_high = SEIRModel(params_high)

        state_low = SEIRState(S=0.9, E=0.1, I=0.0, R=0.0)
        state_high = SEIRState(S=0.9, E=0.1, I=0.0, R=0.0)

        for _ in range(20):
            state_low = model_low.step(state_low)
            state_high = model_high.step(state_high)

        assert state_high.I > state_low.I, \
            f"高β应有更高感染率: high={state_high.I:.4f} > low={state_low.I:.4f}"


class TestSpreadSimulation:
    """传播模拟测试"""

    @pytest.fixture
    def test_graph(self):
        layout = {"total_shelves": 6, "columns": 3, "layers": 1}
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        return ShelfGraph(layout, params)

    @pytest.fixture
    def seir_params(self):
        return {"beta": 0.3, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}

    def test_simulation_returns_results_per_day_per_shelf(self, test_graph, seir_params):
        """模拟结果应为每天×每个书架的条目"""
        results = simulate_spread(
            graph=test_graph,
            initial_infected=["SHELF-01"],
            days=10,
            seir_params=seir_params,
            edge_params={},
        )

        expected_count = 10 * len(test_graph.nodes)
        assert len(results) == expected_count, \
            f"结果数量应为{expected_count}，实际{len(results)}"

    def test_simulation_initial_infected(self, test_graph, seir_params):
        """初始感染书架第1天应为I≈1"""
        results = simulate_spread(
            graph=test_graph,
            initial_infected=["SHELF-01"],
            days=10,
            seir_params=seir_params,
            edge_params={},
        )

        day1_results = [r for r in results if r.day == 1]
        shelf01 = [r for r in day1_results if r.shelf_id == "SHELF-01"][0]

        assert shelf01.state.I >= 0.85, f"初始感染书架I应接近1，实际: {shelf01.state.I:.4f}"

    def test_simulation_no_initial_infection(self, test_graph, seir_params):
        """无初始感染时，所有书架应保持S=1"""
        results = simulate_spread(
            graph=test_graph,
            initial_infected=[],
            days=5,
            seir_params=seir_params,
            edge_params={},
        )

        for r in results:
            assert abs(r.state.S - 1.0) < 1e-10, f"{r.shelf_id} day{r.day}: S={r.state.S:.4f} ≠ 1"

    def test_simulation_spreads_to_neighbors(self, test_graph):
        """感染应传播到相邻书架（使用较高传播参数）"""
        high_transmission_params = {"beta": 0.8, "sigma": 0.5, "gamma": 0.05, "mu": 0.001}
        results = simulate_spread(
            graph=test_graph,
            initial_infected=["SHELF-01"],
            days=30,
            seir_params=high_transmission_params,
            edge_params={},
        )

        neighbors = [n[0] for n in test_graph.get_neighbors("SHELF-01")]

        neighbor_infected = False
        for r in results:
            if r.shelf_id in neighbors and r.state.infection_prob > 0.1:
                neighbor_infected = True
                break

        assert neighbor_infected, "感染应传播到相邻书架"

    def test_simulation_deterministic(self, test_graph, seir_params):
        """相同参数应得到相同结果（确定性）"""
        results1 = simulate_spread(
            graph=test_graph,
            initial_infected=["SHELF-01"],
            days=20,
            seir_params=seir_params,
            edge_params={},
        )

        results2 = simulate_spread(
            graph=test_graph,
            initial_infected=["SHELF-01"],
            days=20,
            seir_params=seir_params,
            edge_params={},
        )

        for r1, r2 in zip(results1, results2):
            assert r1.day == r2.day
            assert r1.shelf_id == r2.shelf_id
            assert abs(r1.state.S - r2.state.S) < 1e-10
            assert abs(r1.state.E - r2.state.E) < 1e-10
            assert abs(r1.state.I - r2.state.I) < 1e-10
            assert abs(r1.state.R - r2.state.R) < 1e-10

    def test_simulation_isolated_node(self, seir_params):
        """无邻接边时传播停止（高距离阈值创建无连接图）"""
        layout = {"total_shelves": 4, "columns": 4, "layers": 1}
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 3.0,
        }
        graph = ShelfGraph(layout, params)

        for shelf_id in graph.nodes:
            assert len(graph.get_neighbors(shelf_id)) == 0, f"{shelf_id} 应无邻居"

        results = simulate_spread(
            graph=graph,
            initial_infected=["SHELF-01"],
            days=50,
            seir_params=seir_params,
            edge_params={},
        )

        shelf04_results = [r for r in results if r.shelf_id == "SHELF-04"]
        for r in shelf04_results:
            assert r.state.infection_prob < 0.01, \
                f"孤立节点SHELF-04不应被感染: day{r.day}, prob={r.state.infection_prob:.4f}"

    def test_hotspot_identification(self, test_graph, seir_params):
        """热点识别应正确标记高风险书架"""
        results = simulate_spread(
            graph=test_graph,
            initial_infected=["SHELF-01"],
            days=30,
            seir_params=seir_params,
            edge_params={},
        )

        hotspots = identify_hotspots(results, threshold=0.5)

        assert len(hotspots) > 0, "应识别到至少1个热点"
        for h in hotspots:
            assert h["max_infection_prob"] >= 0.5
            assert "shelf_id" in h
            assert "first_day" in h
            assert h["is_hotspot"] is True


class TestMonteCarloSimulation:
    """蒙特卡洛模拟测试 - ProcessPoolExecutor"""

    @pytest.fixture
    def default_layout(self):
        return {"total_shelves": 6, "columns": 3, "layers": 1}

    @pytest.fixture
    def default_edge_params(self):
        return {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }

    @pytest.fixture
    def seir_params(self):
        return {"beta": 0.3, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}

    @pytest.fixture
    def worker(self):
        worker = SpreadSimulationWorker(max_workers=2)
        yield worker
        worker.shutdown()

    def test_single_simulation_function(self, default_layout, default_edge_params, seir_params):
        """模块级模拟函数应可序列化并返回正确结果"""
        result_dicts = _run_single_simulation(
            shelf_layout=default_layout,
            edge_params=default_edge_params,
            initial_infected=["SHELF-01"],
            days=5,
            seir_params=seir_params,
        )

        assert isinstance(result_dicts, list)
        assert len(result_dicts) == 5 * 6

        for r in result_dicts:
            assert "day" in r
            assert "shelf_id" in r
            assert "S" in r
            assert "E" in r
            assert "I" in r
            assert "R" in r

    def test_monte_carlo_reduces_variance(self, worker, default_layout, default_edge_params, seir_params):
        """蒙特卡洛模拟（多次平均）应降低结果方差"""
        config = MonteCarloConfig(
            num_simulations=10,
            days=20,
            shelf_layout=default_layout,
            edge_params=default_edge_params,
            seir_params=seir_params,
        )

        single_run = _run_single_simulation(
            shelf_layout=default_layout,
            edge_params=default_edge_params,
            initial_infected=["SHELF-01"],
            days=20,
            seir_params=seir_params,
        )

        averaged_result = worker.run_monte_carlo_simulation(
            initial_infected=["SHELF-01"],
            config=config,
        )

        assert isinstance(averaged_result, MonteCarloSimulationResult)
        assert len(averaged_result.results) == 20 * 6

        shelf01_day20_single = [r for r in single_run if r["day"] == 20 and r["shelf_id"] == "SHELF-01"][0]
        shelf01_day20_avg = [r for r in averaged_result.results if r.day == 20 and r.shelf_id == "SHELF-01"][0]

        assert 0 <= shelf01_day20_avg.state.S <= 1
        assert 0 <= shelf01_day20_avg.state.I <= 1

    def test_monte_carlo_parallel(self, worker, default_layout, default_edge_params, seir_params):
        """并行模拟多个初始点应返回对应数量结果"""
        config = MonteCarloConfig(
            num_simulations=5,
            days=10,
            shelf_layout=default_layout,
            edge_params=default_edge_params,
            seir_params=seir_params,
        )

        initial_points = [["SHELF-01"], ["SHELF-03"], ["SHELF-06"]]

        results = worker.run_parallel_simulations(
            initial_infected_list=initial_points,
            config=config,
        )

        assert len(results) == 3
        for result in results:
            assert isinstance(result, MonteCarloSimulationResult)
            assert len(result.results) == 10 * 6

    def test_monte_carlo_config_validation(self):
        """蒙特卡洛配置应验证参数"""
        config = MonteCarloConfig(
            num_simulations=10,
            days=30,
            shelf_layout={},
            edge_params={},
            seir_params={},
        )

        assert config.num_simulations == 10
        assert config.days == 30
        assert config.confidence_level == 0.95

    def test_worker_shutdown(self, default_layout, default_edge_params, seir_params):
        """Worker应能正确关闭"""
        worker = SpreadSimulationWorker(max_workers=2)
        config = MonteCarloConfig(
            num_simulations=3,
            days=5,
            shelf_layout=default_layout,
            edge_params=default_edge_params,
            seir_params=seir_params,
        )

        result = worker.run_monte_carlo_simulation(["SHELF-01"], config)
        assert result is not None

        worker.shutdown()

        with pytest.raises(Exception):
            worker.run_monte_carlo_simulation(["SHELF-01"], config)


class TestNetworkPropagation:
    """网络传播特性测试"""

    def test_propagation_speed_depends_on_beta(self):
        """传播速度取决于β值"""
        layout = {"total_shelves": 4, "columns": 2, "layers": 1}
        edge_params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.9,
            "shelf_distance_default": 1.0,
        }
        graph = ShelfGraph(layout, edge_params)

        params_fast = {"beta": 0.6, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}
        params_slow = {"beta": 0.1, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}

        results_fast = simulate_spread(graph, ["SHELF-01"], 20, params_fast, {})
        results_slow = simulate_spread(graph, ["SHELF-01"], 20, params_slow, {})

        def get_day_all_infected(results, threshold=0.3):
            for day in range(1, 21):
                day_results = [r for r in results if r.day == day]
                infected = [r for r in day_results if r.state.infection_prob > threshold]
                if len(infected) >= len(graph.nodes) * 0.8:
                    return day
            return 999

        day_fast = get_day_all_infected(results_fast)
        day_slow = get_day_all_infected(results_slow)

        assert day_fast <= day_slow, \
            f"高β应传播更快: fast={day_fast}天, slow={day_slow}天"

    def test_ventilation_affects_propagation(self):
        """高通风应加速传播"""
        layout = {"total_shelves": 4, "columns": 2, "layers": 1}
        seir_params = {"beta": 0.3, "sigma": 0.2, "gamma": 0.1, "mu": 0.01}

        params_high_vent = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.9,
            "shelf_distance_default": 1.0,
        }

        params_low_vent = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.1,
            "shelf_distance_default": 1.0,
        }

        graph_high = ShelfGraph(layout, params_high_vent)
        graph_low = ShelfGraph(layout, params_low_vent)

        results_high = simulate_spread(graph_high, ["SHELF-01"], 15, seir_params, {})
        results_low = simulate_spread(graph_low, ["SHELF-01"], 15, seir_params, {})

        day15_high = [r for r in results_high if r.day == 15]
        day15_low = [r for r in results_low if r.day == 15]

        avg_infected_high = sum(r.state.I for r in day15_high) / len(day15_high)
        avg_infected_low = sum(r.state.I for r in day15_low) / len(day15_low)

        assert avg_infected_high >= avg_infected_low * 0.8, \
            f"高通风应有更多传播: high={avg_infected_high:.4f}, low={avg_infected_low:.4f}"
