"""Release-blocker regression tests: safety gates, tenant isolation, pipeline
correctness, policy enforcement, audit/outbox semantics, rate limiting, DLQ."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest

from paytwin_api.auth import new_api_key
from paytwin_api.config import get_settings
from paytwin_api.models import (AuditHead, AuditRecord, DeadLetter, EventInbox,
                                Integration, Merchant, Organization, Payment, Policy)
from paytwin_api.services import audit as audit_svc
from paytwin_api.services import executor
from paytwin_api.services.bus import bus, publish_outbox
from paytwin_api.services.ingest import ingest_webhook
from paytwin_api.services.state_machine import apply_event
from paytwin_contracts import CanonicalEvent


def _mk_org_merchant(db, org="org1", merch="mer1", config=None):
    if db.query(Organization).filter_by(id=org).one_or_none() is None:
        db.add(Organization(id=org, name=f"Org {org}"))
    m = Merchant(id=merch, organization_id=org, name=f"M {merch}",
                 short_code=merch[:2].upper(),
                 config=config or {"connector": "simulator"})
    db.add(m)
    db.commit()
    return m


def _sim_payload(ext_id, etype, ref, epoch_h=10, **data):
    base = {"id": ext_id, "event": etype, "created_at":
            int(datetime(2026, 8, 25, epoch_h, tzinfo=timezone.utc).timestamp()),
            "data": {"payment_id": ref, "amount": 150000, **data}}
    return json.dumps(base).encode()


def _sig(db, body):
    import hashlib
    import hmac

    secret = get_settings().webhook_secret_simulator
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ------------------------------------------------- chaos + execution gates
class TestSafetyGates:
    def test_chaos_forbidden_for_ops_oncall(self, db):
        from paytwin_api.auth import Principal
        from paytwin_api.routers.chaos import inject

        _mk_org_merchant(db, merch="mgro", config={"world_id": "mgro"})
        p = Principal(organization_id="org1", role="ops_oncall", key_prefix="ptw_x")
        res = inject("psp_degradation", type("B", (), {"scope": "mgro",
                                                     "duration_min": 5})(), p, db)
        assert res.status_code == 403

    def test_chaos_disabled_in_production(self, db, monkeypatch):
        from paytwin_api.auth import Principal
        from paytwin_api.routers.chaos import inject
        from paytwin_api.config import Settings

        monkeypatch.setattr(Settings, "is_prod",
                            property(lambda self: True), raising=False)
        _mk_org_merchant(db, merch="mgro", config={"world_id": "mgro"})
        p = Principal(organization_id="org1", role="org_admin", key_prefix="ptw_x")
        res = inject("psp_degradation", type("B", (), {"scope": "mgro",
                                                     "duration_min": 5})(), p, db)
        assert res.status_code == 403

    def test_real_psp_execution_refused_by_default(self, db):
        m = _mk_org_merchant(db, config={"connector": "mockprovider"})
        m.autonomy_mode = 4  # AUTONOMOUS so the flow actually reaches dispatch
        db.commit()
        cand = type("C", (), {"id": "c1", "kind": "retry_burst",
                              "params": {"count": 5, "cooldown_ok_ok": 1,
                                         "evidence": {"provider_healthy": True,
                                                      "consent_on_file": True,
                                                      "within_mandate_window": True,
                                                      "agent_authority_verified": True,
                                                      "contacts_24h": 0,
                                                      "minutes_since_last_action": 60}},
                              "value_paise": 100,
                              "incident_id": None})()
        ex, _ = executor.request_execution(db, None, m, cand)
        db.commit()
        assert ex.state == "FAILED_FINAL"
        assert "disabled" in ex.outcome["error"]

    def test_production_config_rejects_dev_secrets(self):
        from paytwin_api.config import Settings

        bad = Settings(env="production", database_url="sqlite:///./x.db",
                       secret_key="dev-secret-change-me",
                       webhook_secret_simulator="sim-secret-dev",
                       webhook_secret_mockprovider="mock-secret-dev",
                       webhook_secret_razorpay="rzp-secret-dev",
                       hash_salt="dev-hash-salt")
        with pytest.raises(RuntimeError, match="production configuration"):
            bad.validate_for_env()


# ------------------------------------------------- tenant isolation
class TestTenantIsolation:
    def test_cross_tenant_event_cannot_touch_org1_payment(self, db):
        _mk_org_merchant(db, org="org1", merch="mer1")
        _mk_org_merchant(db, org="org2", merch="mer2")
        body = _sim_payload("evt_x1", "success", "pay_shared")
        r1 = ingest_webhook(db, "simulator", "mer1", body, _sig(db, body))
        assert r1.status == 200 and r1.body["payment_status"] == "success"
        # org-2 delivers an event with the SAME provider reference
        body2 = _sim_payload("evt_x2", "failed", "pay_shared", epoch_h=10,
                             error_reason="issuer_decline")
        # shift occurred_at 5 minutes later so it is not "late"
        obj = json.loads(body2)
        obj["created_at"] += 300
        body2 = json.dumps(obj).encode()
        r2 = ingest_webhook(db, "simulator", "mer2", body2, _sig(db, body2))
        assert r2.status == 200
        rows = db.query(Payment).filter(Payment.payment_ref == "pay_shared").all()
        assert len(rows) == 2  # two tenant-scoped payments, never one shared row
        by_org = {r.organization_id: r for r in rows}
        assert by_org["org1"].status == "success"  # org-2 event did NOT regress it
        assert by_org["org2"].status == "failed"

    def test_inbox_dedupe_is_per_tenant(self, db):
        _mk_org_merchant(db, org="org1", merch="mer1")
        _mk_org_merchant(db, org="org2", merch="mer2")
        body = _sim_payload("evt_dup9", "created", "pay_d9")
        r1 = ingest_webhook(db, "simulator", "mer1", body, _sig(db, body))
        r2 = ingest_webhook(db, "simulator", "mer2", body, _sig(db, body))
        assert r1.status == 200 and r1.body.get("duplicate") is None
        # same external id under ANOTHER org is a distinct delivery, not a dupe
        assert r2.status == 200 and r2.body.get("duplicate") is None


# ------------------------------------------------- pipeline correctness
class TestPipelineCorrectness:
    def test_late_created_cannot_regress_authorized(self, db):
        _mk_org_merchant(db)
        e_auth = CanonicalEvent(
            type="payment.authorized", organization_id="org1", merchant_id="mer1",
            provider="simulator", external_event_id="evt_a1",
            occurred_at=datetime(2026, 8, 25, 10, 1, tzinfo=timezone.utc),
            payment_ref="pay_r1", amount_paise=100)
        p = apply_event(db, e_auth)
        assert p.status == "authorized"
        e_late = CanonicalEvent(
            type="payment.created", organization_id="org1", merchant_id="mer1",
            provider="simulator", external_event_id="evt_c0",
            occurred_at=datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
            payment_ref="pay_r1", amount_paise=100)
        p2 = apply_event(db, e_late)
        assert p2.status == "authorized"  # forward-only by state rank

    def test_failed_authorized_success_is_an_allowed_lifecycle(self, db):
        """A late authorization may legitimately recover an earlier failure."""
        _mk_org_merchant(db)
        t0 = datetime(2026, 8, 25, 10, tzinfo=timezone.utc)
        events = (
            ("payment.failed", "evt_fail", t0, "failed"),
            ("payment.authorized", "evt_auth", t0.replace(minute=1), "authorized"),
            ("payment.success", "evt_succ", t0.replace(minute=2), "success"),
        )
        for event_type, event_id, occurred_at, expected in events:
            payment = apply_event(db, CanonicalEvent(
                type=event_type, organization_id="org1", merchant_id="mer1",
                provider="simulator", external_event_id=event_id,
                occurred_at=occurred_at, payment_ref="pay_late_auth", amount_paise=100))
            assert payment.status == expected
        assert payment.final_status_at == t0.replace(minute=2)

    def test_success_and_refund_cannot_be_overwritten(self, db):
        _mk_org_merchant(db)
        t0 = datetime(2026, 8, 25, 10, tzinfo=timezone.utc)

        def apply(event_type: str, event_id: str, minute: int):
            return apply_event(db, CanonicalEvent(
                type=event_type, organization_id="org1", merchant_id="mer1",
                provider="simulator", external_event_id=event_id,
                occurred_at=t0.replace(minute=minute), payment_ref="pay_final",
                amount_paise=100))

        assert apply("payment.success", "evt_success", 0).status == "success"
        assert apply("payment.failed", "evt_after_success_fail", 1).status == "success"
        assert apply("payment.authorized", "evt_after_success_auth", 2).status == "success"
        # Refund is the one valid forward transition from success.
        assert apply("refund.created", "evt_refund", 3).status == "refunded"
        assert apply("payment.success", "evt_after_refund", 4).status == "refunded"

    def test_razorpay_lifecycle_events_are_distinct(self, db):
        _mk_org_merchant(db)
        from paytwin_api.connectors import get_connector

        conn = get_connector("razorpay")
        ent = {"id": "pay_RZ1", "amount": 200000, "method": "upi",
               "bank": "HDFC", "order_id": "order_1"}
        auth = {"event": "payment.authorized",
                "payload": {"payment": {"entity": dict(ent, created_at=1756100000)}}}
        cap = {"event": "payment.captured",
               "payload": {"payment": {"entity": dict(ent, created_at=1756100060)}}}
        ev1 = conn.normalize(auth, "org1", "mer1",
                             headers={"x-razorpay-event-id": "evt-hdr-1"})
        ev2 = conn.normalize(cap, "org1", "mer1",
                             headers={"x-razorpay-event-id": "evt-hdr-2"})
        assert ev1.external_event_id == "evt-hdr-1"
        assert ev2.external_event_id == "evt-hdr-2"  # distinct → capture not dropped
        # no header → composite fallback still distinct per lifecycle stage
        f1 = conn.normalize(auth, "org1", "mer1")
        f2 = conn.normalize(cap, "org1", "mer1")
        assert f1.external_event_id != f2.external_event_id
        # both lifecycle events apply to the same payment
        p = apply_event(db, ev1)
        assert p.status == "authorized"
        p = apply_event(db, ev2)
        assert p.status == "success"  # capture landed instead of being deduped

    def test_dlq_payload_is_redacted(self, db):
        _mk_org_merchant(db)
        bad = json.dumps({"id": "evt_bad", "data": {
            "customer_ref": "cust_PII_99", "vpa": "person@upi",
            "amount": "not-an-int"}}).encode()
        r = ingest_webhook(db, "simulator", "mer1", bad, _sig(db, bad))
        assert r.status == 422
        dl = db.query(DeadLetter).filter_by(reason="malformed").one()
        blob = json.dumps(dl.payload)
        assert "cust_PII_99" not in blob and "person@upi" not in blob
        assert "[redacted]" in blob

    def test_customer_ref_pseudonymized_in_ledger(self, db):
        _mk_org_merchant(db)
        body = _sim_payload("evt_pii1", "created", "pay_pii",
                            customer_ref="cust_RAW_77")
        r = ingest_webhook(db, "simulator", "mer1", body, _sig(db, body))
        assert r.status == 200
        p = db.query(Payment).filter_by(payment_ref="pay_pii").one()
        assert p.customer_ref and p.customer_ref.startswith("c_")
        assert "cust_RAW_77" not in (p.customer_ref or "")

    def test_successful_inbox_payload_is_redacted(self, db):
        _mk_org_merchant(db)
        body = _sim_payload("evt_inbox_pii", "created", "pay_inbox_pii",
                            customer_ref="cust_RAW_88", vpa="person@upi",
                            pan="4111111111111111", cvv="123")
        r = ingest_webhook(db, "simulator", "mer1", body, _sig(db, body))
        assert r.status == 200
        inbox = db.query(EventInbox).filter_by(external_event_id="evt_inbox_pii").one()
        blob = json.dumps(inbox.payload)
        for raw in ("cust_RAW_88", "person@upi", "4111111111111111", '"123"'):
            assert raw not in blob
        assert "[redacted]" in blob

    def test_unknown_provider_is_typed_404_not_an_exception(self, db):
        _mk_org_merchant(db)
        r = ingest_webhook(db, "not_a_provider", "mer1", b"{}", "")
        assert r.status == 404
        assert r.body["error"]["code"] == "unknown_provider"
        assert db.query(DeadLetter).filter_by(reason="unknown_provider").count() == 1

    def test_inbound_integration_secret_ref_is_preferred(self, db, monkeypatch):
        merchant = _mk_org_merchant(db)
        secret_name = "PAYTWIN_TEST_RAZORPAY_WEBHOOK_SECRET"
        secret = "merchant-specific-test-secret"
        monkeypatch.setenv(secret_name, secret)
        db.add(Integration(organization_id="org1", merchant_id=merchant.id,
                           provider="razorpay", secret_ref=secret_name))
        db.commit()
        body = json.dumps({
            "event": "payment.authorized",
            "payload": {"payment": {"entity": {
                "id": "pay_rzp_secret", "amount": 12_900, "method": "upi",
                "created_at": 1_772_000_000,
            }}},
        }).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        r = ingest_webhook(db, "razorpay", merchant.id, body, signature)
        assert r.status == 200
        assert r.body["payment_status"] == "authorized"


# ------------------------------------------------- policy enforcement
class TestPolicyEnforcement:
    def test_live_policy_blocks_execution(self, db):
        from paytwin_api.models import PolicyDecision

        m = _mk_org_merchant(db, config={"connector": "simulator",
                                         "policy_rules": {}})
        db.add(Policy(organization_id="org1", merchant_id=m.id, human_id="RP-900",
                      name="Tight cap", version=1, status="live",
                      rules={"amount_cap": 1000}, created_by="test"))
        db.commit()
        cand = type("C", (), {"id": "c9", "kind": "retry_burst",
                              "params": {"slice_value_paise": 500000},
                              "value_paise": 500000, "incident_id": None})()
        ex, res = executor.request_execution(db, None, m, cand)
        db.commit()
        assert ex.state == "REJECTED_BY_POLICY"
        assert any("amount_cap" in r for r in res.failed_rules)
        # the decision records WHICH policy version enforced it
        dec = (db.query(PolicyDecision)
               .filter(PolicyDecision.action_execution_id == ex.id).one())
        assert "RP-900:v1" in (dec.policy_version or "")

    def test_rule_validation_rejects_bad_types(self, db):
        from paytwin_api.services.policy import validate_rules

        assert validate_rules({"amount_cap": "lots"}) is not None
        assert validate_rules({"max_attempts": 0}) is not None
        assert validate_rules({"consent_on_file": "yes"}) is not None
        assert validate_rules({"dnd_window_ok": {"start_hour": 25, "end_hour": 8}}) is not None
        assert validate_rules({"max_attempts": 3, "cooldown_ok": 30}) is None


# ------------------------------------------------- audit + outbox semantics
class TestAuditAndOutbox:
    def test_deleting_latest_record_breaks_verification(self, db):
        _mk_org_merchant(db)
        for i in range(3):
            audit_svc.append_audit(db, "org1", actor="t", actor_role="system",
                                   action_type=f"t{i}", object_type="x",
                                   object_id=str(i), summary=f"s{i}")
        db.commit()
        ok, _ = audit_svc.verify_chain(db, "org1")
        assert ok
        last = (db.query(AuditRecord)
                .filter(AuditRecord.organization_id == "org1")
                .order_by(AuditRecord.seq.desc()).first())
        db.delete(last)
        db.commit()
        ok, bad = audit_svc.verify_chain(db, "org1")
        assert not ok  # tail deletion is caught via the checkpoint
        head = db.query(AuditHead).filter_by(organization_id="org1").one()
        assert head.record_count == 3

    def test_sse_events_only_after_commit(self, db):
        _mk_org_merchant(db)
        q = bus.subscribe("org1")
        try:
            publish_outbox(db, "org1", "metric", {"n": 1})
            assert q.empty()  # nothing published before commit
            db.commit()
            assert not q.empty() and q.get_nowait().topic == "metric"
            # rollback drops pending events
            publish_outbox(db, "org1", "metric", {"n": 2})
            db.rollback()
            assert q.empty()
        finally:
            bus.unsubscribe("org1", q)

    def test_commander_chat_persists_audit(self, db):
        import httpx

        from paytwin_api.main import app

        _mk_org_merchant(db)
        raw, row = new_api_key("org1", "risk_admin")
        db.add(row); db.commit()

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://t") as ac:
                r = await ac.post("/api/commander/chat",
                                  json={"message": "why did ACT-1 happen"},
                                  headers={"Authorization": f"Bearer {raw}"})
                assert r.status_code == 200

        asyncio.new_event_loop().run_until_complete(_run())
        db.expire_all()
        n = db.query(AuditRecord).filter(
            AuditRecord.organization_id == "org1",
            AuditRecord.actor == "commander").count()
        assert n >= 1  # committed and visible outside the request session


# ------------------------------------------------- rate limiting
class TestRateLimiting:
    @staticmethod
    def _dummy_ok(status=200):
        async def dummy(scope, receive, send):
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})
        return dummy

    @staticmethod
    async def _drive(mw, path, ident="10.0.0.1"):
        sent = []
        scope = {"type": "http", "path": path,
                 "headers": [], "client": (ident, 1)}

        async def send(msg):
            sent.append(msg)

        await mw(scope, None, send)
        return sent[0]["status"]

    def test_rate_limit_middleware_429s(self):
        from paytwin_api.main import RateLimitMiddleware

        mw = RateLimitMiddleware(self._dummy_ok(), limit=2)
        loop = asyncio.new_event_loop()
        statuses = [loop.run_until_complete(self._drive(mw, "/api/overview"))
                    for _ in range(3)]
        loop.close()
        assert statuses == [200, 200, 429]

    def test_webhooks_and_health_exempt(self):
        from paytwin_api.main import RateLimitMiddleware

        mw = RateLimitMiddleware(self._dummy_ok(), limit=1)
        loop = asyncio.new_event_loop()
        assert loop.run_until_complete(self._drive(mw, "/webhooks/simulator", "9")) == 200
        assert loop.run_until_complete(self._drive(mw, "/webhooks/simulator", "9")) == 200
        assert loop.run_until_complete(self._drive(mw, "/api/health", "9")) == 200
        loop.close()


class TestWorkerAndPolicyPreview:
    def test_worker_sweeps_every_organization(self, db, monkeypatch):
        from paytwin_api.services import incident_service
        from paytwin_api.worker import run_once

        db.add_all([Organization(id="org1", name="Org 1"),
                    Organization(id="org2", name="Org 2")])
        db.commit()
        seen: list[str] = []
        monkeypatch.setattr(incident_service, "run_detection_cycle",
                            lambda _db, org_id: seen.append(org_id) or [])

        result = run_once(db)
        assert seen == ["org1", "org2"]
        assert result["organizations"] == 2
        assert result["opened"] == 0 and result["executed"] == []

    def test_policy_preview_merges_draft_rules(self, db):
        from paytwin_api.auth import Principal
        from paytwin_api.routers.policies import PreviewBody, preview

        _mk_org_merchant(db)
        result = preview(
            PreviewBody(merchant_id="mer1", draft_rules={"amount_cap": 100_000}),
            Principal(organization_id="org1", role="risk_admin", key_prefix="ptw_test"),
            db,
        )
        assert result == {"replayed": 0, "would_block": 0,
                          "verdict_changes": 0, "unchanged": 0}
