"""
SEIR霉菌传播模型
基于SEIR传染病模型的书架间霉菌传播动力学
"""
import logging
import math
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ShelfNode:
    """书架节点"""
    shelf_id: str
    row: int
    col: int
    layer: int
    position: Tuple[int, int, int]
    ventilation: float = 0.5


@dataclass
class Edge:
    """边连接"""
    from_shelf: str
    to_shelf: str
    weight: float
    distance: float
    ventilation: float


@dataclass
class SEIRState:
    """SEIR状态"""
    S: float = 1.0
    E: float = 0.0
    I: float = 0.0
    R: float = 0.0

    @property
    def infection_prob(self) -> float:
        return self.E + self.I

    def to_dict(self) -> Dict[str, float]:
        return {"S": self.S, "E": self.E, "I": self.I, "R": self.R}


@dataclass
class SimulationResult:
    """模拟结果"""
    day: int
    shelf_id: str
    state: SEIRState
    spread_from: str = ""
    edge_weight: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day": self.day,
            "shelf_id": self.shelf_id,
            **self.state.to_dict(),
            "infection_prob": self.state.infection_prob,
            "spread_from": self.spread_from,
            "edge_weight": self.edge_weight,
        }


class ShelfGraph:
    """
    书架图结构
    节点 = 书架，边 = 邻接关系带权重
    """

    def __init__(self, shelf_layout: Dict[str, Any], edge_params: Dict[str, Any]):
        self.shelf_layout = shelf_layout
        self.edge_params = edge_params
        self.nodes: Dict[str, ShelfNode] = {}
        self.edges: List[Edge] = []
        self.adjacency: Dict[str, List[Tuple[str, float]]] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        """从shelf_layout配置构建图"""
        total_shelves = self.shelf_layout.get("total_shelves", 10)
        cols = self.shelf_layout.get("columns", 5)
        layers = self.shelf_layout.get("layers", 6)
        ventilation_default = self.edge_params.get("ventilation_default", 0.5)
        distance_default = self.edge_params.get("shelf_distance_default", 1.0)

        for i in range(total_shelves):
            shelf_id = f"SHELF-{i + 1:02d}"
            row = i // cols
            col = i % cols
            layer = 0

            node = ShelfNode(
                shelf_id=shelf_id,
                row=row,
                col=col,
                layer=layer,
                position=(row, col, layer),
                ventilation=ventilation_default
            )
            self.nodes[shelf_id] = node
            self.adjacency[shelf_id] = []

        shelf_ids = list(self.nodes.keys())
        for i, from_id in enumerate(shelf_ids):
            from_node = self.nodes[from_id]
            for to_id in shelf_ids[i + 1:]:
                to_node = self.nodes[to_id]
                distance = self._compute_distance(from_node.position, to_node.position, distance_default)
                if distance <= 2.0:
                    avg_ventilation = (from_node.ventilation + to_node.ventilation) / 2.0
                    weight = compute_edge_weight(distance, avg_ventilation, self.edge_params)

                    edge = Edge(
                        from_shelf=from_id,
                        to_shelf=to_id,
                        weight=weight,
                        distance=distance,
                        ventilation=avg_ventilation
                    )
                    self.edges.append(edge)
                    self.adjacency[from_id].append((to_id, weight))
                    self.adjacency[to_id].append((from_id, weight))

        logger.info(f"书架图构建完成: {len(self.nodes)}个节点, {len(self.edges)}条边")

    def _compute_distance(
        self,
        pos1: Tuple[int, int, int],
        pos2: Tuple[int, int, int],
        default_distance: float
    ) -> float:
        """计算两个书架之间的曼哈顿距离"""
        d_row = abs(pos1[0] - pos2[0])
        d_col = abs(pos1[1] - pos2[1])
        d_layer = abs(pos1[2] - pos2[2])

        if d_row == 0 and d_col == 0 and d_layer == 0:
            return 0.0

        distance = math.sqrt(d_row ** 2 + d_col ** 2 + d_layer ** 2)
        return max(distance, default_distance)

    def get_neighbors(self, shelf_id: str) -> List[Tuple[str, float]]:
        """获取邻居书架及权重"""
        return self.adjacency.get(shelf_id, [])

    def get_spread_directions(self) -> List[Tuple[str, str, float]]:
        """获取传播方向箭头列表，用于前端展示"""
        return [(e.from_shelf, e.to_shelf, e.weight) for e in self.edges]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "nodes": [
                {
                    "shelf_id": n.shelf_id,
                    "row": n.row,
                    "col": n.col,
                    "ventilation": n.ventilation,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "from": e.from_shelf,
                    "to": e.to_shelf,
                    "weight": e.weight,
                    "distance": e.distance,
                }
                for e in self.edges
            ],
            "spread_directions": self.get_spread_directions(),
        }


class SEIRModel:
    """
    SEIR传染病模型
    S - 易感(Susceptible)
    E - 潜伏(Exposed)
    I - 感染(Infectious)
    R - 恢复(Recovered)
    """

    def __init__(self, params: Dict[str, float]):
        self.beta = params.get("beta", 0.3)
        self.sigma = params.get("sigma", 0.2)
        self.gamma = params.get("gamma", 0.1)
        self.mu = params.get("mu", 0.01)

    def step(self, state: SEIRState, infection_pressure: float = 0.0) -> SEIRState:
        """
        执行一个时间步长的SEIR动力学更新

        微分方程（离散时间步长）:
        S[t+1] = S[t] - beta * S[t] * I[t] + mu * (1 - S[t])
        E[t+1] = E[t] + beta * S[t] * I[t] - (sigma + mu) * E[t]
        I[t+1] = I[t] + sigma * E[t] - (gamma + mu) * I[t]
        R[t+1] = R[t] + gamma * I[t] - mu * R[t]
        """
        S = state.S
        E = state.E
        I = state.I
        R = state.R

        effective_infection = I + infection_pressure
        new_infections = self.beta * S * effective_infection

        new_S = S - new_infections + self.mu * (1 - S)
        new_E = E + new_infections - (self.sigma + self.mu) * E
        new_I = I + self.sigma * E - (self.gamma + self.mu) * I
        new_R = R + self.gamma * I - self.mu * R

        new_S = max(0.0, min(1.0, new_S))
        new_E = max(0.0, min(1.0, new_E))
        new_I = max(0.0, min(1.0, new_I))
        new_R = max(0.0, min(1.0, new_R))

        total = new_S + new_E + new_I + new_R
        if total > 0:
            new_S /= total
            new_E /= total
            new_I /= total
            new_R /= total

        return SEIRState(S=new_S, E=new_E, I=new_I, R=new_R)


def compute_edge_weight(
    distance: float,
    ventilation: float,
    params: Dict[str, Any]
) -> float:
    """
    计算边的传播概率权重

    公式:
    weight = exp(-distance_factor * distance) * (ventilation_factor * ventilation + (1 - ventilation_factor)) * adjacency_bonus

    参数:
        distance: 书架间距离
        ventilation: 平均通风系数 (0-1)
        params: 边权重参数字典

    返回:
        边权重值 (0-1)
    """
    distance_factor = params.get("distance_factor", 0.01)
    ventilation_factor = params.get("ventilation_factor", 0.7)
    adjacency_bonus = params.get("adjacency_bonus", 1.5)

    distance_term = math.exp(-distance_factor * distance)
    ventilation_term = ventilation_factor * ventilation + (1 - ventilation_factor)
    weight = distance_term * ventilation_term * adjacency_bonus

    return max(0.0, min(1.0, weight))


def simulate_spread(
    graph: ShelfGraph,
    initial_infected: List[str],
    days: int,
    seir_params: Dict[str, float],
    edge_params: Dict[str, Any]
) -> List[SimulationResult]:
    """
    运行完整的传播模拟

    参数:
        graph: 书架图
        initial_infected: 初始感染书架ID列表
        days: 模拟天数
        seir_params: SEIR模型参数
        edge_params: 边权重参数

    返回:
        所有天的模拟结果列表
    """
    model = SEIRModel(seir_params)

    states: Dict[str, SEIRState] = {}
    for shelf_id in graph.nodes.keys():
        if shelf_id in initial_infected:
            states[shelf_id] = SEIRState(S=0.0, E=0.0, I=1.0, R=0.0)
        else:
            states[shelf_id] = SEIRState(S=1.0, E=0.0, I=0.0, R=0.0)

    results: List[SimulationResult] = []

    for day in range(1, days + 1):
        new_states: Dict[str, SEIRState] = {}
        spread_sources: Dict[str, Tuple[str, float]] = {}

        for shelf_id, current_state in states.items():
            infection_pressure = 0.0
            max_weight = 0.0
            spread_from = ""

            for neighbor_id, edge_weight in graph.get_neighbors(shelf_id):
                neighbor_state = states[neighbor_id]
                neighbor_I = neighbor_state.I
                pressure = neighbor_I * edge_weight
                infection_pressure += pressure

                if pressure > max_weight and neighbor_I > 0.1:
                    max_weight = edge_weight
                    spread_from = neighbor_id

            new_state = model.step(current_state, infection_pressure)
            new_states[shelf_id] = new_state

            if spread_from and (new_state.E > 0.01 or new_state.I > 0.01):
                spread_sources[shelf_id] = (spread_from, max_weight)

        for shelf_id, new_state in new_states.items():
            spread_from, edge_weight = spread_sources.get(shelf_id, ("", 0.0))
            result = SimulationResult(
                day=day,
                shelf_id=shelf_id,
                state=new_state,
                spread_from=spread_from,
                edge_weight=edge_weight,
            )
            results.append(result)

        states = new_states

    logger.info(f"传播模拟完成: {days}天, {len(results)}条结果")
    return results


def identify_hotspots(
    simulation_results: List[SimulationResult],
    threshold: float = 0.5
) -> List[Dict[str, Any]]:
    """
    识别高风险热点书架

    参数:
        simulation_results: 模拟结果列表
        threshold: 感染概率阈值

    返回:
        热点书架列表，包含最大感染概率及出现的天数
    """
    shelf_max_infection: Dict[str, Dict[str, Any]] = {}

    for result in simulation_results:
        shelf_id = result.shelf_id
        infection_prob = result.state.infection_prob

        if shelf_id not in shelf_max_infection:
            shelf_max_infection[shelf_id] = {
                "shelf_id": shelf_id,
                "max_infection_prob": 0.0,
                "first_day": None,
                "is_hotspot": False,
            }

        if infection_prob > shelf_max_infection[shelf_id]["max_infection_prob"]:
            shelf_max_infection[shelf_id]["max_infection_prob"] = infection_prob

        if infection_prob >= threshold and shelf_max_infection[shelf_id]["first_day"] is None:
            shelf_max_infection[shelf_id]["first_day"] = result.day
            shelf_max_infection[shelf_id]["is_hotspot"] = True

    hotspots = [
        info for info in shelf_max_infection.values()
        if info["is_hotspot"]
    ]

    hotspots.sort(key=lambda x: x["max_infection_prob"], reverse=True)

    logger.info(f"识别到 {len(hotspots)} 个热点书架")
    return hotspots
