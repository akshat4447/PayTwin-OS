"""Connector framework: provider-neutral interface + capability contract (Phase 5).

Core intelligence NEVER imports a provider SDK — only this package touches dialects.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Protocol

from paytwin_contracts import CanonicalEvent


@dataclass(frozen=True)
class Capabilities:
    payment_fetch: bool = False
    payment_link: bool = True
    downtime_feed: bool = False
    direct_retry: bool = False
    refund: bool = False
    notes: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "payment_fetch": self.payment_fetch,
            "payment_link": self.payment_link,
            "downtime_feed": self.downtime_feed,
            "direct_retry": self.direct_retry,
            "refund": self.refund,
        }


class WebhookRejected(Exception):
    """Bad signature / malformed payload — caller must 4xx and dead-letter."""


class PaymentProviderConnector(Protocol):
    provider: str

    def verify_webhook(self, body: bytes, signature: str, secret: str) -> bool: ...
    def normalize(self, payload: dict, organization_id: str, merchant_id: str) -> CanonicalEvent: ...
    def capabilities(self) -> Capabilities: ...


def hmac_ok(body: bytes, signature: str, secret: str, scheme: str = "sha256=") -> bool:
    """Constant-time HMAC-SHA256 check. `signature` includes the scheme prefix."""
    if not signature.startswith(scheme):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(scheme + digest, signature)


def _ext_event_id(payload: dict, *keys: str) -> str:
    for k in keys:
        v = payload.get(k)
        if v:
            return str(v)
    raise WebhookRejected("missing event id")


def _epoch_to_dt(ts: Any):
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError) as e:
        raise WebhookRejected("bad created_at") from e
