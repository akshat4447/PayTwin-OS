"""Typed configuration. All env vars prefixed PAYTWIN_ (see .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYTWIN_", env_file=".env", extra="ignore")

    env: str = "development"  # development | production
    database_url: str = "sqlite:///./data/dev.db"
    redis_url: str = "redis://localhost:6380/0"

    secret_key: str = "dev-secret-change-me"
    webhook_secret_simulator: str = "sim-secret-dev"
    webhook_secret_mockprovider: str = "mock-secret-dev"
    webhook_secret_razorpay: str = "rzp-secret-dev"

    llm_provider: str = "none"  # none | openai | anthropic
    llm_api_key: str = ""

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    feature_version: str = "fv1"
    policy_version: str = "pv1"
    connector_version: str = "cv1"

    rate_limit_per_min: int = 240
    worker_poll_seconds: float = 0.5
    sse_interval_seconds: float = 2.0

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_prod(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
