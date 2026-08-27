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
    "refund.created": "refund.created",
    "refund.processed": "refund.created",
    "refund.failed": "refund.failed",
    "refund.speed_changed": "refund.updated",
    "order.paid": "order.paid",
}


class RazorpayConnector(PaymentProviderConnector):
    provider = "razorpay"

    def verify_webhook(self, body: bytes, signature: str, secret: str) -> bool:
        return hmac_ok(body, signature, secret, scheme="")  # raw hex, no prefix

    def normalize(self, payload: dict, organization_id: str, merchant_id: str,
                  headers: dict | None = None) -> CanonicalEvent:
        try:
            raw = payload["event"]
            etype = _EVENT_MAP.get(raw)
            if etype is None:
                raise WebhookRejected(f"unmapped razorpay event {raw}")
            envelope = payload.get("payload", {})
            payment = envelope.get("payment", {}).get("entity", {})
            refund = envelope.get("refund", {}).get("entity", {})
            # Refund webhooks carry both an independent refund entity and the
            # original payment entity.  The refund amount must NEVER be read
            # from the payment snapshot.
            if raw.startswith("refund."):
                if not refund or not refund.get("payment_id"):
                    raise WebhookRejected("missing refund entity or payment_id")
                payment_ref = str(refund["payment_id"])
                event_ref = str(refund.get("id") or payment_ref)
                amount_paise = int(refund.get("amount", 0))
                occurred_at = refund.get("created_at") or payload.get("created_at")
                ent = payment or {"id": payment_ref, "amount": 0}
            else:
                if not payment:
                    raise WebhookRejected("missing payment entity")
                payment_ref = str(payment["id"])
                event_ref = payment_ref
                amount_paise = int(payment.get("amount", 0))
                occurred_at = payment.get("created_at") or payload.get("created_at")
                ent = payment

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
            # Razorpay delivers a DISTINCT event id per webhook delivery
            # (X-Razorpay-Event-Id). Using payment.id instead made lifecycle
            # progress (authorized → captured, refunds, late auth) look like
            # duplicates and get dropped. Header first, composite fallback.
            ext = (headers or {}).get("x-razorpay-event-id")
            external_event_id = str(ext) if ext else f"{raw}:{event_ref}"
            from paytwin_api.config import get_settings
            from paytwin_api.connectors.base import pseudonymize_ref

            event_payload = {
                "failure_class": (ent.get("error_source") or err or "issuer_decline"),
                "latency_ms": None,
                "customer_ref": pseudonymize_ref(
                    ent.get("customer_id"), get_settings().hash_salt),
                "order_ref": ent.get("order_id"),
                "order_amount_paise": ent.get("amount"),
                "attempt_no": 1,
                "group_id": ent.get("order_id") or payment_ref,
                "source_event": raw,
            }
            if refund:
                event_payload.update({
                    "refund_ref": str(refund.get("id") or ""),
                    "refund_amount_paise": amount_paise,
                    "refund_status": refund.get("status") or raw.removeprefix("refund."),
                    "refund_receipt": refund.get("receipt"),
                    "refund_speed_requested": refund.get("speed_requested"),
                    "refund_speed_processed": refund.get("speed_processed"),
                    "payment_amount_paise": ent.get("amount"),
                })

            return CanonicalEvent(
                type=etype,
                organization_id=organization_id,
                merchant_id=merchant_id,
                provider=self.provider,
                external_event_id=external_event_id,
                occurred_at=_epoch_to_dt(occurred_at),
                payment_ref=payment_ref,
                amount_paise=amount_paise,
                cohort={k: v for k, v in cohort.items() if v},
                payload=event_payload,
            )
        except WebhookRejected:
            raise
        except (KeyError, TypeError, ValueError) as e:
            raise WebhookRejected(f"malformed razorpay payload: {e}") from e

    def capabilities(self) -> Capabilities:
        return Capabilities(payment_fetch=True, payment_link=True, downtime_feed=True,
                            direct_retry=False, refund=True)
