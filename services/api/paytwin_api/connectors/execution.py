"""Action execution on the connector (capability-gated, deterministic for the simulator)."""
from __future__ import annotations

from paytwin_api.connectors.base import Capabilities, WebhookRejected


class RetryableActionError(RuntimeError):
    """A provider-side transient where retry is safe but bounded."""


def execute_action(connector, kind: str, params: dict, idempotency_key: str,
                   secret: str) -> dict:
    """Dispatch a money-affecting action. Returns outcome dict. Raises on refusal."""
    fault = str(params.get("failure_mode") or "")
    if fault in {"timeout", "rate_limit", "provider_5xx"}:
        raise RetryableActionError(f"transient provider failure: {fault}")
    caps: Capabilities = connector.capabilities()
    needs = {
        "retry_burst": caps.direct_retry,
        "reroute_psp": True,          # routing switch is always available on our side
        "payment_link": caps.payment_link,
        "notify_customer": True,
        "calendar_shift": caps.payment_link,
        "escalate": True,
    }
    if not needs.get(kind, False):
        raise WebhookRejected(f"connector {connector.provider} lacks capability for {kind}")
    fn = getattr(connector, "perform_action", None)
    if fn is None:
        raise WebhookRejected(f"connector {connector.provider} has no perform_action")
    outcome = fn(kind=kind, params=params, idempotency_key=idempotency_key, secret=secret)
    if fault == "partial_success":
        outcome["partial_success"] = True
        outcome["partial_reason"] = "provider accepted only a bounded subset"
    return outcome
