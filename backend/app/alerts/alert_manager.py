import json
import logging
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import uuid

from ..core.config import config

logger = logging.getLogger(__name__)


@dataclass
class AlertThreshold:
    yellow_ph: float = None
    orange_ph: float = None
    red_ph: float = None
    yellow_mold: float = None
    orange_light: float = None
    red_active_mold: bool = None

    def __post_init__(self):
        thresholds = config.get_alert_thresholds()
        if self.yellow_ph is None:
            self.yellow_ph = thresholds.get("yellow_ph", 6.5)
        if self.orange_ph is None:
            self.orange_ph = thresholds.get("orange_ph", 6.0)
        if self.red_ph is None:
            self.red_ph = thresholds.get("red_ph", 5.5)
        if self.yellow_mold is None:
            self.yellow_mold = thresholds.get("yellow_mold", 500.0)
        if self.orange_light is None:
            self.orange_light = thresholds.get("orange_light", 50.0)
        if self.red_active_mold is None:
            self.red_active_mold = thresholds.get("red_active_mold", True)


@dataclass
class Alert:
    alert_id: str
    timestamp: str
    shelf_id: str
    slot_id: str
    alert_level: str
    alert_type: str
    alert_value: float
    threshold: float
    message: str
    is_handled: bool = False
    handle_time: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class AlertManager:
    """
    告警管理器
    负责告警分级、去重、推送
    所有配置从config.yaml加载
    """

    def __init__(self, dingtalk_webhook: str = None,
                 smtp_config: Dict = None,
                 thresholds: AlertThreshold = None):
        notif_config = config.notification
        alert_config = config.alerts

        self.dingtalk_webhook = dingtalk_webhook or notif_config.get("dingtalk", {}).get("webhook", "")
        self.smtp_config = smtp_config or notif_config.get("smtp", {})
        self.thresholds = thresholds or AlertThreshold()
        self._recent_alerts = {}
        self._dedup_window = alert_config.get("dedup_window", 300)

    def check_and_create_alerts(self, sensor_data: Dict) -> List[Alert]:
        """
        检查传感器数据，生成告警
        """
        alerts = []
        shelf_id = sensor_data.get("shelf_id", "unknown")
        slot_id = sensor_data.get("slot_id", "unknown")

        if "ph_value" in sensor_data:
            ph_alerts = self._check_ph(sensor_data["ph_value"], shelf_id, slot_id)
            alerts.extend(ph_alerts)

        if "mold_spore" in sensor_data:
            mold_alerts = self._check_mold(sensor_data["mold_spore"],
                                           sensor_data.get("temperature", 20),
                                           sensor_data.get("humidity", 50),
                                           shelf_id, slot_id)
            alerts.extend(mold_alerts)

        if "light" in sensor_data:
            light_alerts = self._check_light(sensor_data["light"], shelf_id, slot_id)
            alerts.extend(light_alerts)

        active_mold = sensor_data.get("active_mold_detected", False)
        if active_mold:
            red_alert = Alert(
                alert_id=str(uuid.uuid4()),
                timestamp=datetime.now().isoformat(),
                shelf_id=shelf_id,
                slot_id=slot_id,
                alert_level="red",
                alert_type="active_mold",
                alert_value=1,
                threshold=0,
                message=f"检测到活性霉菌！书架 {shelf_id} 格口 {slot_id} 已发现活性霉菌，请立即处理！"
            )
            alerts.append(red_alert)

        unique_alerts = []
        for alert in alerts:
            dedup_key = f"{alert.shelf_id}_{alert.slot_id}_{alert.alert_type}_{alert.alert_level}"
            if self._should_send_alert(dedup_key):
                unique_alerts.append(alert)
                self._recent_alerts[dedup_key] = datetime.now()

        return unique_alerts

    def _should_send_alert(self, dedup_key: str) -> bool:
        """告警去重判断"""
        if dedup_key not in self._recent_alerts:
            return True
        last_time = self._recent_alerts[dedup_key]
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed > self._dedup_window

    def _check_ph(self, ph_value: float, shelf_id: str, slot_id: str) -> List[Alert]:
        """检查pH值告警"""
        alerts = []
        now = datetime.now().isoformat()

        if ph_value < self.thresholds.red_ph:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                timestamp=now,
                shelf_id=shelf_id,
                slot_id=slot_id,
                alert_level="red",
                alert_type="ph_low",
                alert_value=ph_value,
                threshold=self.thresholds.red_ph,
                message=f"【红色告警】书架 {shelf_id} 格口 {slot_id} pH值严重偏低：{ph_value:.2f}（阈值{self.thresholds.red_ph}），纸张面临严重酸化脆化风险！"
            ))
        elif ph_value < self.thresholds.orange_ph:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                timestamp=now,
                shelf_id=shelf_id,
                slot_id=slot_id,
                alert_level="orange",
                alert_type="ph_low",
                alert_value=ph_value,
                threshold=self.thresholds.orange_ph,
                message=f"【橙色告警】书架 {shelf_id} 格口 {slot_id} pH值偏低：{ph_value:.2f}（阈值{self.thresholds.orange_ph}），酸化风险较高。"
            ))
        elif ph_value < self.thresholds.yellow_ph:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                timestamp=now,
                shelf_id=shelf_id,
                slot_id=slot_id,
                alert_level="yellow",
                alert_type="ph_low",
                alert_value=ph_value,
                threshold=self.thresholds.yellow_ph,
                message=f"【黄色提醒】书架 {shelf_id} 格口 {slot_id} pH值略低：{ph_value:.2f}（阈值{self.thresholds.yellow_ph}），请注意监控。"
            ))

        return alerts

    def _check_mold(self, mold_spore: float, temperature: float, humidity: float,
                    shelf_id: str, slot_id: str) -> List[Alert]:
        """检查霉菌孢子浓度告警"""
        alerts = []
        now = datetime.now().isoformat()

        orange_mold = self.thresholds.yellow_mold * 4
        red_mold = self.thresholds.yellow_mold * 10

        if mold_spore > self.thresholds.yellow_mold:
            level = "yellow"
            msg = f"【黄色提醒】书架 {shelf_id} 格口 {slot_id} 霉菌孢子浓度偏高：{mold_spore:.0f} CFU/m³（阈值{self.thresholds.yellow_mold}）"

            if mold_spore > orange_mold:
                level = "orange"
                msg = f"【橙色告警】书架 {shelf_id} 格口 {slot_id} 霉菌孢子浓度过高：{mold_spore:.0f} CFU/m³，存在霉变风险！"
            if mold_spore > red_mold:
                level = "red"
                msg = f"【红色告警】书架 {shelf_id} 格口 {slot_id} 霉菌孢子浓度严重超标：{mold_spore:.0f} CFU/m³，请立即采取防霉措施！"

            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                timestamp=now,
                shelf_id=shelf_id,
                slot_id=slot_id,
                alert_level=level,
                alert_type="mold_spore_high",
                alert_value=mold_spore,
                threshold=self.thresholds.yellow_mold,
                message=msg
            ))

        return alerts

    def _check_light(self, light: float, shelf_id: str, slot_id: str) -> List[Alert]:
        """检查光照强度告警"""
        alerts = []
        now = datetime.now().isoformat()

        red_light = self.thresholds.orange_light * 2

        if light > self.thresholds.orange_light:
            level = "orange"
            msg = f"【橙色告警】书架 {shelf_id} 格口 {slot_id} 光照强度超标：{light:.1f} lux（阈值{self.thresholds.orange_light}）"

            if light > red_light:
                level = "red"
                msg = f"【红色告警】书架 {shelf_id} 格口 {slot_id} 光照强度严重超标：{light:.1f} lux，纸张光老化风险极高！"

            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                timestamp=now,
                shelf_id=shelf_id,
                slot_id=slot_id,
                alert_level=level,
                alert_type="light_high",
                alert_value=light,
                threshold=self.thresholds.orange_light,
                message=msg
            ))

        return alerts

    def send_dingtalk_alert(self, alert: Alert) -> bool:
        """
        发送钉钉机器人告警
        """
        if not self.dingtalk_webhook:
            logger.warning("未配置钉钉机器人Webhook，跳过发送")
            return False

        try:
            level_emoji = {
                "red": "🔴",
                "orange": "🟠",
                "yellow": "🟡"
            }.get(alert.alert_level, "ℹ️")

            title = f"{level_emoji} 古籍馆藏微环境告警"

            markdown_text = f"""
### {title}

**告警级别**：{self._level_text(alert.alert_level)}
**告警类型**：{self._type_text(alert.alert_type)}
**位置**：书架 {alert.shelf_id} / 格口 {alert.slot_id}
**检测值**：{alert.alert_value}
**阈值**：{alert.threshold}
**时间**：{alert.timestamp}

**详情**：
> {alert.message}

---
*古代医学文献馆藏微环境监测系统*
"""

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": markdown_text
                },
                "at": {
                    "isAtAll": alert.alert_level == "red"
                }
            }

            response = requests.post(
                self.dingtalk_webhook,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            result = response.json()
            if result.get("errcode") == 0:
                logger.info(f"钉钉告警发送成功: {alert.alert_id}")
                return True
            else:
                logger.error(f"钉钉告警发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"发送钉钉告警异常: {e}")
            return False

    def send_email_alert(self, alert: Alert, to_emails: List[str]) -> bool:
        """
        发送邮件告警
        """
        if not self.smtp_config:
            logger.warning("未配置SMTP，跳过邮件发送")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_config.get("sender", "monitor@library.com")
            msg["To"] = ", ".join(to_emails)
            msg["Subject"] = f"[{self._level_text(alert.alert_level)}] 古籍馆藏微环境告警"

            body = f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <div style="background-color: {self._level_color(alert.alert_level)}; color: white; padding: 15px; border-radius: 5px;">
        <h2 style="margin: 0;">古籍馆藏微环境告警</h2>
    </div>
    <div style="padding: 20px; background-color: #f5f5f5; border-radius: 5px; margin-top: 10px;">
        <p><strong>告警级别：</strong>{self._level_text(alert.alert_level)}</p>
        <p><strong>告警类型：</strong>{self._type_text(alert.alert_type)}</p>
        <p><strong>位置：</strong>书架 {alert.shelf_id} / 格口 {alert.slot_id}</p>
        <p><strong>检测值：</strong>{alert.alert_value}</p>
        <p><strong>阈值：</strong>{alert.threshold}</p>
        <p><strong>时间：</strong>{alert.timestamp}</p>
        <hr>
        <p><strong>详细信息：</strong></p>
        <p style="background-color: #fff; padding: 10px; border-left: 4px solid {self._level_color(alert.alert_level)};">
            {alert.message}
        </p>
    </div>
    <p style="color: #999; font-size: 12px; margin-top: 20px;">
        此邮件由古代医学文献馆藏微环境监测系统自动发送，请勿直接回复。
    </p>
</body>
</html>
"""

            msg.attach(MIMEText(body, "html", "utf-8"))

            with smtplib.SMTP(
                self.smtp_config.get("host", "localhost"),
                self.smtp_config.get("port", 25)
            ) as server:
                if self.smtp_config.get("use_tls", False):
                    server.starttls()
                if self.smtp_config.get("username"):
                    server.login(
                        self.smtp_config["username"],
                        self.smtp_config.get("password", "")
                    )
                server.sendmail(
                    self.smtp_config.get("sender", "monitor@library.com"),
                    to_emails,
                    msg.as_string()
                )

            logger.info(f"邮件告警发送成功: {alert.alert_id}")
            return True

        except Exception as e:
            logger.error(f"发送邮件告警异常: {e}")
            return False

    def push_alert(self, alert: Alert, to_emails: List[str] = None) -> Dict:
        """
        推送告警（钉钉 + 邮件）
        """
        results = {
            "alert_id": alert.alert_id,
            "dingtalk": False,
            "email": False
        }

        if self.dingtalk_webhook:
            results["dingtalk"] = self.send_dingtalk_alert(alert)

        if to_emails and self.smtp_config:
            results["email"] = self.send_email_alert(alert, to_emails)

        return results

    def _level_text(self, level: str) -> str:
        return {
            "red": "红色",
            "orange": "橙色",
            "yellow": "黄色"
        }.get(level, level)

    def _level_color(self, level: str) -> str:
        return {
            "red": "#f44336",
            "orange": "#ff9800",
            "yellow": "#ffc107"
        }.get(level, "#9e9e9e")

    def _type_text(self, alert_type: str) -> str:
        type_map = {
            "ph_low": "pH值偏低",
            "mold_spore_high": "霉菌孢子浓度高",
            "light_high": "光照强度超标",
            "active_mold": "活性霉菌检测"
        }
        return type_map.get(alert_type, alert_type)

    def cleanup_old_alerts(self):
        """清理过期的告警记录（用于去重）"""
        now = datetime.now()
        to_remove = []
        for key, timestamp in self._recent_alerts.items():
            if (now - timestamp).total_seconds() > self._dedup_window * 2:
                to_remove.append(key)
        for key in to_remove:
            del self._recent_alerts[key]
