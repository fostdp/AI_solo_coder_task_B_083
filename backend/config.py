from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "古籍微环境监测系统"
    app_version: str = "1.0.0"
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "ancient_book_monitor"
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_env: str = "sensor/env/+"
    mqtt_topic_ph: str = "sensor/ph/+"
    sensor_count_env: int = 50
    sensor_count_ph: int = 20
    batch_size: int = 500
    batch_flush_interval: float = 30.0
    batch_max_retries: int = 3
    dingtalk_webhook: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""
    alert_cooldown_minutes: int = 30

    class Config:
        env_prefix = "ABM_"

settings = Settings()
