"""RazorpayConnector — real dialect shape (sandbox-ready; verified against docs shape).

Razorpay webhooks: header `X-Razorpay-Signature`, body JSON {"event": "payment.failed",
"payload": {"payment": {"entity": {...}}}}. HMAC-SHA256 of raw body with webhook secret.
"""
from __future__ import annotations

from paytwin_contracts import CanonicalEvent

from paytwin_api.connectors.base import (
    Capabilities,
    PaymentProviderConnector,
    WebhookRejected,
    _epoch_to_dt,
    hmac_ok,
)

_EVENT_MAP = {
    "payment.authorized": "payment.authorized",
    "payment.failed": "payment.failed",
    "payment.captured": "payment.success",
    "refund.processed": "refund.created",
    "order.paid": "payment.success",
}


class RazorpayConnector(PaymentProviderConnector):
    provider = "razorpay"

    def verify_webhook(self, body: bytes, signature: str, secret: str) -> bool:
        return hmac_ok(body, signature, secret, scheme="")  # raw hex, no prefix

    def normalize(self, payload: dict, organization_id: str, merchant_id: str) -> CanonicalEvent:
        try:
            raw = payload["event"]
            etype = _EVENT_MAP.get(raw)
            if etype is None:
                raise WebhookRejected(f"unmapped razorpay event {raw}")
            ent = payload.get("payload", {}).get("payment", {}).get("entity", {})
            if not ent:
                raise WebhookRejected("missing payment entity")
            method = ent.get("method")
            vpa = ent.get("vpa")
            cohort = {
                "issuer": (ent.get("bank") or "").upper() or None,
                "method": method,
                "psp": "razorpay",
                "gateway": None,
            }
            if method == "upi" and vpa:
                cohort["method"] = "upi_intent"
            err = ent.get("error_description")
            return CanonicalEvent(
                type=etype,
                organization_id=organization_id,
                merchant_id=merchant_id,
                provider=self.provider,
                external_event_id=str(ent["id"]),
                occurred_at=_epoch_to_dt(ent.get("created_at")),
                payment_ref=str(ent["id"]),
                amount_paise=int(ent.get("amount", 0)),
                cohort={k: v for k, v in cohort.items() if v},
                payload={
                    "failure_class": (ent.get("error_source") or err or "issuer_decline"),
                    "latency_ms": None,
                    "customer_ref": ent.get("customer_id"),
                    "order_ref": ent.get("order_id"),
                    "attempt_no": 1,
                    "group_id": ent.get("order_id") or ent["id"],
                },
            )
        except WebhookRejected:
            raise
        except (KeyError, TypeError, ValueError) as e:
            raise WebhookRejected(f"malformed razorpay payload: {e}") from e

    def capabilities(self) -> Capabilities:
        return Capabilities(payment_fetch=True, payment_link=True, downtime_feed=True,
                            direct_retry=False, refund=True)
