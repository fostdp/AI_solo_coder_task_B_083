"""
efficacy-service FastAPI 子应用
基于贝叶斯统计方法评估三方古代药方的防霉效果
"""
import logging
import sys
import os
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend", "app"))

from .router import router as efficacy_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    创建 efficacy-service FastAPI 子应用
    
    Returns:
        FastAPI 应用实例
    """
    app = FastAPI(
        title="Efficacy Service",
        description="基于贝叶斯统计和零膨胀泊松模型的古代药方防霉效果评估服务",
        version="1.0.0",
        prefix="/api/efficacy",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(efficacy_router, prefix="", tags=["efficacy"])

    @app.get("/", tags=["root"])
    async def root() -> Dict[str, Any]:
        """子应用根路径"""
        return {
            "name": "Efficacy Service",
            "version": "1.0.0",
            "status": "running",
            "description": "古代药方防霉效果评估服务",
            "endpoints": {
                "evaluate_single": "/api/efficacy/evaluate/{prescription}",
                "evaluate_all": "/api/efficacy/evaluate_all",
                "summary": "/api/efficacy/summary",
                "zip_fit": "/api/efficacy/zip/fit",
                "zip_detect": "/api/efficacy/zip/detect",
            },
            "docs": "/docs",
        }

    @app.get("/health", tags=["health"])
    async def health_check() -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "service": "efficacy-service",
            "version": "1.0.0",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )
