"""
系统全局配置
"""
from typing import List, Dict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "古代医学文献馆藏微环境监测与古籍病害预测系统"
    app_version: str = "1.0.0"
    debug: bool = True

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "ancient_med_lib"
    clickhouse_pool_size: int = 32

    mqtt_broker: str = "broker.emqx.io"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = "ancient_med_backend"
    mqtt_topic_env: str = "ancient_med/sensor/env/+"
    mqtt_topic_ph: str = "ancient_med/sensor/ph/+"

    mqtt_batch_size: int = 500
    mqtt_batch_interval: int = 3

    dingtalk_webhook: str = ""
    dingtalk_secret: str = ""

    smtp_host: str = "smtp.example.com"
    smtp_port: int = 465
    smtp_user: str = "alert@example.com"
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    alert_email_receivers: List[str] = ["curator@museum.com", "conservator@museum.com"]

    alert_threshold_ph_yellow: float = 6.5
    alert_threshold_ph_orange: float = 6.0
    alert_threshold_ph_red: float = 5.5

    alert_threshold_mold_spores_yellow: float = 500.0
    alert_threshold_mold_spores_orange: float = 1000.0
    alert_threshold_mold_spores_red: float = 1500.0

    alert_threshold_light_orange: float = 50.0
    alert_threshold_light_red: float = 100.0

    sensor_count_env: int = 50
    sensor_count_ph: int = 20

    prediction_aging_arrhenius_ea: float = 100.0
    prediction_aging_ref_temp: float = 25.0
    prediction_aging_base_rate: float = 0.15

    cors_origins: List[str] = ["*"]

    class Config:
        env_file = ".env"


settings = Settings()

ALERT_LEVELS: Dict[str, Dict] = {
    "RED": {"name": "红色告警", "priority": 1, "color": "#dc2626", "emoji": "🚨"},
    "ORANGE": {"name": "橙色告警", "priority": 2, "color": "#ea580c", "emoji": "⚠️"},
    "YELLOW": {"name": "黄色告警", "priority": 3, "color": "#ca8a04", "emoji": "⚡"},
}

ALERT_TYPES: Dict[str, str] = {
    "ACIDOSIS": "纸张酸化",
    "MOLD": "霉菌超标",
    "LIGHT": "光照过强",
    "INSECT": "虫蛀风险",
    "ACTIVE_MOLD": "活性霉菌检测",
}
