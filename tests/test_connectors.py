"""CONN-001: connector framework — HMAC, dialect normalization, capability contracts.

Key proof: the SAME canonical event emerges from two different provider dialects,
and core logic can treat both identically.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from paytwin_api.connectors import get_connector
from paytwin_api.connectors.base import WebhookRejected, hmac_ok

SECRET = "test-secret"
BODY = b'{"hello":"world"}'


def _sig(body: bytes, secret: str = SECRET, scheme: str = "sha256=") -> str:
    return scheme + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestHmac:
    def test_valid(self):
        assert hmac_ok(BODY, _sig(BODY), SECRET)

    def test_bad_secret(self):
        assert not hmac_ok(BODY, _sig(BODY, "other"), SECRET)

    def test_bad_scheme(self):
        assert not hmac_ok(BODY, _sig(BODY), SECRET, scheme="sha512=")

    def test_tampered_body(self):
        assert not hmac_ok(BODY + b"x", _sig(BODY), SECRET)


class TestSimulatorDialect:
    def test_verify_and_normalize(self):
        c = get_connector("simulator")
        payload = {
            "event": "failed", "id": "evt_sim_1", "created_at": 1750000000,
            "data": {"payment_id": "pay_1", "order_id": "ord_1", "amount": 129900,
                     "method": "upi_intent", "issuer": "HDFC", "psp": "cashfree",
                     "gateway": "gw1", "error_reason": "issuer_decline",
                     "customer_ref": "c_1", "attempt_no": 2, "group_id": "grp_1"},
        }
        raw = json.dumps(payload).encode()
        assert c.verify_webhook(raw, _sig(raw), SECRET)
        e = c.normalize(payload, "org1", "mer1")
        assert e.type == "payment.failed"
        assert e.external_event_id == "evt_sim_1"
        assert e.amount_paise == 129900
        assert e.cohort == {"issuer": "HDFC", "method": "upi_intent", "psp": "cashfree", "gateway": "gw1"}
        assert e.payload["failure_class"] == "issuer_decline"

    def test_malformed_rejected(self):
        c = get_connector("simulator")
        with pytest.raises(WebhookRejected):
            c.normalize({"event": "failed"}, "org1", "mer1")  # no data/id


class TestMockProviderDialect:
    def test_normalize(self):
        c = get_connector("mockprovider")
        payload = {
            "type": "charge.failed", "event_id": "mp_9", "ts": 1750000000,
            "charge": {"id": "ch_1", "amount_rupees": 1299.0, "decline_code": "issuer_decline",
                       "network": {"bank": "HDFC", "rail": "upi_intent", "aggregator": "cashfree"},
                       "buyer_ref": "c_1", "session": "grp_1", "attempt": 2},
        }
        e = c.normalize(payload, "org1", "mer1")
        assert e.type == "payment.failed"
        assert e.amount_paise == 129900  # float rupees → integer paise
        assert e.cohort["issuer"] == "HDFC"


class TestProviderAgnosticCore:
    def test_same_canonical_shape_from_two_dialects(self):
        sim = get_connector("simulator").normalize(
            {"event": "failed", "id": "evt_x1", "created_at": 1750000000,
             "data": {"payment_id": "p", "amount": 100, "issuer": "HDFC",
                      "method": "upi_intent", "psp": "cashfree"}},
            "org1", "mer1")
        mock = get_connector("mockprovider").normalize(
            {"type": "charge.failed", "event_id": "evt_x2", "ts": 1750000000,
             "charge": {"id": "p2", "amount_rupees": 1.0,
                        "network": {"bank": "HDFC", "rail": "upi_intent", "aggregator": "cashfree"}}},
            "org1", "mer1")
        # Core-relevant fields are identical regardless of dialect:
        assert sim.type == mock.type
        assert sim.cohort == mock.cohort
        assert sim.amount_paise == mock.amount_paise
        assert sim.provider != mock.provider  # provenance preserved

    def test_capabilities_differ(self):
        sim = get_connector("simulator").capabilities()
        mock = get_connector("mockprovider").capabilities()
        assert sim.direct_retry and not mock.direct_retry
        assert sim.payment_link and not mock.payment_link
        assert sim.as_dict()["payment_fetch"]

    def test_razorpay_dialect_and_signature(self):
        c = get_connector("razorpay")
        payload = {"event": "payment.failed",
                   "payload": {"payment": {"entity": {
                       "id": "pay_R1", "amount": 500000, "method": "upi", "vpa": "a@b",
                       "bank": "HDFC", "created_at": 1750000000, "order_id": "order_1",
                       "error_description": "Payment declined"}}}}
        raw = json.dumps(payload).encode()
        assert c.verify_webhook(raw, hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(), SECRET)
        e = c.normalize(payload, "org1", "mer1")
        assert e.type == "payment.failed" and e.cohort["method"] == "upi_intent"
        assert e.cohort["psp"] == "razorpay"

    def test_unknown_provider_rejected(self):
        with pytest.raises(WebhookRejected):
            get_connector("stripe")
