"""
告警推送模块
负责钉钉机器人推送、邮件通知和WebSocket广播
"""
import asyncio
import logging
import smtplib
import threading
import time
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass
from datetime import datetime

import requests

from ..core.config import config
from ..core.messages import AlertMessage, Message
from ..core.queue_manager import queue_manager, AsyncQueueWrapper

logger = logging.getLogger(__name__)


@dataclass
class AlerterStats:
    """告警统计"""
    total_alerts: int = 0
    dingtalk_sent: int = 0
    dingtalk_failed: int = 0
    email_sent: int = 0
    email_failed: int = 0
    websocket_broadcast: int = 0
    dedup_skipped: int = 0
    last_alert_time: Optional[str] = None


class DingTalkNotifier:
    """钉钉机器人推送"""

    def __init__(self):
        notif_config = config.notification.get("dingtalk", {})
        alert_config = config.alerts.get("notification", {}).get("dingtalk", {})
        self.webhook = notif_config.get("webhook", "")
        self.timeout = alert_config.get("timeout", 10)
        self.enabled = alert_config.get("enabled", True) and bool(self.webhook)

    def send_alert(self, alert: AlertMessage) -> bool:
        """发送钉钉告警"""
        if not self.enabled:
            return False

        try:
            level_emoji = {
                "yellow": "🟡",
                "orange": "🟠",
                "red": "🔴",
            }.get(alert.alert_level, "⚠️")

            level_name = {
                "yellow": "黄色预警",
                "orange": "橙色告警",
                "red": "红色告警",
            }.get(alert.alert_level, "告警")

            message = f"""
{level_emoji} **{level_name}** {level_emoji}

**告警时间**: {alert.timestamp}
**书架**: {alert.shelf_id}
**格口**: {alert.slot_id}
**告警类型**: {alert.alert_type}
**当前值**: {alert.alert_value}
**阈值**: {alert.threshold}

**详细信息**:
{alert.message}

---
*古代医学文献馆藏微环境监测系统*
            """.strip()

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"[{level_name}] 馆藏环境告警",
                    "text": message,
                },
                "at": {
                    "isAtAll": alert.alert_level == "red",
                },
            }

            response = requests.post(
                self.webhook,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )

            response.raise_for_status()
            result = response.json()

            if result.get("errcode") == 0:
                logger.info(f"钉钉告警发送成功: {alert.alert_id}")
                return True
            else:
                logger.error(f"钉钉告警发送失败: {result.get('errmsg')}")
                return False

        except Exception as e:
            logger.error(f"钉钉告警发送异常: {e}")
            return False


class EmailNotifier:
    """邮件通知"""

    def __init__(self):
        notif_config = config.notification
        smtp_config = notif_config.get("smtp", {})
        alert_config = config.alerts.get("notification", {}).get("email", {})

        self.host = smtp_config.get("host", "")
        self.port = smtp_config.get("port", 25)
        self.username = smtp_config.get("username", "")
        self.password = smtp_config.get("password", "")
        self.sender = smtp_config.get("sender", "monitor@library.com")
        self.use_tls = smtp_config.get("use_tls", True)
        self.recipients = notif_config.get("alert_emails", [])

        self.timeout = alert_config.get("timeout", 15)
        self.enabled = (
            alert_config.get("enabled", True)
            and bool(self.host)
            and bool(self.recipients)
        )

    def send_alert(self, alert: AlertMessage) -> bool:
        """发送邮件告警"""
        if not self.enabled:
            return False

        try:
            level_name = {
                "yellow": "黄色预警",
                "orange": "橙色告警",
                "red": "红色告警",
            }.get(alert.alert_level, "告警")

            priority = {
                "yellow": "normal",
                "orange": "high",
                "red": "high",
            }.get(alert.alert_level, "normal")

            msg = MIMEMultipart()
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = f"[{level_name}] 馆藏环境告警 - 书架{alert.shelf_id}"
            msg["X-Priority"] = "1" if priority == "high" else "3"

            html_body = f"""
<html>
<head>
    <meta charset="utf-8">
    <style>
        .alert {{ padding: 20px; border-radius: 8px; font-family: "Microsoft YaHei", Arial, sans-serif; }}
        .yellow {{ background-color: #fff3cd; border-left: 4px solid #ffc107; }}
        .orange {{ background-color: #ffe5d0; border-left: 4px solid #fd7e14; }}
        .red {{ background-color: #f8d7da; border-left: 4px solid #dc3545; }}
        .title {{ font-size: 18px; font-weight: bold; margin-bottom: 15px; }}
        .info-item {{ margin: 8px 0; font-size: 14px; }}
        .label {{ display: inline-block; width: 80px; color: #666; }}
        .value {{ font-weight: bold; }}
        .message {{ margin-top: 15px; padding: 10px; background: rgba(255,255,255,0.5); border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="alert {alert.alert_level}">
        <div class="title">⚠️ {level_name}</div>
        <div class="info-item"><span class="label">告警时间:</span><span class="value">{alert.timestamp}</span></div>
        <div class="info-item"><span class="label">书架:</span><span class="value">{alert.shelf_id}</span></div>
        <div class="info-item"><span class="label">格口:</span><span class="value">{alert.slot_id}</span></div>
        <div class="info-item"><span class="label">告警类型:</span><span class="value">{alert.alert_type}</span></div>
        <div class="info-item"><span class="label">当前值:</span><span class="value">{alert.alert_value}</span></div>
        <div class="info-item"><span class="label">阈值:</span><span class="value">{alert.threshold}</span></div>
        <div class="message">
            <strong>详细信息:</strong><br>
            {alert.message}
        </div>
        <p style="margin-top: 20px; font-size: 12px; color: #999;">
            此邮件由古代医学文献馆藏微环境监测系统自动发送
        </p>
    </div>
</body>
</html>
            """

            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if self.use_tls:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                server.starttls()

            if self.username:
                server.login(self.username, self.password)

            server.sendmail(self.sender, self.recipients, msg.as_string())
            server.quit()

            logger.info(f"邮件告警发送成功: {alert.alert_id}")
            return True

        except Exception as e:
            logger.error(f"邮件告警发送异常: {e}")
            return False


class WebSocketBroadcaster:
    """WebSocket广播器"""

    def __init__(self):
        alert_config = config.alerts.get("notification", {}).get("websocket", {})
        self.enabled = alert_config.get("enabled", True)
        self.broadcast_interval = alert_config.get("broadcast_interval", 5)

        self._clients: Set[asyncio.Queue] = set()
        self._recent_alerts: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._broadcast_task: Optional[asyncio.Task] = None
        self._running = False

    def add_client(self, client_queue: asyncio.Queue):
        """添加WebSocket客户端"""
        self._clients.add(client_queue)
        logger.info(f"WebSocket客户端已连接，当前连接数: {len(self._clients)}")

    def remove_client(self, client_queue: asyncio.Queue):
        """移除WebSocket客户端"""
        self._clients.discard(client_queue)
        logger.info(f"WebSocket客户端已断开，当前连接数: {len(self._clients)}")

    async def broadcast(self, alert: AlertMessage):
        """广播告警给所有连接的客户端"""
        if not self.enabled:
            return

        alert_dict = alert.to_dict()

        async with self._lock:
            self._recent_alerts.append(alert_dict)
            if len(self._recent_alerts) > 100:
                self._recent_alerts = self._recent_alerts[-100:]

        disconnected = []
        for client in self._clients:
            try:
                client.put_nowait(alert_dict)
            except Exception:
                disconnected.append(client)

        for client in disconnected:
            self._clients.discard(client)

        logger.debug(f"WebSocket广播完成: {alert.alert_id}, 接收客户端: {len(self._clients)}")

    async def get_recent_alerts(self) -> List[Dict[str, Any]]:
        """获取最近的告警"""
        async with self._lock:
            return list(self._recent_alerts)

    async def start(self):
        """启动广播器（目前被动发送，无需后台任务）"""
        self._running = True

    async def stop(self):
        """停止广播器"""
        self._running = False
        self._clients.clear()


class AlertDeduplicator:
    """告警去重器"""

    def __init__(self):
        self._recent_alerts: Dict[str, float] = {}
        self._dedup_window = config.alerts.get("dedup_window", 300)
        self._lock = threading.Lock()

    def should_alert(self, alert: AlertMessage) -> bool:
        """检查是否应该发送告警（去重）"""
        dedup_key = f"{alert.shelf_id}_{alert.slot_id}_{alert.alert_type}_{alert.alert_level}"

        with self._lock:
            now = time.time()
            last_sent = self._recent_alerts.get(dedup_key, 0)

            if now - last_sent < self._dedup_window:
                return False

            self._recent_alerts[dedup_key] = now
            self._cleanup_old()
            return True

    def _cleanup_old(self):
        """清理过期的告警记录"""
        now = time.time()
        expired = [k for k, v in self._recent_alerts.items() if now - v > self._dedup_window * 2]
        for k in expired:
            del self._recent_alerts[k]


class AlerterService:
    """
    告警服务
    监听告警队列，通过钉钉、邮件和WebSocket推送告警
    """

    def __init__(self):
        self._input_queue: Optional[AsyncQueueWrapper] = None
        self._dingtalk = DingTalkNotifier()
        self._email = EmailNotifier()
        self._websocket = WebSocketBroadcaster()
        self._deduplicator = AlertDeduplicator()

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = AlerterStats()

        self._send_thread_pool: Optional[asyncio.AbstractEventLoop] = None

    def register_input_queue(self, queue: AsyncQueueWrapper):
        """注册输入队列"""
        self._input_queue = queue
        logger.info("AlerterService注册输入队列")

    def get_websocket_broadcaster(self) -> WebSocketBroadcaster:
        """获取WebSocket广播器"""
        return self._websocket

    async def _send_notifications(self, alert: AlertMessage):
        """异步发送所有通知"""
        if not self._deduplicator.should_alert(alert):
            self._stats.dedup_skipped += 1
            logger.debug(f"告警去重跳过: {alert.alert_id}")
            return

        self._stats.total_alerts += 1
        self._stats.last_alert_time = datetime.now().isoformat()

        if self._dingtalk.send_alert(alert):
            self._stats.dingtalk_sent += 1
        else:
            self._stats.dingtalk_failed += 1

        if self._email.send_alert(alert):
            self._stats.email_sent += 1
        else:
            self._stats.email_failed += 1

        await self._websocket.broadcast(alert)
        self._stats.websocket_broadcast += 1

    async def _process_loop(self):
        """主处理循环"""
        logger.info("告警服务已启动")
        while self._running:
            try:
                if self._input_queue is None:
                    await asyncio.sleep(0.5)
                    continue

                alert = await self._input_queue.get(timeout=1.0)
                if alert is None:
                    continue

                if isinstance(alert, AlertMessage):
                    await self._send_notifications(alert)
                else:
                    logger.debug(f"忽略非告警消息: {alert.message_type}")

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"告警处理异常: {e}")
                await asyncio.sleep(0.1)
        logger.info("告警服务已停止")

    async def start(self):
        """启动服务"""
        if self._running:
            return

        self._running = True
        await self._websocket.start()
        self._task = asyncio.create_task(self._process_loop())
        logger.info("AlerterService已启动")

    async def stop(self):
        """停止服务"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        await self._websocket.stop()
        await queue_manager.flush_all_async()
        logger.info("AlerterService已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "stats": self._stats.__dict__,
            "notifiers": {
                "dingtalk_enabled": self._dingtalk.enabled,
                "email_enabled": self._email.enabled,
                "websocket_enabled": self._websocket.enabled,
                "websocket_clients": len(self._websocket._clients),
            },
            "queue_size": self._input_queue.qsize() if self._input_queue else 0,
        }
