import os
from typing import Dict, Any


class Settings:
    CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    CLICKHOUSE_PORT: int = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER", "default")
    CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    CLICKHOUSE_DATABASE: str = os.getenv("CLICKHOUSE_DATABASE", "ancient_medical_books")

    MQTT_BROKER: str = os.getenv("MQTT_BROKER", "localhost")
    MQTT_PORT: int = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_USERNAME: str = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD", "")
    MQTT_TOPIC_ENV: str = os.getenv("MQTT_TOPIC_ENV", "library/env/+")
    MQTT_TOPIC_PH: str = os.getenv("MQTT_TOPIC_PH", "library/ph/+")

    DINGTALK_WEBHOOK: str = os.getenv("DINGTALK_WEBHOOK", "")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "25"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_SENDER: str = os.getenv("SMTP_SENDER", "monitor@library.com")
    ALERT_EMAILS: list = os.getenv("ALERT_EMAILS", "admin@library.com").split(",")

    FASTAPI_HOST: str = os.getenv("FASTAPI_HOST", "0.0.0.0")
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT", "8000"))

    BATCH_WRITE_SIZE: int = int(os.getenv("BATCH_WRITE_SIZE", "100"))
    BATCH_WRITE_INTERVAL: int = int(os.getenv("BATCH_WRITE_INTERVAL", "5"))

    TOTAL_SHELVES: int = int(os.getenv("TOTAL_SHELVES", "10"))
    SLOTS_PER_SHELF: int = int(os.getenv("SLOTS_PER_SHELF", "12"))
    ENV_SENSOR_COUNT: int = int(os.getenv("ENV_SENSOR_COUNT", "50"))
    PH_SENSOR_COUNT: int = int(os.getenv("PH_SENSOR_COUNT", "20"))

    ALERT_YELLOW_PH: float = float(os.getenv("ALERT_YELLOW_PH", "6.5"))
    ALERT_ORANGE_PH: float = float(os.getenv("ALERT_ORANGE_PH", "6.0"))
    ALERT_RED_PH: float = float(os.getenv("ALERT_RED_PH", "5.5"))
    ALERT_YELLOW_MOLD: float = float(os.getenv("ALERT_YELLOW_MOLD", "500.0"))
    ALERT_ORANGE_LIGHT: float = float(os.getenv("ALERT_ORANGE_LIGHT", "50.0"))


settings = Settings()
