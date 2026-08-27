"""Operational readiness and safe-reconciliation regression tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from paytwin_api.auth import AuthError, Principal
from paytwin_api.models import Integration, Merchant, Organization, Payment, Refund
from paytwin_api.routers.operations import reconcile, status
from paytwin_api.services.reconciliation import reconcile_financial_state


def _seed(db):
    db.add(Organization(id="org_ops", name="Ops"))
    db.add(Merchant(id="mer_ops", organization_id="org_ops", name="Ops Merchant", short_code="OP"))
    db.commit()


def _admin():
    return Principal(organization_id="org_ops", role="risk_admin", key_prefix="ptw_ops",
                     user_id="ops-admin")


def test_reconciliation_settles_only_already_captured_pending_refunds_and_retires_expired_ref(db):
    _seed(db)
    now = datetime.now(timezone.utc)
    payment = Payment(organization_id="org_ops", merchant_id="mer_ops", group_id="g1",
                      provider="razorpay", payment_ref="pay_ops", order_ref="order_ops",
                      amount_paise=5_000, status="success", occurred_at=now)
    db.add(payment); db.flush()
    refund = Refund(organization_id="org_ops", merchant_id="mer_ops", payment_id=payment.id,
                    provider="razorpay", refund_ref="refund_ops", amount_paise=2_000,
                    status="pending_reconciliation")
    integration = Integration(organization_id="org_ops", merchant_id="mer_ops",
                              provider="razorpay", secret_ref="PTW_NEW",
                              previous_secret_ref="PTW_OLD",
                              previous_secret_expires_at=now - timedelta(minutes=1))
    db.add_all([refund, integration]); db.commit()

    result = reconcile_financial_state(db, "org_ops")
    assert result["pending_refunds_examined"] == 1
    assert result["expired_secret_references_retired"] == 1
    assert refund.status == "processed"
    assert payment.refunded_amount_paise == 2_000 and payment.status == "success"
    assert integration.previous_secret_ref is None


def test_operations_status_is_tenant_scoped_and_reconcile_requires_admin(db):
    _seed(db)
    integration = Integration(organization_id="org_ops", merchant_id="mer_ops",
                              provider="razorpay", status="test_mode")
    db.add(integration); db.commit()

    out = status(_admin(), db)
    assert out["mode"] == "sandbox-only"
    assert out["integrations"] == [{"provider": "razorpay", "merchant_id": "mer_ops",
                                    "test_mode": True, "last_webhook_at": None,
                                    "last_healthcheck_at": None}]
    with pytest.raises(AuthError):
        reconcile(Principal(organization_id="org_ops", role="finance_viewer", key_prefix="ptw_fin"), db)
    result = reconcile(_admin(), db)
    assert result["ok"] is True and result["mode"] == "local_reconciliation_only"
