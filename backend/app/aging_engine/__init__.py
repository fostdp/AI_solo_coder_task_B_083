"""
老化预测引擎模块
在独立进程中运行CPU密集型的纸张老化预测计算
"""
from .service import (
    AgingEngineService,
    AgingEngineStats,
    ArrheniusAgingModel,
    aging_process_main,
)

__all__ = [
    "AgingEngineService",
    "AgingEngineStats",
    "ArrheniusAgingModel",
    "aging_process_main",
]
