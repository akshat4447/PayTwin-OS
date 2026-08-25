"""Action execution on the connector (capability-gated, deterministic for the simulator)."""
from __future__ import annotations

from paytwin_api.connectors.base import Capabilities, WebhookRejected


def execute_action(connector, kind: str, params: dict, idempotency_key: str,
                   secret: str) -> dict:
    """Dispatch a money-affecting action. Returns outcome dict. Raises on refusal."""
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
    return fn(kind=kind, params=params, idempotency_key=idempotency_key, secret=secret)
