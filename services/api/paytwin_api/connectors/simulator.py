"""SimulatorConnector — the dialect used by paytwin_sim's emitter (and demos/tests)."""
from __future__ import annotations

from paytwin_contracts import CanonicalEvent

from paytwin_api.connectors.base import (
    Capabilities,
    PaymentProviderConnector,
    WebhookRejected,
    _epoch_to_dt,
    _ext_event_id,
    hmac_ok,
)

_STATUS_MAP = {
    "created": "payment.created",
    "authorized": "payment.authorized",
    "success": "payment.success",
    "failed": "payment.failed",
    "timeout": "payment.timeout",
}


class SimulatorConnector(PaymentProviderConnector):
    provider = "simulator"

    def verify_webhook(self, body: bytes, signature: str, secret: str) -> bool:
        return hmac_ok(body, signature, secret)

    def normalize(self, payload: dict, organization_id: str, merchant_id: str,
                  headers: dict | None = None) -> CanonicalEvent:
        try:
            etype = _STATUS_MAP[payload["event"]] if payload["event"] in _STATUS_MAP else payload["event"]
            data = payload["data"]
            ext_id = _ext_event_id(payload, "id")
            cohort = {
                "issuer": data.get("issuer"),
                "method": data.get("method"),
                "psp": data.get("psp"),
                "gateway": data.get("gateway"),
            }
            from paytwin_api.config import get_settings
            from paytwin_api.connectors.base import pseudonymize_ref

            return CanonicalEvent(
                type=etype,
                organization_id=organization_id,
                merchant_id=merchant_id,
                provider=self.provider,
                external_event_id=ext_id,
                occurred_at=_epoch_to_dt(payload.get("created_at")),
                payment_ref=str(data["payment_id"]),
                amount_paise=int(data["amount"]),
                cohort={k: v for k, v in cohort.items() if v},
                payload={
                    "failure_class": data.get("error_reason"),
                    "latency_ms": data.get("latency_ms"),
                    "customer_ref": pseudonymize_ref(
                        data.get("customer_ref"), get_settings().hash_salt),
                    "order_ref": data.get("order_id"),
                    "attempt_no": data.get("attempt_no", 1),
                    "group_id": data.get("group_id") or data["payment_id"],
                },
            )
        except WebhookRejected:
            raise
        except (KeyError, TypeError, ValueError) as e:
            raise WebhookRejected(f"malformed simulator payload: {e}") from e

    def capabilities(self) -> Capabilities:
        return Capabilities(payment_fetch=True, payment_link=True, downtime_feed=True,
                            direct_retry=True, refund=True)

    def perform_action(self, kind: str, params: dict, idempotency_key: str,
                       secret: str) -> dict:
        """Deterministic simulated execution: outcome derived from the idempotency key."""
        import hashlib

        seed = int(hashlib.sha256(idempotency_key.encode()).hexdigest()[:8], 16)
        count = int(params.get("count", 0))
        p_success = float(params.get("p_success", 0.35))
        # deterministic Bernoulli draws from the key-seeded PRNG
        outcomes = []
        state = seed
        for i in range(min(count, 100_000)):
            state = (state * 6364136223846793005 + 1442695040888963407) % (1 << 64)
            outcomes.append((state >> 33) / (1 << 63) < p_success)
        recovered = sum(1 for o in outcomes if o)
        return {
            "connector": self.provider,
            "kind": kind,
            "attempted": len(outcomes),
            "recovered": recovered,
            "recovered_paise": int(recovered * float(params.get("avg_amount_paise", 0))),
            "ref": f"{self.provider}_{idempotency_key[:12]}",
        }

