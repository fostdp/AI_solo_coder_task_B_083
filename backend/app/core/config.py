import os
import yaml
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ServiceConfig:
    name: str = "古代医学文献馆藏微环境监测系统"
    version: str = "2.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"


@dataclass
class Config:
    _instance: Optional["Config"] = None
    _loaded: bool = False

    service: ServiceConfig = field(default_factory=ServiceConfig)
    clickhouse: Dict[str, Any] = field(default_factory=dict)
    mqtt: Dict[str, Any] = field(default_factory=dict)
    batch_writer: Dict[str, Any] = field(default_factory=dict)
    aging_engine: Dict[str, Any] = field(default_factory=dict)
    mold_engine: Dict[str, Any] = field(default_factory=dict)
    algorithms: Dict[str, Any] = field(default_factory=dict)
    alerts: Dict[str, Any] = field(default_factory=dict)
    notification: Dict[str, Any] = field(default_factory=dict)
    shelf_layout: Dict[str, Any] = field(default_factory=dict)
    data_validation: Dict[str, Any] = field(default_factory=dict)
    logging: Dict[str, Any] = field(default_factory=dict)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def load(cls, config_path: str = None) -> "Config":
        if cls._instance is None or not cls._instance._loaded:
            cls._instance = cls()
            cls._instance._load_config(config_path)
            cls._instance._loaded = True
        return cls._instance

    def _load_config(self, config_path: str = None) -> None:
        if config_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            config_path = os.getenv("CONFIG_PATH", str(base_dir / "config.yaml"))

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"配置文件 {config_path} 不存在，使用默认配置")
            config_data = {}
        except yaml.YAMLError as e:
            logger.error(f"配置文件解析错误: {e}，使用默认配置")
            config_data = {}

        self._apply_config(config_data)
        self._apply_env_overrides()

        logger.info(f"配置加载完成: {config_path}")

    def _apply_config(self, config_data: Dict[str, Any]) -> None:
        if "service" in config_data:
            s = config_data["service"]
            self.service = ServiceConfig(
                name=s.get("name", self.service.name),
                version=s.get("version", self.service.version),
                host=s.get("host", self.service.host),
                port=s.get("port", self.service.port),
                log_level=s.get("log_level", self.service.log_level),
            )

        self.clickhouse = config_data.get("clickhouse", {})
        self.mqtt = config_data.get("mqtt", {})
        self.batch_writer = config_data.get("batch_writer", {})
        self.aging_engine = config_data.get("aging_engine", {})
        self.mold_engine = config_data.get("mold_engine", {})
        self.algorithms = config_data.get("algorithms", {})
        self.alerts = config_data.get("alerts", {})
        self.notification = config_data.get("notification", {})
        self.shelf_layout = config_data.get("shelf_layout", {})
        self.data_validation = config_data.get("data_validation", {})
        self.logging = config_data.get("logging", {})

    def _apply_env_overrides(self) -> None:
        env_map = {
            "CLICKHOUSE_HOST": ("clickhouse", "host"),
            "CLICKHOUSE_PORT": ("clickhouse", "port"),
            "CLICKHOUSE_USER": ("clickhouse", "user"),
            "CLICKHOUSE_PASSWORD": ("clickhouse", "password"),
            "MQTT_BROKER": ("mqtt", "broker"),
            "MQTT_PORT": ("mqtt", "port"),
            "MQTT_USERNAME": ("mqtt", "username"),
            "MQTT_PASSWORD": ("mqtt", "password"),
            "DINGTALK_WEBHOOK": ("notification", "dingtalk", "webhook"),
            "SMTP_HOST": ("notification", "smtp", "host"),
            "SMTP_PORT": ("notification", "smtp", "port"),
            "SMTP_USER": ("notification", "smtp", "username"),
            "SMTP_PASSWORD": ("notification", "smtp", "password"),
        }

        for env_key, config_path in env_map.items():
            value = os.getenv(env_key)
            if value is not None:
                d = self.__dict__
                for key in config_path[:-1]:
                    if key not in d:
                        d[key] = {}
                    d = d[key]
                last_key = config_path[-1]
                d[last_key] = self._convert_type(value, d.get(last_key))

    def _convert_type(self, value: str, target_type: Any) -> Any:
        if isinstance(target_type, bool):
            return value.lower() in ("true", "1", "yes")
        elif isinstance(target_type, int):
            try:
                return int(value)
            except ValueError:
                return value
        elif isinstance(target_type, float):
            try:
                return float(value)
            except ValueError:
                return value
        elif isinstance(target_type, list):
            return [item.strip() for item in value.split(",")]
        return value

    def get_arrhenius_config(self) -> Dict[str, Any]:
        return self.algorithms.get("arrhenius", {})

    def get_mold_config(self) -> Dict[str, Any]:
        return self.algorithms.get("mold_growth", {})

    def get_alert_thresholds(self) -> Dict[str, float]:
        return self.alerts.get("thresholds", {})


def setup_logging(config: Config) -> None:
    log_config = config.logging
    log_format = log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    log_level = getattr(logging, config.service.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
        ],
    )

    for handler_config in log_config.get("handlers", []):
        if handler_config.get("type") == "file":
            file_handler = logging.FileHandler(handler_config.get("filename", "app.log"))
            file_handler.setFormatter(logging.Formatter(log_format))
            file_handler.setLevel(getattr(logging, handler_config.get("level", "WARNING").upper(), logging.WARNING))
            logging.getLogger().addHandler(file_handler)


config = Config.load()
