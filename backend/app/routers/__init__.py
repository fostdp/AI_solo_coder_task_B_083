from fastapi import APIRouter
from .monitor import router as monitor_router
from .analysis import router as analysis_router
from .admin import router as admin_router

api_router = APIRouter()
api_router.include_router(monitor_router)
api_router.include_router(analysis_router)
api_router.include_router(admin_router)

__all__ = ['api_router']
