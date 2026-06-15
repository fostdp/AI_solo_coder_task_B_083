import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class OCRCacheConfig:
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD", None)
    USE_FAKE_REDIS: bool = os.getenv("USE_FAKE_REDIS", "true").lower() == "true"

    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

    SCHEDULED_HOUR: int = int(os.getenv("SCHEDULED_HOUR", "2"))
    SCHEDULED_MINUTE: int = int(os.getenv("SCHEDULED_MINUTE", "0"))

    CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    CLICKHOUSE_PORT: int = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER", "default")
    CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    CLICKHOUSE_DATABASE: str = os.getenv("CLICKHOUSE_DATABASE", "ancient_medical_books")

    CLICKHOUSE_POOL_NAME: str = "ocr_cache"
    CLICKHOUSE_POOL_SIZE: int = 2

    FASTAPI_HOST: str = os.getenv("FASTAPI_HOST", "0.0.0.0")
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT", "8001"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = OCRCacheConfig()
