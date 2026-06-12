"""
FastAPI 应用入口
古代医学文献馆藏微环境监测与古籍病害预测系统
"""
import logging
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .api.routes import router as api_router

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    from .services.mqtt_consumer import mqtt_consumer
    try:
        mqtt_consumer.start()
    except Exception as e:
        logger.warning(f"MQTT consumer start skipped: {e}")
    yield
    logger.info("Shutting down...")
    try:
        mqtt_consumer.stop()
    except Exception:
        pass
    try:
        from .database import get_ch
        get_ch().close()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="古代医学文献馆藏微环境监测与古籍病害预测系统 - 后端API",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    try:
        import os
        frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
        if os.path.isdir(frontend_dir):
            app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    except Exception as e:
        logger.info(f"Static frontend mount skipped: {e}")

    @app.get("/")
    async def root():
        return {
            "app": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api_base": "/api/v1",
        }

    return app


app = create_app()


def _sigint_handler(signum, frame):
    logger.info("SIGINT received, stopping...")
    try:
        from .services.mqtt_consumer import mqtt_consumer
        mqtt_consumer.stop()
    except Exception:
        pass
    sys.exit(0)


signal.signal(signal.SIGINT, _sigint_handler)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
