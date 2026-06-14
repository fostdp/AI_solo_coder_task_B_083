import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .api.routes import router as api_router
from .services.mqtt_ingest import mqtt_writer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("abm.app")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="古代医学文献馆藏微环境监测与古籍病害预测系统后端 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def on_startup():
    logger.info("Starting MQTT ingestion service with BatchWriter")
    mqtt_ingest.start()


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Stopping MQTT ingestion service")
    mqtt_ingest.stop()


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "api_prefix": "/api/v1",
    }
