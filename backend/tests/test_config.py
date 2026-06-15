import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.core.config import Config, ServiceConfig, setup_logging


class TestServiceConfig:
    def test_default_values(self):
        config = ServiceConfig()
        assert config.name == "古代医学文献馆藏微环境监测系统"
        assert config.version == "2.0.0"
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.log_level == "INFO"

    def test_custom_values(self):
        config = ServiceConfig(
            name="Test Service",
            version="1.0.0",
            host="127.0.0.1",
            port=9000,
            log_level="DEBUG"
        )
        assert config.name == "Test Service"
        assert config.version == "1.0.0"
        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.log_level == "DEBUG"


class TestConfigSingleton:
    def setup_method(self):
        Config._instance = None
        Config._loaded = False

    def test_singleton_pattern(self):
        config1 = Config()
        config2 = Config()
        assert config1 is config2

    def test_load_creates_instance(self):
        Config._instance = None
        config = Config.load()
        assert config is not None
        assert Config._instance is config
        assert config._loaded is True


class TestConfigLoading:
    def setup_method(self):
        Config._instance = None
        Config._loaded = False

    def test_default_config_when_no_file(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = f.name
        
        try:
            os.unlink(config_path)
            config = Config.load(config_path)
            
            assert isinstance(config.service, ServiceConfig)
            assert config.service.name == "古代医学文献馆藏微环境监测系统"
            assert config.clickhouse == {}
            assert config.mqtt == {}
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)

    def test_load_from_yaml_file(self):
        config_data = {
            "service": {
                "name": "Test Service",
                "port": 9090,
                "log_level": "DEBUG"
            },
            "clickhouse": {
                "host": "testhost",
                "port": 9999
            },
            "mqtt": {
                "broker": "test.mqtt.com"
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump(config_data, f)
            config_path = f.name
        
        try:
            Config._instance = None
            Config._loaded = False
            config = Config.load(config_path)
            
            assert config.service.name == "Test Service"
            assert config.service.port == 9090
            assert config.service.log_level == "DEBUG"
            assert config.service.version == "2.0.0"
            assert config.clickhouse["host"] == "testhost"
            assert config.clickhouse["port"] == 9999
            assert config.mqtt["broker"] == "test.mqtt.com"
        finally:
            os.unlink(config_path)

    def test_invalid_yaml_uses_default(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("invalid: yaml: [unclosed")
            config_path = f.name
        
        try:
            Config._instance = None
            Config._loaded = False
            config = Config.load(config_path)
            
            assert config.service.name == "古代医学文献馆藏微环境监测系统"
            assert config.clickhouse == {}
        finally:
            os.unlink(config_path)


class TestEnvOverrides:
    def setup_method(self):
        Config._instance = None
        Config._loaded = False

    def test_env_override_clickhouse(self, monkeypatch):
        monkeypatch.setenv("CLICKHOUSE_HOST", "env-host")
        monkeypatch.setenv("CLICKHOUSE_PORT", "12345")
        monkeypatch.setenv("CLICKHOUSE_USER", "env-user")
        monkeypatch.setenv("CLICKHOUSE_PASSWORD", "env-pass")
        
        config = Config.load()
        
        assert config.clickhouse["host"] == "env-host"
        assert config.clickhouse["port"] == 12345
        assert config.clickhouse["user"] == "env-user"
        assert config.clickhouse["password"] == "env-pass"

    def test_env_override_mqtt(self, monkeypatch):
        monkeypatch.setenv("MQTT_BROKER", "env-mqtt.com")
        monkeypatch.setenv("MQTT_PORT", "8883")
        monkeypatch.setenv("MQTT_USERNAME", "mqtt-user")
        monkeypatch.setenv("MQTT_PASSWORD", "mqtt-pass")
        
        config = Config.load()
        
        assert config.mqtt["broker"] == "env-mqtt.com"
        assert config.mqtt["port"] == 8883
        assert config.mqtt["username"] == "mqtt-user"
        assert config.mqtt["password"] == "mqtt-pass"

    def test_env_override_nested_notification(self, monkeypatch):
        monkeypatch.setenv("DINGTALK_WEBHOOK", "https://dingtalk.com/webhook")
        monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "smtp-user")
        monkeypatch.setenv("SMTP_PASSWORD", "smtp-pass")
        
        config = Config.load()
        
        assert config.notification["dingtalk"]["webhook"] == "https://dingtalk.com/webhook"
        assert config.notification["smtp"]["host"] == "smtp.test.com"
        assert config.notification["smtp"]["port"] == 587
        assert config.notification["smtp"]["username"] == "smtp-user"
        assert config.notification["smtp"]["password"] == "smtp-pass"

    def test_env_override_with_existing_config(self, monkeypatch):
        config_data = {
            "clickhouse": {
                "host": "file-host",
                "port": 8123
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump(config_data, f)
            config_path = f.name
        
        try:
            monkeypatch.setenv("CLICKHOUSE_HOST", "env-host")
            monkeypatch.setenv("CLICKHOUSE_PORT", "9999")
            
            Config._instance = None
            Config._loaded = False
            config = Config.load(config_path)
            
            assert config.clickhouse["host"] == "env-host"
            assert config.clickhouse["port"] == 9999
        finally:
            os.unlink(config_path)


class TestTypeConversion:
    def test_convert_bool(self):
        config = Config()
        
        assert config._convert_type("true", True) is True
        assert config._convert_type("1", True) is True
        assert config._convert_type("yes", True) is True
        assert config._convert_type("false", True) is False
        assert config._convert_type("0", True) is False
        assert config._convert_type("no", True) is False

    def test_convert_int(self):
        config = Config()
        
        assert config._convert_type("123", 0) == 123
        assert config._convert_type("-456", 0) == -456
        assert config._convert_type("invalid", 0) == "invalid"

    def test_convert_float(self):
        config = Config()
        
        assert config._convert_type("123.45", 0.0) == pytest.approx(123.45)
        assert config._convert_type("-67.89", 0.0) == pytest.approx(-67.89)
        assert config._convert_type("invalid", 0.0) == "invalid"

    def test_convert_list(self):
        config = Config()
        
        result = config._convert_type("a,b,c", [])
        assert result == ["a", "b", "c"]
        
        result = config._convert_type("item1, item2, item3", [])
        assert result == ["item1", "item2", "item3"]

    def test_convert_string(self):
        config = Config()
        
        assert config._convert_type("test", "") == "test"
        assert config._convert_type("123", "") == "123"


class TestConfigHelperMethods:
    def setup_method(self):
        Config._instance = None
        Config._loaded = False

    def test_get_arrhenius_config(self):
        config_data = {
            "algorithms": {
                "arrhenius": {
                    "R": 8.314,
                    "A": 1.0e10
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_path)
            arr_config = config.get_arrhenius_config()
            
            assert arr_config["R"] == 8.314
            assert arr_config["A"] == 1.0e10
        finally:
            os.unlink(config_path)

    def test_get_mold_config(self):
        config_data = {
            "algorithms": {
                "mold_growth": {
                    "opt_temp": 25.0,
                    "opt_humidity": 85.0
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_path)
            mold_config = config.get_mold_config()
            
            assert mold_config["opt_temp"] == 25.0
            assert mold_config["opt_humidity"] == 85.0
        finally:
            os.unlink(config_path)

    def test_get_alert_thresholds(self):
        config_data = {
            "alerts": {
                "thresholds": {
                    "yellow_ph": 6.5,
                    "orange_ph": 6.0
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_path)
            thresholds = config.get_alert_thresholds()
            
            assert thresholds["yellow_ph"] == 6.5
            assert thresholds["orange_ph"] == 6.0
        finally:
            os.unlink(config_path)

    def test_get_empty_configs(self):
        Config._instance = None
        Config._loaded = False
        
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = f.name
        
        try:
            os.unlink(config_path)
            config = Config.load(config_path)
            
            assert config.get_arrhenius_config() == {}
            assert config.get_mold_config() == {}
            assert config.get_alert_thresholds() == {}
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)


class TestSetupLogging:
    def test_setup_logging_basic(self, mock_config):
        import logging
        
        mock_config.logging = {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        }
        mock_config.service.log_level = "DEBUG"
        
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging(mock_config)
            
            mock_basic_config.assert_called_once()
            call_kwargs = mock_basic_config.call_args[1]
            assert call_kwargs["level"] == logging.DEBUG

    def test_setup_logging_with_file_handler(self, mock_config, tmp_path):
        import logging
        
        log_file = tmp_path / "test.log"
        mock_config.logging = {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "handlers": [
                {
                    "type": "file",
                    "filename": str(log_file),
                    "level": "WARNING"
                }
            ]
        }
        mock_config.service.log_level = "INFO"
        
        setup_logging(mock_config)
        
        root_logger = logging.getLogger()
        has_file_handler = any(
            isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file)
            for h in root_logger.handlers
        )
        assert has_file_handler
