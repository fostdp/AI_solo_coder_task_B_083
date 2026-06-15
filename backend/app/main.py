"""
古代医学文献馆藏微环境监测系统 - 主入口
协调各模块通信，提供REST API和WebSocket接口
"""
import asyncio
import json
import time
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from clickhouse_driver import Client

from loguru import logger

from .core.config import config
from .core.logging_setup import setup_loguru_logging
from .core.metrics import metrics
from .core.queue_manager import queue_manager
from .core.messages import (
    AgingPredictionRequest,
    MoldPredictionRequest,
    AlertMessage,
    SensorData,
)

from .ingest import IngestService
from .batch_writer import BatchWriterService
from .aging_engine import AgingEngineService
from .mold_engine import MoldEngineService
from .alerter import AlerterService
from .text_miner import TextMinerService
from .efficacy_engine import EfficacyEngineService
from .comparator import CrossLibraryComparatorService
from .spread_model import SpreadModelService

try:
    from services.comparator_service.ipc_client import (
        ComparatorServiceClient,
        init_comparator_client,
        get_comparator_client,
    )
    _COMPARATOR_CLIENT_AVAILABLE = True
except ImportError:
    try:
        import sys
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(BASE_DIR / "services" / "comparator-service"))
        from ipc_client import (
            ComparatorServiceClient,
            init_comparator_client,
            get_comparator_client,
        )
        _COMPARATOR_CLIENT_AVAILABLE = True
    except ImportError:
        _COMPARATOR_CLIENT_AVAILABLE = False
        ComparatorServiceClient = None
        init_comparator_client = None
        get_comparator_client = None

setup_loguru_logging(config)

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "efficacy-service"))
from router import router as efficacy_router


class SystemServices:
    """系统服务管理器"""

    def __init__(self):
        self.ingest: Optional[IngestService] = None
        self.batch_writer: Optional[BatchWriterService] = None
        self.aging_engine: Optional[AgingEngineService] = None
        self.mold_engine: Optional[MoldEngineService] = None
        self.alerter: Optional[AlerterService] = None
        self.text_miner: Optional[TextMinerService] = None
        self.efficacy_engine: Optional[EfficacyEngineService] = None
        self.comparator: Optional[CrossLibraryComparatorService] = None
        self.comparator_client: Optional[ComparatorServiceClient] = None
        self.spread_model: Optional[SpreadModelService] = None
        self.clickhouse_client: Optional[Client] = None

        self._running = False
        self._ws_clients: List[WebSocket] = []
        self._ws_lock = asyncio.Lock()

    async def init(self):
        """初始化所有服务"""
        logger.info("正在初始化系统服务...")

        ch_config = config.clickhouse
        self.clickhouse_client = Client(
            host=ch_config.get("host", "localhost"),
            port=ch_config.get("port", 8123),
            user=ch_config.get("user", "default"),
            password=ch_config.get("password", ""),
            database=ch_config.get("database", "ancient_medical_books"),
        )
        logger.info("ClickHouse客户端已初始化")

        self.ingest = IngestService()
        self.batch_writer = BatchWriterService(self.clickhouse_client)
        self.aging_engine = AgingEngineService()
        self.mold_engine = MoldEngineService()
        self.alerter = AlerterService()
        self.text_miner = TextMinerService()
        self.efficacy_engine = EfficacyEngineService()
        comp_config = config.comparator
        use_external = comp_config.get("use_external_service", False)
        external_url = comp_config.get("external_service_url", "http://127.0.0.1:8001")

        if _COMPARATOR_CLIENT_AVAILABLE:
            try:
                self.comparator_client = init_comparator_client(base_url=external_url)
                logger.info(f"Comparator Service 客户端已初始化: {external_url}")
            except Exception as e:
                logger.warning(f"Comparator Service 客户端初始化失败: {e}")
                self.comparator_client = None

        self.comparator = CrossLibraryComparatorService(
            batch_writer_service=self.batch_writer,
            use_external_service=use_external,
        )
        self.spread_model = SpreadModelService(batch_writer_service=self.batch_writer)

        await self._connect_queues()
        logger.info("系统服务初始化完成")

    async def _connect_queues(self):
        """连接各模块的队列"""
        assert self.ingest and self.batch_writer and self.alerter
        assert self.aging_engine and self.mold_engine
        assert self.text_miner and self.efficacy_engine
        assert self.comparator and self.spread_model

        self.batch_writer.register_input_queue(self.ingest.get_sensor_queue())
        self.batch_writer.register_input_queue(self.alerter._input_queue)

        self.alerter.register_input_queue(self.ingest.get_alert_queue())
        self.mold_engine.set_alert_queue(self.ingest.get_alert_queue())

        self.aging_engine.register_output_queue(self.alerter._input_queue)

        self.batch_writer.register_input_queue(self.text_miner.get_output_queue())

        self.batch_writer.register_input_queue(self.efficacy_engine.get_result_queue())

        self.comparator.register_alert_queue(self.alerter._input_queue)

        logger.info("队列连接完成: ingest → batch_writer, ingest → alerter, "
                     "aging_engine → alerter, text_miner → batch_writer, "
                     "efficacy_engine → batch_writer, comparator → alerter")

    async def start(self):
        """启动所有服务"""
        if self._running:
            return

        logger.info("正在启动系统服务...")

        await asyncio.gather(
            self.ingest.start(),
            self.batch_writer.start(),
            self.aging_engine.start(),
            self.mold_engine.start(),
            self.alerter.start(),
            self.text_miner.start(),
            self.efficacy_engine.start(),
            self.comparator.start(),
            self.spread_model.start(),
        )

        self._running = True
        metrics.set_system_running(True)
        metrics.set_clickhouse_connected(self.clickhouse_client is not None)
        metrics.set_mqtt_connected(self.ingest.subscriber.is_connected() if self.ingest else False)

        logger.info("所有系统服务已启动")

    async def stop(self):
        """停止所有服务"""
        if not self._running:
            return

        logger.info("正在停止系统服务...")

        await asyncio.gather(
            self.ingest.stop(),
            self.batch_writer.stop(),
            self.aging_engine.stop(),
            self.mold_engine.stop(),
            self.alerter.stop(),
            self.text_miner.stop(),
            self.efficacy_engine.stop(),
            self.comparator.stop(),
            self.spread_model.stop(),
        )

        queue_manager.close_all_process_queues()

        if self.clickhouse_client:
            try:
                self.clickhouse_client.disconnect()
            except Exception as e:
                logger.error(f"关闭ClickHouse连接失败: {e}")

        self._running = False
        metrics.set_system_running(False)
        metrics.set_clickhouse_connected(False)
        metrics.set_mqtt_connected(False)

        logger.info("所有系统服务已停止")

    async def add_ws_client(self, websocket: WebSocket):
        """添加WebSocket客户端"""
        async with self._ws_lock:
            self._ws_clients.append(websocket)
        metrics.set_websocket_connections(len(self._ws_clients))
        logger.info(f"WebSocket客户端已连接，当前: {len(self._ws_clients)}")

    async def remove_ws_client(self, websocket: WebSocket):
        """移除WebSocket客户端"""
        async with self._ws_lock:
            if websocket in self._ws_clients:
                self._ws_clients.remove(websocket)
        metrics.set_websocket_connections(len(self._ws_clients))
        logger.info(f"WebSocket客户端已断开，当前: {len(self._ws_clients)}")

    async def broadcast_ws(self, message: Dict[str, Any]):
        """广播消息到所有WebSocket客户端"""
        async with self._ws_lock:
            disconnected = []
            for client in self._ws_clients:
                try:
                    await client.send_json(message)
                except Exception:
                    disconnected.append(client)

            for client in disconnected:
                self._ws_clients.remove(client)

    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "running": self._running,
            "websocket_clients": len(self._ws_clients),
            "services": {
                "ingest": self.ingest.get_stats() if self.ingest else {},
                "batch_writer": self.batch_writer.get_stats() if self.batch_writer else {},
                "aging_engine": self.aging_engine.get_stats() if self.aging_engine else {},
                "mold_engine": self.mold_engine.get_stats() if self.mold_engine else {},
                "alerter": self.alerter.get_stats() if self.alerter else {},
                "text_miner": self.text_miner.get_stats() if self.text_miner else {},
                "efficacy_engine": self.efficacy_engine.get_stats() if self.efficacy_engine else {},
                "comparator": self.comparator.get_stats() if self.comparator else {},
                "spread_model": self.spread_model.get_stats() if self.spread_model else {},
            },
            "queues": queue_manager.get_all_stats(),
        }


services = SystemServices()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"正在启动 {config.service.name} v{config.service.version}...")

    await services.init()
    await services.start()

    app.state.services = services

    logger.info("系统启动完成")

    yield

    logger.info("正在关闭系统...")
    await services.stop()
    logger.info("系统已关闭")


app = FastAPI(
    title=config.service.name,
    description="基于物联网和AI算法的古籍保护监测系统",
    version=config.service.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(efficacy_router, prefix="/api/efficacy", tags=["efficacy"])


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """Prometheus指标中间件"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    endpoint = request.url.path
    if endpoint.startswith("/api/"):
        endpoint = "/api/" + endpoint.split("/")[2]
    elif endpoint not in ("/", "/health", "/metrics", "/docs", "/redoc", "/openapi.json"):
        endpoint = "other"

    metrics.record_api_request(
        method=request.method,
        endpoint=endpoint,
        status_code=response.status_code,
        duration=duration
    )

    return response


@app.get("/metrics")
async def get_metrics():
    """Prometheus指标端点"""
    from .core.queue_manager import queue_manager

    queue_stats = queue_manager.get_all_stats()
    for queue_type, queues in queue_stats.items():
        for q_name, stats in queues.items():
            if isinstance(stats, dict):
                metrics.set_queue_length(q_name, stats.get("current_size", 0))

    return PlainTextResponse(
        content=metrics.get_latest_metrics(),
        media_type=metrics.get_content_type()
    )


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": config.service.name,
        "version": config.service.version,
        "status": "running",
        "docs": "/docs",
        "api_prefix": "/api",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    ch_status = "connected" if services.clickhouse_client else "disconnected"
    ingest_status = "running" if services.ingest and services.ingest.subscriber.is_connected() else "disconnected"
    aging_status = "running" if services.aging_engine and services.aging_engine.is_alive() else "stopped"

    return {
        "status": "healthy",
        "clickhouse": ch_status,
        "mqtt": ingest_status,
        "aging_engine": aging_status,
        "timestamp": services._running,
    }


@app.get("/api/status")
async def get_system_status():
    """获取系统状态和统计"""
    return JSONResponse(content=services.get_status())


@app.websocket("/ws/alert")
async def websocket_alert(websocket: WebSocket):
    """
    WebSocket告警实时推送接口
    客户端连接后自动接收最新告警推送
    """
    await websocket.accept()
    await services.add_ws_client(websocket)

    try:
        broadcaster = services.alerter.get_websocket_broadcaster()
        recent_alerts = await broadcaster.get_recent_alerts()
        for alert in recent_alerts[-10:]:
            await websocket.send_json({
                "type": "alert",
                "data": alert,
            })

        while True:
            try:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": services.get_status()})
                except json.JSONDecodeError:
                    pass
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket消息处理异常: {e}")
                break

    finally:
        await services.remove_ws_client(websocket)


@app.post("/api/predict/aging")
async def submit_aging_prediction(request: Dict[str, Any]):
    """提交老化预测请求"""
    try:
        req = AgingPredictionRequest(**request)
        success = await services.aging_engine.submit_prediction(req)
        return {"success": success, "message_id": req.message_id}
    except Exception as e:
        logger.error(f"提交老化预测失败: {e}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/predict/mold")
async def submit_mold_prediction(request: Dict[str, Any]):
    """提交霉菌预测请求"""
    try:
        req = MoldPredictionRequest(**request)
        success = await services.mold_engine.submit_prediction(req)
        return {"success": success, "message_id": req.message_id}
    except Exception as e:
        logger.error(f"提交霉菌预测失败: {e}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/config/shelf_layout")
async def get_shelf_layout():
    """获取书架布局配置"""
    return config.shelf_layout


@app.get("/api/config/alert_thresholds")
async def get_alert_thresholds():
    """获取告警阈值配置"""
    return config.get_alert_thresholds()


@app.get("/api/config/paper_types")
async def get_paper_types():
    """获取纸张类型配置"""
    arr_config = config.get_arrhenius_config()
    paper_types = arr_config.get("paper_types", {})
    return {
        "paper_types": paper_types,
        "type_map": arr_config.get("paper_type_map", {}),
    }


@app.get("/api/queue_stats")
async def get_queue_stats():
    """获取所有队列统计"""
    return queue_manager.get_all_stats()


class AlertTestRequest(BaseModel):
    level: str = "yellow"
    shelf_id: str = "test_shelf"
    slot_id: str = "test_slot"
    message: str = "测试告警"


@app.post("/api/test/alert")
async def test_alert(req: AlertTestRequest):
    """测试告警推送"""
    try:
        alert = AlertMessage(
            shelf_id=req.shelf_id,
            slot_id=req.slot_id,
            alert_level=req.level,
            alert_type="test",
            alert_value=0,
            threshold=0,
            message=req.message,
        )
        await services.alerter._input_queue.put(alert)
        return {"success": True, "alert_id": alert.alert_id}
    except Exception as e:
        logger.error(f"测试告警失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/text_miner/extract/{book_id}")
async def extract_book_meta(book_id: str):
    """提取单本书籍的OCR元数据"""
    try:
        from .database import db_manager
        books = db_manager.get_books_info()
        book_info = None
        for book in books:
            if book.get("book_id") == book_id:
                book_info = book
                break
        if not book_info:
            return JSONResponse(status_code=404, content={"error": f"未找到书籍: {book_id}"})
        result = await services.text_miner.extract_meta(
            book_id, book_info.get("shelf_id", ""), book_info.get("slot_id", ""), book_info
        )
        if result:
            return result.to_dict()
        return JSONResponse(status_code=500, content={"error": "元数据提取失败"})
    except Exception as e:
        logger.error(f"书籍元数据提取失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/text_miner/extract_all")
async def extract_all_books():
    """提取所有书籍的OCR元数据"""
    try:
        count = await services.text_miner.process_all_books()
        return {"success": True, "processed_count": count}
    except Exception as e:
        logger.error(f"批量提取失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/text_miner/meta/{book_id}")
async def get_book_meta(book_id: str):
    """获取书籍元数据"""
    result = await services.text_miner.get_book_meta(book_id)
    if result:
        return result.to_dict()
    return JSONResponse(status_code=404, content={"error": f"未找到书籍元数据: {book_id}"})


@app.get("/api/efficacy/evaluate/{prescription}")
async def evaluate_prescription_efficacy(
    prescription: str,
    shelf_id: Optional[str] = None,
    slot_id: Optional[str] = None
):
    """评估单个药方的防霉效果"""
    if prescription not in ("yuncao", "huangbo", "yanye"):
        return JSONResponse(status_code=400, content={"error": "无效药方，可选: yuncao, huangbo, yanye"})
    result = await services.efficacy_engine.evaluate_prescription(prescription, shelf_id, slot_id)
    if result:
        return result.to_dict()
    return JSONResponse(status_code=503, content={"error": "数据不足，无法评估"})


@app.get("/api/efficacy/evaluate_all")
async def evaluate_all_prescriptions():
    """评估所有药方的防霉效果"""
    results = await services.efficacy_engine.evaluate_all()
    return {"results": [r.to_dict() for r in results]}


@app.get("/api/efficacy/summary")
async def get_efficacy_summary():
    """获取药效评估摘要"""
    return services.efficacy_engine.get_efficacy_summary()


@app.get("/api/comparator/compare")
async def run_cross_library_comparison():
    """执行跨馆藏环境比对"""
    try:
        results = await services.comparator.compare_all()
        return {"results": [r.to_dict() for r in results]}
    except Exception as e:
        logger.error(f"跨馆藏比对失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/comparator/stats")
async def get_comparator_stats():
    """获取跨馆藏比对统计"""
    return services.comparator.get_stats()


@app.post("/api/spread/predict")
async def predict_spread(request: Dict[str, Any]):
    """提交病害传播预测请求"""
    try:
        from .core.messages import SpreadPredictionRequest
        req = SpreadPredictionRequest(**request)
        results = await services.spread_model.predict_spread(
            req.initial_infected or ([req.start_shelf_id] if req.start_shelf_id else [])
        )
        return {"results": [r.to_dict() for r in results[:100]]}
    except Exception as e:
        logger.error(f"传播预测失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/spread/hotspots")
async def get_spread_hotspots(threshold: Optional[float] = None):
    """获取病害传播热点书架"""
    hotspots = await services.spread_model.get_hotspots(threshold)
    return {"hotspots": hotspots}


@app.get("/api/spread/directions")
async def get_spread_directions():
    """获取书架间传播方向箭头（用于前端可视化）"""
    directions = services.spread_model.get_spread_directions()
    graph_data = {}
    if services.spread_model._shelf_graph:
        graph_data = services.spread_model._shelf_graph.to_dict()
    return {"directions": directions, "graph": graph_data}


@app.post("/api/comparator/callback")
async def comparator_result_callback(request: Dict[str, Any]):
    """
    接收外部 comparator-service 的比对结果回调
    """
    try:
        from .core.messages import CrossLibraryComparisonResult, deserialize_message

        result = deserialize_message(request)
        if isinstance(result, CrossLibraryComparisonResult):
            if services.comparator and services.comparator._output_queue:
                await services.comparator._output_queue.put(result)

            if services.comparator and services.comparator._batch_writer:
                services.comparator._save_to_database(result)

            logger.info(f"收到外部比对结果: {result.library_name} - {result.metric}")
            return {"success": True}
        else:
            logger.warning(f"收到无效的比对结果回调: {request}")
            return {"success": False, "error": "无效的消息类型"}
    except Exception as e:
        logger.error(f"处理比对结果回调失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/alert/callback")
async def comparator_alert_callback(request: Dict[str, Any]):
    """
    接收外部 comparator-service 的告警回调
    """
    try:
        from .core.messages import AlertMessage, deserialize_message

        alert = deserialize_message(request)
        if isinstance(alert, AlertMessage):
            if services.alerter and services.alerter._input_queue:
                await services.alerter._input_queue.put(alert)

            logger.warning(
                f"收到外部告警: {alert.alert_type} - "
                f"{alert.alert_level} - {alert.message[:50]}"
            )
            return {"success": True}
        else:
            logger.warning(f"收到无效的告警回调: {request}")
            return {"success": False, "error": "无效的消息类型"}
    except Exception as e:
        logger.error(f"处理告警回调失败: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/comparator/service/health")
async def check_external_comparator_service():
    """检查外部 comparator-service 健康状态"""
    if services.comparator_client:
        health = services.comparator_client.check_health()
        return {
            "client_available": True,
            "service_health": health,
            "service_url": services.comparator_client.base_url,
        }
    else:
        return {
            "client_available": False,
            "error": "Comparator Service 客户端未初始化",
            "client_import_available": _COMPARATOR_CLIENT_AVAILABLE,
        }


@app.post("/api/comparator/service/switch")
async def switch_comparator_service(request: Dict[str, Any]):
    """
    动态切换 comparator 服务模式
    request: {"use_external": true/false}
    """
    try:
        use_external = request.get("use_external", False)

        if use_external and not _COMPARATOR_CLIENT_AVAILABLE:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "外部服务客户端不可用"}
            )

        if use_external and services.comparator_client is None:
            comp_config = config.comparator
            external_url = comp_config.get("external_service_url", "http://127.0.0.1:8001")
            services.comparator_client = init_comparator_client(base_url=external_url)

        await services.comparator.stop()

        services.comparator = CrossLibraryComparatorService(
            batch_writer_service=services.batch_writer,
            use_external_service=use_external,
        )

        services.comparator.register_alert_queue(services.alerter._input_queue)

        await services.comparator.start()

        logger.info(f"已切换 comparator 服务模式: {'外部' if use_external else '内部'}")
        return {
            "success": True,
            "use_external": use_external,
            "service_mode": "external" if use_external else "internal",
        }
    except Exception as e:
        logger.error(f"切换 comparator 服务模式失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )
