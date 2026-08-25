"""Canonical event schema — the only event shape the PayTwin core understands."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

CANONICAL_SCHEMA_VERSION = 1

Cohort = dict  # keys: issuer, method, psp, gateway (all optional-but-normalized)


def cohort_key(c: Cohort | None) -> str:
    """Stable 'HDFC|upi_intent|cashfree|gw1' key for cohort grouping."""
    c = c or {}
    return "|".join(str(c.get(k, "*")) for k in ("issuer", "method", "psp", "gateway"))


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = CANONICAL_SCHEMA_VERSION
    type: str  # EventType value; kept str for forward-compat validation below
    organization_id: str
    merchant_id: str
    provider: str
    external_event_id: str = Field(min_length=3, max_length=200)
    occurred_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payment_ref: str = Field(min_length=1, max_length=200)
    amount_paise: int = Field(ge=0)
    currency: str = "INR"
    cohort: Cohort = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    late: bool = False

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        from paytwin_contracts.enums import EventType

        allowed = {e.value for e in EventType}
        if v not in allowed:
            raise ValueError(f"unknown canonical event type: {v}")
        return v

    @field_validator("currency")
    @classmethod
    def _inr_only_v1(cls, v: str) -> str:
        if v != "INR":
            raise ValueError("v1 supports INR only")
        return v

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    def cohort_key(self) -> str:
        return cohort_key(self.cohort)
