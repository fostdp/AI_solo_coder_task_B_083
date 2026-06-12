"""
告警分级引擎与通知推送
分级：黄(YELLOW) / 橙(ORANGE) / 红(RED)
推送：钉钉机器人 Webhook + SMTP 邮件
"""
import json
import time
import uuid
import hmac
import base64
import hashlib
import logging
import smtplib
import urllib.parse
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional, Any

import httpx

from ..config import settings, ALERT_LEVELS, ALERT_TYPES
from ..database import get_ch

logger = logging.getLogger(__name__)


class AlertEngine:

    def __init__(self):
        self.ch = get_ch()
        self._alert_cooldown: Dict[str, float] = {}
        self._cooldown_seconds = {
            "RED": 1800,
            "ORANGE": 3600,
            "YELLOW": 7200,
        }

    def check_ph_alert(self, payload: Dict[str, Any]):
        ph = float(payload.get("ph_value", 7.0))
        sensor_id = payload.get("sensor_id", "")
        shelf_id = payload.get("shelf_id", "")
        slot_id = payload.get("slot_id", "")

        if ph < settings.alert_threshold_ph_red:
            self._trigger_alert(
                "RED", "ACIDOSIS", shelf_id, slot_id, sensor_id,
                ph, settings.alert_threshold_ph_red,
                f"纸张严重酸化 pH={ph:.2f}<{settings.alert_threshold_ph_red}, 建议立即脱酸处理"
            )
        elif ph < settings.alert_threshold_ph_orange:
            self._trigger_alert(
                "ORANGE", "ACIDOSIS", shelf_id, slot_id, sensor_id,
                ph, settings.alert_threshold_ph_orange,
                f"纸张中度酸化 pH={ph:.2f}<{settings.alert_threshold_ph_orange}"
            )
        elif ph < settings.alert_threshold_ph_yellow:
            self._trigger_alert(
                "YELLOW", "ACIDOSIS", shelf_id, slot_id, sensor_id,
                ph, settings.alert_threshold_ph_yellow,
                f"纸张轻度酸化 pH={ph:.2f}<{settings.alert_threshold_ph_yellow}"
            )

    def check_env_alert(self, payload: Dict[str, Any]):
        sensor_id = payload.get("sensor_id", "")
        shelf_id = payload.get("shelf_id", "")
        slot_id = payload.get("slot_id", "")

        active_mold = int(payload.get("active_mold", 0))
        if active_mold:
            self._trigger_alert(
                "RED", "ACTIVE_MOLD", shelf_id, slot_id, sensor_id,
                1.0, 0.5, "检测到活性霉菌，需立即隔离并熏蒸处理"
            )

        mold = float(payload.get("mold_spores", 0.0))
        if mold > settings.alert_threshold_mold_spores_red:
            self._trigger_alert(
                "RED", "MOLD", shelf_id, slot_id, sensor_id,
                mold, settings.alert_threshold_mold_spores_red,
                f"霉菌孢子严重超标 {mold:.0f}>{settings.alert_threshold_mold_spores_red} CFU/m³"
            )
        elif mold > settings.alert_threshold_mold_spores_orange:
            self._trigger_alert(
                "ORANGE", "MOLD", shelf_id, slot_id, sensor_id,
                mold, settings.alert_threshold_mold_spores_orange,
                f"霉菌孢子中度超标 {mold:.0f}>{settings.alert_threshold_mold_spores_orange} CFU/m³"
            )
        elif mold > settings.alert_threshold_mold_spores_yellow:
            self._trigger_alert(
                "YELLOW", "MOLD", shelf_id, slot_id, sensor_id,
                mold, settings.alert_threshold_mold_spores_yellow,
                f"霉菌孢子轻度超标 {mold:.0f}>{settings.alert_threshold_mold_spores_yellow} CFU/m³"
            )

        light = float(payload.get("light_lux", 0.0))
        if light > settings.alert_threshold_light_red:
            self._trigger_alert(
                "RED", "LIGHT", shelf_id, slot_id, sensor_id,
                light, settings.alert_threshold_light_red,
                f"光照严重过强 {light:.1f}>{settings.alert_threshold_light_red} lux, 古籍有褪色风险"
            )
        elif light > settings.alert_threshold_light_orange:
            self._trigger_alert(
                "ORANGE", "LIGHT", shelf_id, slot_id, sensor_id,
                light, settings.alert_threshold_light_orange,
                f"光照中度超标 {light:.1f}>{settings.alert_threshold_light_orange} lux"
            )

    def _trigger_alert(
        self,
        level: str,
        alert_type: str,
        shelf_id: str,
        slot_id: str,
        sensor_id: str,
        trigger_value: float,
        threshold_value: float,
        description: str,
    ):
        key = f"{level}:{alert_type}:{shelf_id}:{slot_id or 'all'}"
        now = time.time()
        cooldown = self._cooldown_seconds.get(level, 3600)
        if key in self._alert_cooldown:
            if now - self._alert_cooldown[key] < cooldown:
                return
        self._alert_cooldown[key] = now

        event_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).timestamp() * 1000
        try:
            self.ch.insert("alert_events", [{
                "event_id": event_id,
                "timestamp": ts,
                "alert_level": level,
                "alert_type": alert_type,
                "shelf_id": shelf_id,
                "slot_id": slot_id,
                "sensor_id": sensor_id,
                "trigger_value": trigger_value,
                "threshold_value": threshold_value,
                "description": description,
            }])
        except Exception as e:
            logger.error(f"Save alert event failed: {e}")

        self._push_notifications(level, alert_type, description, shelf_id, slot_id, sensor_id)

    def _push_notifications(
        self, level: str, alert_type: str, desc: str,
        shelf_id: str, slot_id: str, sensor_id: str,
    ):
        level_meta = ALERT_LEVELS.get(level, {})
        type_name = ALERT_TYPES.get(alert_type, alert_type)
        title = f"{level_meta.get('emoji', '')} {level_meta.get('name', '')} - {type_name}"
        text = (
            f"**{title}**\n\n"
            f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📚 书架: {shelf_id}\n"
            f"📖 格口: {slot_id or '全局'}\n"
            f"📡 传感器: {sensor_id}\n"
            f"📝 详情: {desc}"
        )
        if settings.dingtalk_webhook:
            try:
                self._send_dingtalk(title, text, level)
            except Exception as e:
                logger.error(f"DingTalk push failed: {e}")
        else:
            logger.info(f"[DingTalk disabled] {title} | {desc}")

        try:
            self._send_email(title, text, level)
        except Exception as e:
            logger.error(f"Email push failed: {e}")

    def _send_dingtalk(self, title: str, text: str, level: str):
        url = settings.dingtalk_webhook
        if settings.dingtalk_secret:
            timestamp = str(round(time.time() * 1000))
            secret = settings.dingtalk_secret
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(
                secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url = f"{url}&timestamp={timestamp}&sign={sign}"

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {"isAtAll": level in ("RED", "ORANGE")},
        }
        headers = {"Content-Type": "application/json;charset=utf-8"}
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                result = r.json()
                if result.get("errcode") == 0:
                    logger.info(f"DingTalk sent: {title}")
                else:
                    logger.warning(f"DingTalk API error: {result}")
            else:
                logger.error(f"DingTalk HTTP {r.status_code}: {r.text}")

    def _send_email(self, title: str, markdown_text: str, level: str):
        receivers = settings.alert_email_receivers
        if not receivers or not settings.smtp_host:
            logger.info(f"[Email disabled] {title}")
            return

        html_body = markdown_text.replace("\n", "<br>").replace("**", "<b>").replace("##", "<h3>")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[馆藏监测] {title}"
        msg["From"] = settings.smtp_user
        msg["To"] = ", ".join(receivers)

        level_color = ALERT_LEVELS.get(level, {}).get("color", "#666")
        html = f"""
        <div style="font-family: 'Microsoft YaHei', sans-serif; padding: 20px; max-width: 680px;">
            <div style="padding: 12px 20px; background: {level_color}; color: #fff;
                        border-radius: 6px; font-size: 16px; font-weight: bold;">
                {title}
            </div>
            <div style="margin-top: 16px; padding: 16px; background: #f9fafb; border-radius: 6px;
                        line-height: 1.8; font-size: 14px; color: #111827;">
                {html_body}
            </div>
            <div style="margin-top: 20px; font-size: 12px; color: #9ca3af;">
                此邮件由古代医学文献馆藏微环境监测系统自动发送
            </div>
        </div>
        """
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            if settings.smtp_use_ssl:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
                server.starttls()
            if settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, receivers, msg.as_string())
            server.quit()
            logger.info(f"Email sent to {receivers}: {title}")
        except Exception as e:
            logger.error(f"SMTP error: {e}")
            raise


alert_engine = AlertEngine()
