"""
Spread Simulator gRPC 客户端
支持 gRPC 调用 Go 服务，当 gRPC 不可用时自动降级到 Python 原生实现
"""
import logging
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import grpc
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    logger.warning("gRPC not available, will use Python native implementation")

try:
    from . import spread_pb2
    from . import spread_pb2_grpc
    PROTO_AVAILABLE = True
except ImportError:
    PROTO_AVAILABLE = False
    logger.warning("Proto generated files not available, will use Python native implementation")

try:
    from backend.app.spread_model.seir import (
        ShelfGraph,
        simulate_spread as python_simulate_spread,
        identify_hotspots as python_identify_hotspots,
        SEIRState,
        SimulationResult,
    )
    PYTHON_NATIVE_AVAILABLE = True
except ImportError:
    PYTHON_NATIVE_AVAILABLE = False
    logger.error("Python native SEIR implementation not available")


@dataclass
class ClientSEIRState:
    S: float
    E: float
    I: float
    R: float
    infection_prob: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "S": self.S,
            "E": self.E,
            "I": self.I,
            "R": self.R,
            "infection_prob": self.infection_prob,
        }


@dataclass
class ClientSimulationResult:
    day: int
    shelf_id: str
    state: ClientSEIRState
    spread_from: str
    edge_weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day": self.day,
            "shelf_id": self.shelf_id,
            **self.state.to_dict(),
            "spread_from": self.spread_from,
            "edge_weight": self.edge_weight,
        }


@dataclass
class ClientHotspot:
    shelf_id: str
    max_infection_prob: float
    first_day: int
    is_hotspot: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shelf_id": self.shelf_id,
            "max_infection_prob": self.max_infection_prob,
            "first_day": self.first_day,
            "is_hotspot": self.is_hotspot,
        }


@dataclass
class ClientDirection:
    from_shelf: str
    to_shelf: str
    weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_shelf": self.from_shelf,
            "to_shelf": self.to_shelf,
            "weight": self.weight,
        }


@dataclass
class ClientSimulationResponse:
    results: List[ClientSimulationResult]
    hotspots: List[ClientHotspot]
    directions: List[ClientDirection]
    used_grpc: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "hotspots": [h.to_dict() for h in self.hotspots],
            "directions": [d.to_dict() for d in self.directions],
            "used_grpc": self.used_grpc,
        }


class SpreadSimulatorClient:
    """
    Spread Simulator 客户端
    优先使用 gRPC 调用 Go 服务，失败时自动降级到 Python 原生实现
    """

    def __init__(
        self,
        grpc_host: str = "localhost",
        grpc_port: int = 50051,
        prefer_grpc: bool = True,
        timeout: float = 10.0,
    ):
        self.grpc_host = grpc_host
        self.grpc_port = grpc_port
        self.prefer_grpc = prefer_grpc
        self.timeout = timeout
        self._channel = None
        self._stub = None
        self._grpc_available = GRPC_AVAILABLE and PROTO_AVAILABLE

    def _connect_grpc(self) -> bool:
        """建立 gRPC 连接"""
        if not self._grpc_available:
            return False

        try:
            if self._channel is None:
                target = f"{self.grpc_host}:{self.grpc_port}"
                self._channel = grpc.insecure_channel(
                    target,
                    options=[
                        ("grpc.max_send_message_length", 100 * 1024 * 1024),
                        ("grpc.max_receive_message_length", 100 * 1024 * 1024),
                    ],
                )
                self._stub = spread_pb2_grpc.SpreadSimulatorStub(self._channel)
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to gRPC server: {e}")
            self._channel = None
            self._stub = None
            return False

    def _grpc_simulate_spread(
        self,
        shelves_layout: Dict[str, Any],
        initial_infected: List[str],
        days: int,
        seir_params: Dict[str, float],
        edge_params: Dict[str, Any],
    ) -> Optional[ClientSimulationResponse]:
        """使用 gRPC 调用 Go 服务进行模拟"""
        if not self.prefer_grpc or not self._connect_grpc():
            return None

        try:
            request = spread_pb2.SimulationRequest(
                shelves_layout=spread_pb2.ShelvesLayout(
                    total_shelves=shelves_layout.get("total_shelves", 10),
                    columns=shelves_layout.get("columns", 5),
                    layers=shelves_layout.get("layers", 6),
                ),
                initial_infected=initial_infected,
                days=days,
                seir_params=spread_pb2.SEIRParams(
                    beta=seir_params.get("beta", 0.3),
                    sigma=seir_params.get("sigma", 0.2),
                    gamma=seir_params.get("gamma", 0.1),
                    mu=seir_params.get("mu", 0.01),
                ),
                edge_params=spread_pb2.EdgeWeightParams(
                    distance_factor=edge_params.get("distance_factor", 0.01),
                    ventilation_factor=edge_params.get("ventilation_factor", 0.7),
                    adjacency_bonus=edge_params.get("adjacency_bonus", 1.5),
                    ventilation_default=edge_params.get("ventilation_default", 0.5),
                    shelf_distance_default=edge_params.get("shelf_distance_default", 1.0),
                ),
            )

            response = self._stub.SimulateSpread(request, timeout=self.timeout)

            results = [
                ClientSimulationResult(
                    day=r.day,
                    shelf_id=r.shelf_id,
                    state=ClientSEIRState(
                        S=r.state.S,
                        E=r.state.E,
                        I=r.state.I,
                        R=r.state.R,
                        infection_prob=r.state.infection_prob,
                    ),
                    spread_from=r.spread_from,
                    edge_weight=r.edge_weight,
                )
                for r in response.results
            ]

            hotspots = [
                ClientHotspot(
                    shelf_id=h.shelf_id,
                    max_infection_prob=h.max_infection_prob,
                    first_day=h.first_day,
                    is_hotspot=h.is_hotspot,
                )
                for h in response.hotspots
            ]

            directions = [
                ClientDirection(
                    from_shelf=d.from_shelf,
                    to_shelf=d.to_shelf,
                    weight=d.weight,
                )
                for d in response.directions
            ]

            logger.info("Successfully used gRPC service for simulation")
            return ClientSimulationResponse(
                results=results,
                hotspots=hotspots,
                directions=directions,
                used_grpc=True,
            )

        except grpc.RpcError as e:
            logger.warning(f"gRPC call failed: {e}, falling back to Python native")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error in gRPC call: {e}, falling back to Python native")
            return None

    def _python_simulate_spread(
        self,
        shelves_layout: Dict[str, Any],
        initial_infected: List[str],
        days: int,
        seir_params: Dict[str, float],
        edge_params: Dict[str, Any],
    ) -> Optional[ClientSimulationResponse]:
        """使用 Python 原生实现进行模拟"""
        if not PYTHON_NATIVE_AVAILABLE:
            logger.error("Python native implementation not available")
            return None

        try:
            graph = ShelfGraph(shelves_layout, edge_params)
            results = python_simulate_spread(
                graph=graph,
                initial_infected=initial_infected,
                days=days,
                seir_params=seir_params,
                edge_params=edge_params,
            )
            hotspots = python_identify_hotspots(results)
            directions = graph.get_spread_directions()

            client_results = [
                ClientSimulationResult(
                    day=r.day,
                    shelf_id=r.shelf_id,
                    state=ClientSEIRState(
                        S=r.state.S,
                        E=r.state.E,
                        I=r.state.I,
                        R=r.state.R,
                        infection_prob=r.state.infection_prob,
                    ),
                    spread_from=r.spread_from,
                    edge_weight=r.edge_weight,
                )
                for r in results
            ]

            client_hotspots = [
                ClientHotspot(
                    shelf_id=h["shelf_id"],
                    max_infection_prob=h["max_infection_prob"],
                    first_day=h["first_day"] or 0,
                    is_hotspot=h["is_hotspot"],
                )
                for h in hotspots
            ]

            client_directions = [
                ClientDirection(
                    from_shelf=d[0],
                    to_shelf=d[1],
                    weight=d[2],
                )
                for d in directions
            ]

            logger.info("Used Python native implementation for simulation")
            return ClientSimulationResponse(
                results=client_results,
                hotspots=client_hotspots,
                directions=client_directions,
                used_grpc=False,
            )

        except Exception as e:
            logger.error(f"Python native simulation failed: {e}")
            return None

    def simulate_spread(
        self,
        shelves_layout: Dict[str, Any],
        initial_infected: List[str],
        days: int,
        seir_params: Optional[Dict[str, float]] = None,
        edge_params: Optional[Dict[str, Any]] = None,
    ) -> ClientSimulationResponse:
        """
        运行传播模拟

        优先使用 gRPC 调用 Go 服务，失败时自动降级到 Python 原生实现

        参数:
            shelves_layout: 书架布局配置，包含 total_shelves, columns, layers
            initial_infected: 初始感染书架ID列表
            days: 模拟天数
            seir_params: SEIR模型参数，默认值: beta=0.3, sigma=0.2, gamma=0.1, mu=0.01
            edge_params: 边权重参数，默认值: distance_factor=0.01, ventilation_factor=0.7,
                         adjacency_bonus=1.5, ventilation_default=0.5, shelf_distance_default=1.0

        返回:
            ClientSimulationResponse 对象，包含 results, hotspots, directions, used_grpc

        异常:
            RuntimeError: 当 gRPC 和 Python 原生实现都不可用时抛出
        """
        if seir_params is None:
            seir_params = {
                "beta": 0.3,
                "sigma": 0.2,
                "gamma": 0.1,
                "mu": 0.01,
            }

        if edge_params is None:
            edge_params = {
                "distance_factor": 0.01,
                "ventilation_factor": 0.7,
                "adjacency_bonus": 1.5,
                "ventilation_default": 0.5,
                "shelf_distance_default": 1.0,
            }

        if not initial_infected:
            raise ValueError("initial_infected cannot be empty")

        if days <= 0:
            raise ValueError("days must be positive")

        response = None

        if self.prefer_grpc and self._grpc_available:
            response = self._grpc_simulate_spread(
                shelves_layout,
                initial_infected,
                days,
                seir_params,
                edge_params,
            )

        if response is None:
            response = self._python_simulate_spread(
                shelves_layout,
                initial_infected,
                days,
                seir_params,
                edge_params,
            )

        if response is None:
            raise RuntimeError(
                "Both gRPC and Python native implementations are unavailable. "
                "Please ensure either gRPC dependencies are installed and the server "
                "is running, or the Python SEIR module is available."
            )

        return response

    def close(self):
        """关闭 gRPC 连接"""
        if self._channel is not None:
            self._channel.close()
            self._channel = None
            self._stub = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
