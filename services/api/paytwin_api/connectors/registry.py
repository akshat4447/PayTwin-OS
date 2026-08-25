"""Connector registry. Adding a provider = one entry here; core never changes."""
from __future__ import annotations

from paytwin_api.connectors.base import PaymentProviderConnector, WebhookRejected  # noqa: F401
from paytwin_api.connectors.mockprovider import MockProviderConnector
from paytwin_api.connectors.razorpay import RazorpayConnector
from paytwin_api.connectors.simulator import SimulatorConnector

_REGISTRY: dict[str, type] = {
    SimulatorConnector.provider: SimulatorConnector,
    MockProviderConnector.provider: MockProviderConnector,
    RazorpayConnector.provider: RazorpayConnector,
}

SUPPORTED_PROVIDERS = tuple(_REGISTRY)


def get_connector(provider: str) -> PaymentProviderConnector:
    cls = _REGISTRY.get(provider)
    if cls is None:
        raise WebhookRejected(f"unknown provider {provider}")
    return cls()  # type: ignore[return-value]
