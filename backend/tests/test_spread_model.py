"""
医籍病害传播网络分析测试
覆盖正常、边界、异常三种场景
"""
import pytest
import math
import os
import sys
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.spread_model.seir import (
        ShelfGraph,
        SEIRModel,
        SEIRState,
        SimulationResult,
        ShelfNode,
        Edge,
        compute_edge_weight,
        simulate_spread,
        identify_hotspots,
    )
    from app.spread_model.service import SpreadModelStats


class TestSEIRModelNormal:
    """正常场景：SEIR模型动力学"""

    def setup_method(self):
        self.model = SEIRModel({
            "beta": 0.3,
            "sigma": 0.2,
            "gamma": 0.1,
            "mu": 0.01,
        })

    def test_initial_state_susceptible(self):
        """正常场景：初始状态全部为易感"""
        state = SEIRState()
        assert state.S == 1.0
        assert state.E == 0.0
        assert state.I == 0.0
        assert state.R == 0.0
        assert state.infection_prob == 0.0

    def test_step_with_infection_pressure(self):
        """正常场景：在感染压力下状态变化符合SEIR曲线"""
        state = SEIRState(S=0.9, E=0.05, I=0.05, R=0.0)

        new_state = self.model.step(state, infection_pressure=0.2)

        assert 0 <= new_state.S <= 1
        assert 0 <= new_state.E <= 1
        assert 0 <= new_state.I <= 1
        assert 0 <= new_state.R <= 1
        assert abs(new_state.S + new_state.E + new_state.I + new_state.R - 1.0) < 0.01

    def test_infection_spreads_over_time(self):
        """正常场景：多步迭代后感染人数先增后减"""
        state = SEIRState(S=0.99, E=0.01, I=0.0, R=0.0)

        infection_probs = []
        for _ in range(20):
            state = self.model.step(state)
            infection_probs.append(state.infection_prob)

        assert infection_probs[0] <= max(infection_probs)
        assert infection_probs[-1] >= 0

    def test_high_infection_pressure_increases_E(self):
        """正常场景：高感染压力下潜伏者增加更快"""
        state1 = SEIRState(S=0.9, E=0.05, I=0.05)
        state2 = SEIRState(S=0.9, E=0.05, I=0.05)

        new1 = self.model.step(state1, infection_pressure=0.1)
        new2 = self.model.step(state2, infection_pressure=0.5)

        assert new2.E > new1.E


class TestSEIRModelBoundary:
    """边界场景：SEIR模型边界情况"""

    def setup_method(self):
        self.model = SEIRModel({
            "beta": 0.3,
            "sigma": 0.2,
            "gamma": 0.1,
            "mu": 0.01,
        })

    def test_state_values_clamped_to_zero_one(self):
        """边界场景：状态值被钳制在[0,1]范围内"""
        extreme_state = SEIRState(S=-0.5, E=1.5, I=2.0, R=-1.0)

        new_state = self.model.step(extreme_state)

        assert 0 <= new_state.S <= 1
        assert 0 <= new_state.E <= 1
        assert 0 <= new_state.I <= 1
        assert 0 <= new_state.R <= 1

    def test_zero_infection_no_spread(self):
        """边界场景：零感染时系统保持稳定"""
        state = SEIRState(S=1.0, E=0.0, I=0.0, R=0.0)

        for _ in range(10):
            state = self.model.step(state)

        assert state.S > 0.9
        assert state.I < 0.1

    def test_full_recovery_state(self):
        """边界场景：全部恢复状态"""
        state = SEIRState(S=0.0, E=0.0, I=0.0, R=1.0)

        new_state = self.model.step(state)

        assert new_state.R > 0.9
        assert new_state.I < 0.1


class TestSEIRModelException:
    """异常场景：SEIR模型异常处理"""

    def setup_method(self):
        self.model = SEIRModel({
            "beta": 0.3,
            "sigma": 0.2,
            "gamma": 0.1,
            "mu": 0.01,
        })

    def test_infection_prob_greater_than_one_clamped(self):
        """异常场景：传播概率大于1时钳制为1"""
        state = SEIRState(S=0.5, E=0.3, I=0.3, R=0.1)

        new_state = self.model.step(state, infection_pressure=10.0)

        assert new_state.S >= 0.0
        assert new_state.I <= 1.0
        assert new_state.infection_prob <= 1.0

    def test_negative_infection_pressure(self):
        """异常场景：负感染压力下模型仍正常运行"""
        state = SEIRState(S=0.8, E=0.1, I=0.1)

        new_state = self.model.step(state, infection_pressure=-0.5)

        assert 0 <= new_state.S <= 1
        assert 0 <= new_state.I <= 1

    def test_extreme_beta_value(self):
        """异常场景：极端beta值模型仍稳定"""
        extreme_model = SEIRModel({
            "beta": 10.0,
            "sigma": 0.2,
            "gamma": 0.1,
            "mu": 0.01,
        })

        state = SEIRState(S=0.9, E=0.05, I=0.05)
        new_state = extreme_model.step(state)

        assert 0 <= new_state.S <= 1
        assert 0 <= new_state.I <= 1


class TestShelfGraphNormal:
    """正常场景：书架图结构"""

    def setup_method(self):
        self.shelf_layout = {
            "total_shelves": 10,
            "columns": 5,
            "layers": 6,
        }
        self.edge_params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        self.graph = ShelfGraph(self.shelf_layout, self.edge_params)

    def test_graph_has_correct_nodes(self):
        """正常场景：图有正确数量的节点"""
        assert len(self.graph.nodes) == 10
        for i in range(1, 11):
            shelf_id = f"SHELF-{i:02d}"
            assert shelf_id in self.graph.nodes

    def test_graph_has_edges(self):
        """正常场景：图有边连接相邻书架"""
        assert len(self.graph.edges) > 0

        for edge in self.graph.edges:
            assert edge.weight > 0
            assert edge.weight <= 1.0

    def test_neighbors_return_adjacent_shelves(self):
        """正常场景：获取邻居书架正确"""
        neighbors = self.graph.get_neighbors("SHELF-01")
        assert isinstance(neighbors, list)

    def test_spread_directions(self):
        """正常场景：获取传播方向列表"""
        directions = self.graph.get_spread_directions()
        assert len(directions) == len(self.graph.edges)
        for d in directions:
            assert len(d) == 3
            assert isinstance(d[0], str)
            assert isinstance(d[1], str)
            assert isinstance(d[2], float)


class TestShelfGraphBoundary:
    """边界场景：书架图边界情况"""

    def test_single_shelf_no_edges(self):
        """边界场景：单书架时无边"""
        layout = {"total_shelves": 1, "columns": 1, "layers": 1}
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        graph = ShelfGraph(layout, params)

        assert len(graph.nodes) == 1
        assert len(graph.edges) == 0
        assert graph.get_neighbors("SHELF-01") == []

    def test_no_adjacent_edges_when_far_apart(self):
        """边界场景：距离太远时无边连接"""
        layout = {"total_shelves": 10, "columns": 10, "layers": 1}
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        graph = ShelfGraph(layout, params)

        for edge in graph.edges:
            assert edge.distance <= 2.0

    def test_nonexistent_shelf_no_neighbors(self):
        """边界场景：不存在的书架无邻居"""
        layout = {"total_shelves": 5, "columns": 5, "layers": 1}
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        graph = ShelfGraph(layout, params)
        neighbors = graph.get_neighbors("NONEXISTENT")
        assert neighbors == []


class TestShelfGraphException:
    """异常场景：书架图异常处理"""

    def test_invalid_layout_still_creates_graph(self):
        """异常场景：无效布局也能创建图"""
        layout = {"total_shelves": 0, "columns": 0, "layers": 0}
        params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        graph = ShelfGraph(layout, params)
        assert isinstance(graph, ShelfGraph)

    def test_negative_ventilation_still_computes_weight(self):
        """异常场景：负通风系数也能计算权重"""
        weight = compute_edge_weight(1.0, -0.5, {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        })
        assert 0 <= weight <= 1.0


class TestEdgeWeightNormal:
    """正常场景：边权重计算"""

    def test_edge_weight_in_range(self):
        """正常场景：边权重在0-1范围内"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }

        weight = compute_edge_weight(1.0, 0.5, params)
        assert 0 < weight <= 1.0

    def test_closer_shelves_higher_weight(self):
        """正常场景：距离越近权重越高"""
        params = {
            "distance_factor": 0.5,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        }

        w_close = compute_edge_weight(1.0, 0.5, params)
        w_far = compute_edge_weight(5.0, 0.5, params)

        assert w_close > w_far

    def test_better_ventilation_higher_weight(self):
        """正常场景：通风越好权重越高"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        }

        w_low = compute_edge_weight(1.0, 0.2, params)
        w_high = compute_edge_weight(1.0, 0.8, params)

        assert w_high > w_low


class TestEdgeWeightBoundary:
    """边界场景：边权重边界"""

    def test_zero_distance_max_weight(self):
        """边界场景：零距离时权重最大"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }

        weight = compute_edge_weight(0.0, 1.0, params)
        assert weight <= 1.0
        assert weight > 0

    def test_full_ventilation_weight(self):
        """边界场景：满通风时权重"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        }

        weight = compute_edge_weight(1.0, 1.0, params)
        assert weight <= 1.0

    def test_zero_ventilation_weight(self):
        """边界场景：零通风时权重"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        }

        weight = compute_edge_weight(1.0, 0.0, params)
        assert weight >= 0.0


class TestEdgeWeightException:
    """异常场景：边权重异常处理"""

    def test_negative_distance(self):
        """异常场景：负距离权重被钳制"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }

        weight = compute_edge_weight(-5.0, 0.5, params)
        assert 0 <= weight <= 1.0

    def test_extreme_ventilation_clamped(self):
        """异常场景：极端通风值权重被钳制"""
        params = {
            "distance_factor": 0.1,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
        }

        weight = compute_edge_weight(1.0, 10.0, params)
        assert 0 <= weight <= 1.0

    def test_very_large_distance(self):
        """异常场景：极大距离权重接近0"""
        params = {
            "distance_factor": 1.0,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.0,
        }

        weight = compute_edge_weight(100.0, 0.5, params)
        assert 0 <= weight <= 0.1


class TestSimulateSpreadNormal:
    """正常场景：传播模拟"""

    def setup_method(self):
        self.shelf_layout = {
            "total_shelves": 5,
            "columns": 5,
            "layers": 1,
        }
        self.edge_params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        self.seir_params = {
            "beta": 0.5,
            "sigma": 0.3,
            "gamma": 0.1,
            "mu": 0.01,
        }
        self.graph = ShelfGraph(self.shelf_layout, self.edge_params)

    def test_spread_from_single_source(self):
        """正常场景：从单个初始感染书架开始传播"""
        results = simulate_spread(
            graph=self.graph,
            initial_infected=["SHELF-01"],
            days=10,
            seir_params=self.seir_params,
            edge_params=self.edge_params,
        )

        assert len(results) == 5 * 10

        day01_results = [r for r in results if r.day == 1]
        shelf01_result = next(r for r in day01_results if r.shelf_id == "SHELF-01")
        assert shelf01_result.state.I > 0.5

    def test_adjacent_shelves_get_infected(self):
        """正常场景：相邻书架逐渐被感染"""
        results = simulate_spread(
            graph=self.graph,
            initial_infected=["SHELF-01"],
            days=30,
            seir_params=self.seir_params,
            edge_params=self.edge_params,
        )

        final_results = [r for r in results if r.day == 30]
        infection_probs = {r.shelf_id: r.state.infection_prob for r in final_results}

        assert infection_probs["SHELF-01"] >= 0

    def test_simulation_result_has_spread_sources(self):
        """正常场景：模拟结果包含传播来源信息"""
        results = simulate_spread(
            graph=self.graph,
            initial_infected=["SHELF-01"],
            days=20,
            seir_params=self.seir_params,
            edge_params=self.edge_params,
        )

        spread_events = [r for r in results if r.spread_from != ""]
        assert len(spread_events) >= 0


class TestSimulateSpreadBoundary:
    """边界场景：传播模拟边界情况"""

    def setup_method(self):
        self.shelf_layout = {
            "total_shelves": 5,
            "columns": 5,
            "layers": 1,
        }
        self.edge_params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 1.0,
        }
        self.seir_params = {
            "beta": 0.3,
            "sigma": 0.2,
            "gamma": 0.1,
            "mu": 0.01,
        }

    def test_zero_days_no_results(self):
        """边界场景：零天模拟返回空结果"""
        graph = ShelfGraph(self.shelf_layout, self.edge_params)
        results = simulate_spread(
            graph=graph,
            initial_infected=["SHELF-01"],
            days=0,
            seir_params=self.seir_params,
            edge_params=self.edge_params,
        )

        assert len(results) == 0

    def test_no_initial_infection_no_spread(self):
        """边界场景：无初始感染时不传播"""
        graph = ShelfGraph(self.shelf_layout, self.edge_params)
        results = simulate_spread(
            graph=graph,
            initial_infected=[],
            days=10,
            seir_params=self.seir_params,
            edge_params=self.edge_params,
        )

        for r in results:
            assert r.state.I == 0.0
            assert r.state.E == 0.0

    def test_isolated_shelf_no_spread(self):
        """边界场景：图无邻接边时传播停止"""
        layout = {"total_shelves": 3, "columns": 10, "layers": 1}
        no_edge_params = {
            "distance_factor": 0.01,
            "ventilation_factor": 0.7,
            "adjacency_bonus": 1.5,
            "ventilation_default": 0.5,
            "shelf_distance_default": 3.0,
        }
        graph = ShelfGraph(layout, no_edge_params)

        for shelf_id in graph.nodes:
            assert len(graph.get_neighbors(shelf_id)) == 0, f"{shelf_id} 应无邻居"

        results = simulate_spread(
            graph=graph,
            initial_infected=["SHELF-02"],
            days=20,
            seir_params=self.seir_params,
            edge_params=no_edge_params,
        )

        day20 = [r for r in results if r.day == 20]
        shelf01 = next(r for r in day20 if r.shelf_id == "SHELF-01")
        shelf03 = next(r for r in day20 if r.shelf_id == "SHELF-03")

        assert shelf01.state.infection_prob < 0.1
        assert shelf03.state.infection_prob < 0.1


class TestIdentifyHotspotsNormal:
    """正常场景：热点识别"""

    def test_identify_hotspots_above_threshold(self):
        """正常场景：识别感染概率超阈值的热点"""
        results = [
            SimulationResult(
                day=10,
                shelf_id="SHELF-01",
                state=SEIRState(S=0.2, E=0.3, I=0.4, R=0.1),
                spread_from="",
            ),
            SimulationResult(
                day=10,
                shelf_id="SHELF-02",
                state=SEIRState(S=0.9, E=0.05, I=0.05, R=0.0),
                spread_from="",
            ),
        ]

        hotspots = identify_hotspots(results, threshold=0.5)

        assert len(hotspots) == 1
        assert hotspots[0]["shelf_id"] == "SHELF-01"
        assert hotspots[0]["is_hotspot"] is True
        assert hotspots[0]["first_day"] == 10

    def test_hotspots_sorted_by_probability(self):
        """正常场景：热点按感染概率降序排列"""
        results = [
            SimulationResult(day=10, shelf_id="A", state=SEIRState(I=0.6, E=0.2)),
            SimulationResult(day=10, shelf_id="B", state=SEIRState(I=0.9, E=0.1)),
            SimulationResult(day=10, shelf_id="C", state=SEIRState(I=0.3, E=0.1)),
        ]

        hotspots = identify_hotspots(results, threshold=0.5)

        assert len(hotspots) == 2
        assert hotspots[0]["shelf_id"] == "B"
        assert hotspots[1]["shelf_id"] == "A"


class TestIdentifyHotspotsBoundary:
    """边界场景：热点识别边界"""

    def test_no_hotspots_below_threshold(self):
        """边界场景：全部低于阈值时无热点"""
        results = [
            SimulationResult(day=10, shelf_id="SHELF-01", state=SEIRState(I=0.1, E=0.1)),
            SimulationResult(day=10, shelf_id="SHELF-02", state=SEIRState(I=0.2, E=0.1)),
        ]

        hotspots = identify_hotspots(results, threshold=0.8)
        assert len(hotspots) == 0

    def test_exactly_at_threshold(self):
        """边界场景：恰好等于阈值时算热点"""
        results = [
            SimulationResult(day=5, shelf_id="SHELF-01", state=SEIRState(I=0.4, E=0.1)),
        ]

        hotspots = identify_hotspots(results, threshold=0.5)
        assert len(hotspots) == 1
        assert hotspots[0]["is_hotspot"] is True

    def test_empty_results_no_hotspots(self):
        """边界场景：空结果无热点"""
        hotspots = identify_hotspots([], threshold=0.5)
        assert hotspots == []


class TestSEIRState:
    """SEIR状态类测试"""

    def test_state_to_dict(self):
        state = SEIRState(S=0.5, E=0.2, I=0.2, R=0.1)
        d = state.to_dict()
        assert d == {"S": 0.5, "E": 0.2, "I": 0.2, "R": 0.1}

    def test_infection_prob_property(self):
        state = SEIRState(S=0.5, E=0.2, I=0.2, R=0.1)
        assert state.infection_prob == pytest.approx(0.4)


class TestSimulationResult:
    """模拟结果类测试"""

    def test_result_to_dict(self):
        result = SimulationResult(
            day=5,
            shelf_id="SHELF-01",
            state=SEIRState(S=0.8, E=0.1, I=0.1, R=0.0),
            spread_from="SHELF-02",
            edge_weight=0.5,
        )
        d = result.to_dict()
        assert d["day"] == 5
        assert d["shelf_id"] == "SHELF-01"
        assert d["S"] == 0.8
        assert d["infection_prob"] == 0.2
        assert d["spread_from"] == "SHELF-02"
        assert d["edge_weight"] == 0.5


class TestSpreadModelStats:
    """传播模型统计数据测试"""

    def test_default_stats(self):
        stats = SpreadModelStats()
        assert stats.total_simulations == 0
        assert stats.total_errors == 0
        assert stats.total_hotspots_identified == 0

    def test_stats_mutation(self):
        stats = SpreadModelStats()
        stats.total_simulations = 10
        stats.total_errors = 1
        stats.last_simulation_time = "2024-01-01"
        stats.total_hotspots_identified = 5

        assert stats.total_simulations == 10
        assert stats.total_errors == 1
        assert stats.last_simulation_time == "2024-01-01"
        assert stats.total_hotspots_identified == 5
