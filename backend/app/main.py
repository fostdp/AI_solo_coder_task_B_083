import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .config import settings
from .database import db_manager
from .mqtt_subscriber import mqtt_subscriber
from .alerts import AlertManager, AlertThreshold
from .routers import api_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("正在启动古代医学文献馆藏微环境监测系统...")

    if not db_manager.connect():
        logger.warning("ClickHouse连接失败，部分功能可能不可用")
    else:
        db_manager.ensure_database()

    alert_manager = AlertManager(
        dingtalk_webhook=settings.DINGTALK_WEBHOOK,
        smtp_config={
            "host": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
            "username": settings.SMTP_USER,
            "password": settings.SMTP_PASSWORD,
            "sender": settings.SMTP_SENDER,
            "use_tls": True
        },
        thresholds=AlertThreshold(
            yellow_ph=settings.ALERT_YELLOW_PH,
            orange_ph=settings.ALERT_ORANGE_PH,
            red_ph=settings.ALERT_RED_PH,
            yellow_mold=settings.ALERT_YELLOW_MOLD,
            orange_light=settings.ALERT_ORANGE_LIGHT
        )
    )

    mqtt_subscriber.alert_manager = alert_manager
    mqtt_subscriber.start_background()

    app.state.db_manager = db_manager
    app.state.mqtt_subscriber = mqtt_subscriber
    app.state.alert_manager = alert_manager

    logger.info("系统启动完成")

    yield

    logger.info("正在关闭系统...")
    mqtt_subscriber.stop()
    db_manager.close()
    logger.info("系统已关闭")


app = FastAPI(
    title="古代医学文献馆藏微环境监测与古籍病害预测系统",
    description="基于物联网和AI算法的古籍保护监测系统",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "古代医学文献馆藏微环境监测与古籍病害预测系统",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "api_prefix": "/api"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    clickhouse_status = "connected" if db_manager.client else "disconnected"
    mqtt_status = "connected" if mqtt_subscriber.connected else "disconnected"

    return {
        "status": "healthy",
        "clickhouse": clickhouse_status,
        "mqtt": mqtt_status,
        "timestamp": settings.FASTAPI_HOST is not None  # dummy check
    }
