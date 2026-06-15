"""
古代医学文献馆藏微环境监测系统 - 主入口
协调各模块通信，提供REST API和WebSocket接口
"""
import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from clickhouse_driver import Client

from .core.config import config, setup_logging
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

setup_logging(config)
logger = logging.getLogger(__name__)


class SystemServices:
    """系统服务管理器"""

    def __init__(self):
        self.ingest: Optional[IngestService] = None
        self.batch_writer: Optional[BatchWriterService] = None
        self.aging_engine: Optional[AgingEngineService] = None
        self.mold_engine: Optional[MoldEngineService] = None
        self.alerter: Optional[AlerterService] = None
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

        await self._connect_queues()
        logger.info("系统服务初始化完成")

    async def _connect_queues(self):
        """连接各模块的队列"""
        assert self.ingest and self.batch_writer and self.alerter
        assert self.aging_engine and self.mold_engine

        self.batch_writer.register_input_queue(self.ingest.get_sensor_queue())
        self.batch_writer.register_input_queue(self.alerter._input_queue)

        self.alerter.register_input_queue(self.ingest.get_alert_queue())
        self.mold_engine.set_alert_queue(self.ingest.get_alert_queue())

        self.aging_engine.register_output_queue(self.alerter._input_queue)

        logger.info("队列连接完成: ingest → batch_writer, ingest → alerter, aging_engine → alerter")

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
        )

        self._running = True
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
        )

        queue_manager.close_all_process_queues()

        if self.clickhouse_client:
            try:
                self.clickhouse_client.disconnect()
            except Exception as e:
                logger.error(f"关闭ClickHouse连接失败: {e}")

        self._running = False
        logger.info("所有系统服务已停止")

    async def add_ws_client(self, websocket: WebSocket):
        """添加WebSocket客户端"""
        async with self._ws_lock:
            self._ws_clients.append(websocket)
        logger.info(f"WebSocket客户端已连接，当前: {len(self._ws_clients)}")

    async def remove_ws_client(self, websocket: WebSocket):
        """移除WebSocket客户端"""
        async with self._ws_lock:
            if websocket in self._ws_clients:
                self._ws_clients.remove(websocket)
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
