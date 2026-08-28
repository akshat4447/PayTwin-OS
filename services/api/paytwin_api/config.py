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
    # Development-only local Razorpay-compatible Checkout signature key. It is
    # deliberately distinct from the webhook HMAC and is rejected in prod when
    # left at this value. A real Razorpay Test Mode secret is supplied only via
    # a server-side environment reference on the integration.
    razorpay_key_secret: str = "rzp-checkout-secret-dev"
    hash_salt: str = "dev-hash-salt"  # salt for customer_ref pseudonymization

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

    # Real-PSP execution is sandbox/demo-only until a provider integration is
    # certified; flip explicitly per-environment (never in production).
    allow_real_execution: bool = False

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_prod(self) -> bool:
        return self.env == "production"

    _DEV_SECRET_DEFAULTS = {
        "dev-secret-change-me", "sim-secret-dev", "mock-secret-dev",
        "rzp-secret-dev", "rzp-checkout-secret-dev", "dev-hash-salt",
    }

    def validate_for_env(self) -> None:
        """Fail fast on unsafe production configuration (startup gate)."""
        if not self.is_prod:
            return
        problems: list[str] = []
        if self.is_sqlite:
            problems.append("sqlite database_url is not a production datastore")
        if self.secret_key in self._DEV_SECRET_DEFAULTS or len(self.secret_key) < 32:
            problems.append("secret_key is a known default or too short (<32 chars)")
        for name in ("webhook_secret_simulator", "webhook_secret_mockprovider",
                     "webhook_secret_razorpay", "razorpay_key_secret", "hash_salt"):
            if getattr(self, name) in self._DEV_SECRET_DEFAULTS:
                problems.append(f"{name} is still a development default")
        if self.allow_real_execution:
            problems.append("allow_real_execution must be false in production "
                            "(real PSP execution is sandbox-only)")
        if problems:
            raise RuntimeError(
                "PAYTWIN production configuration invalid: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
