"""MockProviderConnector — a deliberately different dialect to prove core is provider-agnostic.

Dialect: {"type": "charge.failed", "event_id": "mp_..", "ts": epoch,
          "charge": {"id": "ch_..", "amount_rupees": float, "network": {...}}}
"""
from __future__ import annotations

from paytwin_contracts import CanonicalEvent, paise

from paytwin_api.connectors.base import (
    Capabilities,
    PaymentProviderConnector,
    WebhookRejected,
    _epoch_to_dt,
    _ext_event_id,
    hmac_ok,
)

_TYPE_MAP = {
    "charge.created": "payment.created",
    "charge.captured": "payment.success",
    "charge.failed": "payment.failed",
    "charge.refunded": "refund.created",
}


class MockProviderConnector(PaymentProviderConnector):
    provider = "mockprovider"

    def verify_webhook(self, body: bytes, signature: str, secret: str) -> bool:
        return hmac_ok(body, signature, secret)

    def normalize(self, payload: dict, organization_id: str, merchant_id: str,
                  headers: dict | None = None) -> CanonicalEvent:
        try:
            raw_type = payload["type"]
            etype = _TYPE_MAP.get(raw_type)
            if etype is None:
                raise WebhookRejected(f"unknown mockprovider type {raw_type}")
            ch = payload["charge"]
            net = ch.get("network", {})
            cohort = {
                "issuer": net.get("bank"),
                "method": net.get("rail"),
                "psp": net.get("aggregator"),
                "gateway": net.get("gateway"),
            }
            from paytwin_api.config import get_settings
            from paytwin_api.connectors.base import pseudonymize_ref

            return CanonicalEvent(
                type=etype,
                organization_id=organization_id,
                merchant_id=merchant_id,
                provider=self.provider,
                external_event_id=_ext_event_id(payload, "event_id"),
                occurred_at=_epoch_to_dt(payload.get("ts")),
                payment_ref=str(ch["id"]),
                amount_paise=paise(float(ch["amount_rupees"])),
                cohort={k: v for k, v in cohort.items() if v},
                payload={
                    "failure_class": ch.get("decline_code"),
                    "latency_ms": ch.get("rtt_ms"),
                    "customer_ref": pseudonymize_ref(
                        ch.get("buyer_ref"), get_settings().hash_salt),
                    "order_ref": ch.get("order_id"),
                    "attempt_no": ch.get("attempt", 1),
                    "group_id": ch.get("session") or ch["id"],
                },
            )
        except WebhookRejected:
            raise
        except (KeyError, TypeError, ValueError) as e:
            raise WebhookRejected(f"malformed mockprovider payload: {e}") from e

    def capabilities(self) -> Capabilities:
        return Capabilities(payment_fetch=True, payment_link=False, downtime_feed=False,
                            direct_retry=False, refund=True)
