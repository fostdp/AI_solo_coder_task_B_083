"""
Comparator Service IPC Client
供主服务调用的 comparator-service 客户端
通过 HTTP 与独立进程的 comparator-service 通信
"""

import os
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class ComparatorServiceClient:
    """
    Comparator Service IPC 客户端
    
    通过 HTTP 与独立进程的 comparator-service 通信
    提供与内部 CrossLibraryComparatorService 相同的接口
    """

    def __init__(
        self,
        base_url: str = None,
        timeout: int = 10,
    ):
        self.base_url = base_url or os.getenv(
            "COMPARATOR_SERVICE_URL",
            "http://127.0.0.1:8001"
        )
        self.timeout = timeout
        self._session = requests.Session()
        self._connected = False

    def _make_url(self, path: str) -> str:
        """构造完整URL"""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        params: Dict[str, Any] = None,
        json_data: Dict[str, Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """发送HTTP请求"""
        try:
            url = self._make_url(path)
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            self._connected = True
            return response.json()
        except requests.ConnectionError:
            self._connected = False
            logger.warning(f"无法连接到 comparator-service: {self.base_url}")
            return None
        except requests.Timeout:
            logger.warning(f"请求 comparator-service 超时: {path}")
            return None
        except Exception as e:
            logger.error(f"请求 comparator-service 失败: {path}, error={e}")
            return None

    def is_connected(self) -> bool:
        """检查是否连接成功"""
        return self._connected

    def check_health(self) -> Dict[str, Any]:
        """检查服务健康状态"""
        result = self._request("GET", "/health")
        if result is None:
            return {"status": "disconnected", "error": "无法连接到 comparator-service"}
        return result

    def trigger_compare(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        触发比对
        
        Args:
            force: 是否强制重新加载CSV数据
            
        Returns:
            比对结果，包含 count、anomalies、results
        """
        return self._request(
            "POST",
            "/compare",
            json_data={"force": force},
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        result = self._request("GET", "/stats")
        if result is None:
            return {
                "stats": {
                    "total_comparisons": 0,
                    "total_anomalies": 0,
                    "last_run_time": None,
                    "last_anomaly_time": None,
                    "csv_records_loaded": 0,
                },
                "error": "无法连接到 comparator-service",
                "service_mode": "external",
                "service_url": self.base_url,
                "connected": False,
            }
        result["service_mode"] = "external"
        result["service_url"] = self.base_url
        result["connected"] = True
        return result

    def get_results(self, limit: int = 100) -> Optional[Dict[str, Any]]:
        """获取比对结果"""
        return self._request(
            "GET",
            "/results",
            params={"limit": limit},
        )

    def get_alerts(self, limit: int = 50) -> Optional[Dict[str, Any]]:
        """获取告警信息"""
        return self._request(
            "GET",
            "/alerts",
            params={"limit": limit},
        )

    def reload_data(self) -> Optional[Dict[str, Any]]:
        """重新加载CSV数据"""
        return self._request("POST", "/reload")

    def close(self):
        """关闭连接"""
        self._session.close()
        logger.info("Comparator Service 客户端已关闭")


class ComparatorServiceIPCWrapper:
    """
    Comparator Service IPC 包装器
    
    包装 IPC 客户端，提供与内部 CrossLibraryComparatorService 相同的接口
    用于在主服务中无缝切换内部/外部服务
    """

    def __init__(self, client: ComparatorServiceClient = None):
        self._client = client or ComparatorServiceClient()
        self._use_external_service = True
        self._last_compare_results: List[Dict[str, Any]] = []

    @property
    def use_external_service(self) -> bool:
        return self._use_external_service

    def is_available(self) -> bool:
        """检查外部服务是否可用"""
        health = self._client.check_health()
        return health.get("status") == "healthy"

    async def compare_all(self) -> List[Dict[str, Any]]:
        """
        执行所有图书馆、所有指标的比较
        
        Returns:
            比较结果列表（字典格式，兼容内部服务的 CrossLibraryComparisonResult）
        """
        result = self._client.trigger_compare()
        if result is None or not result.get("success", False):
            logger.warning("外部 comparator-service 调用失败，返回空结果")
            return []

        results = result.get("results", [])
        self._last_compare_results = results
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._client.get_stats()

    def get_results(self) -> List[Dict[str, Any]]:
        """获取最近的比对结果"""
        return self._last_compare_results

    def load_csv_data(self) -> List[Dict[str, Any]]:
        """加载CSV数据（转发到外部服务）"""
        result = self._client.reload_data()
        if result and result.get("success"):
            return [{"loaded": result.get("records_loaded", 0)}]
        return []

    def get_pool_stats(self) -> Dict[str, Any]:
        """获取连接池统计"""
        stats = self._client.get_stats()
        return stats.get("pool_stats", {})

    async def start(self):
        """启动（空实现，保持接口兼容）"""
        logger.info("外部 Comparator Service 客户端已就绪")
        logger.info(f"服务地址: {self._client.base_url}")

    async def stop(self):
        """停止（关闭客户端连接）"""
        self._client.close()

    def register_output_queue(self, queue):
        """注册输出队列（空实现，外部服务通过HTTP回调）"""
        logger.info("外部服务通过HTTP回调发送结果，无需注册输出队列")

    def register_alert_queue(self, queue):
        """注册告警队列（空实现，外部服务通过HTTP回调）"""
        logger.info("外部服务通过HTTP回调发送告警，无需注册告警队列")


_comparator_client: Optional[ComparatorServiceClient] = None


def get_comparator_client() -> ComparatorServiceClient:
    """获取单例 Comparator Service 客户端"""
    global _comparator_client
    if _comparator_client is None:
        _comparator_client = ComparatorServiceClient()
    return _comparator_client


def init_comparator_client(base_url: str = None) -> ComparatorServiceClient:
    """初始化 Comparator Service 客户端"""
    global _comparator_client
    _comparator_client = ComparatorServiceClient(base_url=base_url)
    logger.info(f"Comparator Service 客户端已初始化: {_comparator_client.base_url}")
    return _comparator_client


if __name__ == "__main__":
    client = get_comparator_client()
    print("健康检查:", client.check_health())
    print("统计信息:", client.get_stats())
    print("触发比对:", client.trigger_compare())
