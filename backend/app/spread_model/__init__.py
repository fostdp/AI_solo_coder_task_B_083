"""
霉菌传播模型模块
基于SEIR传染病模型的书架间霉菌传播预测
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import SpreadModelService

__all__ = ["SpreadModelService"]


def __getattr__(name: str):
    """延迟导入，避免循环导入"""
    if name == "SpreadModelService":
        from .service import SpreadModelService
        return SpreadModelService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
