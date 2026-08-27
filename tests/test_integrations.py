"""Hackathon Test Mode integration registry coverage."""
from __future__ import annotations

from paytwin_api.auth import Principal
from paytwin_api.models import Merchant, Organization
from paytwin_api.routers.integrations import ConnectBody, connect, list_integrations


def _principal(role: str = "risk_admin") -> Principal:
    return Principal(organization_id="org1", role=role, key_prefix="ptw_test",
                     user_id="demo-admin")


def test_connects_razorpay_test_mode_without_storing_a_secret(db):
    db.add(Organization(id="org1", name="Nova"))
    db.add(Merchant(id="mer1", organization_id="org1", name="Grocery", short_code="NG"))
    db.commit()

    out = connect(ConnectBody(merchant_id="mer1", provider="razorpay"), _principal(), db)
    assert out["provider"] == "razorpay"
    assert out["test_mode"] is True
    assert out["secret_ref"] == "PAYTWIN_WEBHOOK_SECRET_RAZORPAY"
    assert out["capabilities"]["payment_fetch"] is True

    listed = list_integrations(_principal(), db)
    assert listed["integrations"][0]["id"] == out["id"]
    assert "sandbox-only" in listed["execution_boundary"]


def test_rejects_live_mode_and_invalid_secret_reference(db):
    from paytwin_api.deps import err

    db.add(Organization(id="org1", name="Nova"))
    db.add(Merchant(id="mer1", organization_id="org1", name="Grocery", short_code="NG"))
    db.commit()

    live = connect(ConnectBody(merchant_id="mer1", provider="razorpay", test_mode=False),
                   _principal(), db)
    assert live.status_code == 422
    bad = connect(ConnectBody(merchant_id="mer1", provider="razorpay",
                              secret_ref="not-a-valid-env"), _principal(), db)
    assert bad.status_code == 422
