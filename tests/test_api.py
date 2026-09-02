"""API-001: httpx ASGI integration — auth, RBAC, tenancy, overview shape, twin
reproducibility over HTTP, execute -> policy path with SSE emission."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from paytwin_api.auth import new_api_key
from paytwin_api.main import app
from paytwin_api.models import (
    ActionCandidate,
    ActionExecution,
    ApiKey,
    Incident,
    Merchant,
    ModelVersion,
    Organization,
    Payment,
)
from paytwin_api.services.audit import append_audit
from paytwin_api.services.bus import bus
from paytwin_api.services import experiments as experiment_service


import asyncio


class ApiClient:
    """Sync facade over httpx.AsyncClient+ASGITransport (this httpx version ships
    ASGITransport as async-only); each request runs on a fresh event loop."""

    def __init__(self):
        self._async = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://test")

    @staticmethod
    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def get(self, path, headers=None):
        return self._run(self._async.get(path, headers=headers))

    def post(self, path, json=None, headers=None):
        return self._run(self._async.post(path, json=json, headers=headers))

    def patch(self, path, json=None, headers=None):
        return self._run(self._async.patch(path, json=json, headers=headers))


@pytest.fixture()
def client():
    yield ApiClient()


@pytest.fixture()
def keys(db):
    out = {}
    for org, role, name in (("org1", "risk_admin", "admin1"),
                            ("org1", "finance_viewer", "fin1"),
                            ("org2", "risk_admin", "admin2")):
        raw, row = new_api_key(org, role, user_id=name)
        db.add(row)
        out[name] = raw
    db.commit()
    return out


def _h(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture()
def seeded(db, keys):
    db.add_all([Organization(id="org1", name="Nova Commerce"),
                Organization(id="org2", name="Other Co")])
    db.add_all([
        Merchant(id="mer1", organization_id="org1", name="Nova Grocery",
                 short_code="NG", autonomy_mode=4,
                 config={"industry": "grocery", "policy_rules": {},
                         "world_id": "mgro"}),
        Merchant(id="m2o2", organization_id="org2", name="Other M",
                 short_code="OM", autonomy_mode=4,
                 config={"policy_rules": {}, "world_id": "mgro"}),
    ])
    db.flush()
    now = datetime.now(timezone.utc)
    for i in range(60):
        db.add(Payment(organization_id="org1", merchant_id="mer1",
                       group_id=f"g{i}", provider="simulator",
                       payment_ref=f"p{i}", amount_paise=84_000,
                       status="success" if i % 10 else "failed",
                       method="upi_intent", issuer="HDFC", psp="cashfree",
                       occurred_at=now))
    inc = Incident(organization_id="org1", merchant_id="mer1",
                   human_id="INC-2481", sev="P1",
                   title="HDFC x upi_intent degradation", state="TRIAGING",
                   cohort_issuer="HDFC", cohort_method="upi_intent",
                   baseline_sr_bp=9700, current_sr_bp=8460,
                   rar_paise=505_853, affected_payments=39)
    db.add(inc)
    db.flush()
    evidence = {"provider_healthy": True, "consent_on_file": True,
                "within_mandate_window": True, "agent_authority_verified": True,
                "contacts_24h": 0, "minutes_since_last_action": 60}
    db.add(ActionCandidate(
        incident_id=inc.id, kind="reroute_psp", label="Reroute Psp", detail="",
        params={"count": 2, "attempts_used": 1, "slice_value_paise": 100_000,
                "evidence": evidence},
        value_paise=400_000, ev_paise=89_475, rank=0))
    db.add(ActionCandidate(
        incident_id=inc.id, kind="retry_burst", label="Retry Burst", detail="",
        params={"count": 9, "attempts_used": 3, "slice_value_paise": 900_000_00,
                "evidence": evidence},
        value_paise=400_000, ev_paise=-5, rank=1))
    db.commit()
    return {"incident": inc.human_id, "cand_ok":
            db.query(ActionCandidate).filter_by(kind="reroute_psp").one().id,
            "cand_bad":
            db.query(ActionCandidate).filter_by(kind="retry_burst").one().id}


class TestAuth:
    def test_health_is_open(self, client):
        assert client.get("/api/health").status_code == 200

    @pytest.mark.parametrize("path", ["/api/meta", "/api/overview",
                                      "/api/incidents"])
    def test_missing_bearer_401(self, client, path):
        r = client.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "missing_bearer"

    def test_bad_key_401(self, client, keys):
        r = client.get("/api/meta", headers=_h("ptw_invalid_key"))
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_key"

    def test_meta_ok(self, client, keys, seeded):
        r = client.get("/api/meta", headers=_h(keys["admin1"]))
        assert r.status_code == 200
        body = r.json()
        assert body["org"] == "org1" and len(body["merchants"]) == 1

    def test_workspace_session_keeps_same_origin_ui_connected_after_reload(self, client, keys, seeded):
        r = client.post("/api/workspace/session", headers=_h(keys["admin1"]))
        assert r.status_code == 200 and r.json()["connected"] is True
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert keys["admin1"].lower() not in cookie

        # Simulates a browser reload: no bearer header survives, but the HttpOnly
        # same-origin session remains and is still subject to RBAC/tenant scope.
        restored = client.get("/api/meta")
        assert restored.status_code == 200
        assert restored.json()["org"] == "org1"


class TestTenancy:
    def test_incidents_scoped_to_tenant(self, client, keys, seeded):
        a = client.get("/api/incidents", headers=_h(keys["admin1"]))
        o = client.get("/api/incidents", headers=_h(keys["admin2"]))
        assert a.status_code == 200 and [i["human_id"]
                                         for i in a.json()] == ["INC-2481"]
        assert o.status_code == 200 and o.json() == []

    def test_cross_tenant_detail_404(self, client, keys, seeded):
        r = client.get("/api/incidents/INC-2481", headers=_h(keys["admin2"]))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_overview_shape_and_values(self, client, keys, seeded):
        r = client.get("/api/overview?scope=mer1", headers=_h(keys["admin1"]))
        assert r.status_code == 200
        body = r.json()
        for key in ("metrics", "pulse", "series", "incidents", "stream_rows",
                    "notifs", "lvl"):
            assert key in body, key
        assert body["metrics"]["active_incidents"] == 1
        assert body["metrics"]["rar_paise"] > 0
        assert len(body["pulse"]) == 16
        assert body["metrics"]["sr_bp"] == 9000  # 60 rows, every 10th fails

    def test_overview_keeps_recovery_money_separate_from_payment_count(
            self, client, keys, seeded, db):
        db.add(ActionExecution(
            organization_id="org1", merchant_id="mer1", kind="reroute_psp",
            idempotency_key="overview-recovery-metrics", state="SUCCEEDED",
            outcome={"recovered": 4, "recovered_paise": 336_000},
        ))
        # This label means eventual success within a payment group. It must not
        # inflate the dashboard's recovery-revenue metric.
        db.query(Payment).filter_by(merchant_id="mer1", payment_ref="p1").update(
            {"recovered": True})
        db.commit()

        body = client.get("/api/overview?scope=mer1", headers=_h(keys["admin1"])).json()
        metrics = body["metrics"]
        assert metrics["recovered_payments"] == 4
        assert metrics["recovered_paise"] == 336_000
        assert metrics["protected_paise"] >= 336_000
        assert metrics["retries_avoided"] == 4  # compatibility field remains a count


class TestExecute:
    def test_finance_viewer_403(self, client, keys, seeded):
        r = client.post(f"/api/incidents/{seeded['incident']}/execute",
                        json={"candidate_id": seeded["cand_ok"]},
                        headers=_h(keys["fin1"]))
        assert r.status_code == 403
        assert db_exec_count() == 0

    def test_blocked_path_records_rejection(self, client, keys, seeded):
        r = client.post(f"/api/incidents/{seeded['incident']}/execute",
                        json={"candidate_id": seeded["cand_bad"]},
                        headers=_h(keys["admin1"]))
        assert r.status_code == 202
        body = r.json()
        assert body["decision"] == "block"
        assert body["state"] == "REJECTED_BY_POLICY"
        assert body["failed_rules"]
        assert db_exec_count() == 1

    def test_allowed_then_duplicate_idempotent(self, client, keys, seeded):
        r = client.post(f"/api/incidents/{seeded['incident']}/execute",
                        json={"candidate_id": seeded["cand_ok"]},
                        headers=_h(keys["admin1"]))
        assert r.status_code == 202
        body = r.json()
        assert body["decision"] == "allow" and body["state"] == "SUCCEEDED"
        r2 = client.post(f"/api/incidents/{seeded['incident']}/execute",
                         json={"candidate_id": seeded["cand_ok"]},
                         headers=_h(keys["admin1"]))
        assert r2.json()["execution_id"] == body["execution_id"]
        assert db_exec_count() == 1
        detail = client.get(f"/api/incidents/{seeded['incident']}",
                            headers=_h(keys["admin1"])).json()
        candidate = next(c for c in detail["candidates"] if c["id"] == seeded["cand_ok"])
        assert candidate["execution"]["state"] == "SUCCEEDED"

    def test_sse_emits_on_action(self, client, keys, seeded):
        q = bus.subscribe("org1")
        try:
            client.post(f"/api/incidents/{seeded['incident']}/execute",
                        json={"candidate_id": seeded["cand_ok"]},
                        headers=_h(keys["admin1"]))
            topics = []
            while not q.empty():
                topics.append(q.get_nowait().topic)
            assert "policy_decision" in topics and "action" in topics
        finally:
            bus.unsubscribe("org1", q)

    def test_resolve_lifecycle(self, client, keys, seeded):
        r = client.post(f"/api/incidents/{seeded['incident']}/resolve",
                        headers=_h(keys["admin1"]))
        assert r.status_code == 200 and r.json()["state"] == "RESOLVED"
        listed = client.get("/api/incidents?state=RESOLVED",
                            headers=_h(keys["admin1"])).json()
        assert [i["human_id"] for i in listed] == ["INC-2481"]


class TestTwin:
    def test_same_seed_byte_identical_over_http(self, client, keys, seeded):
        body = {"scope": "mer1", "scenario": "retry_burst", "alloc_pct": 25,
                "duration_min": 30, "seed": 7}
        h = _h(keys["admin1"])
        a = client.post("/api/twin/simulate", json=body, headers=h)
        b = client.post("/api/twin/simulate", json=body, headers=h)
        assert a.status_code == b.status_code == 200
        assert a.text == b.text  # byte-identical for the same seed
        j = a.json()
        for key in ("p50_paise", "lo_paise", "hi_paise", "lift_pct", "traj",
                    "trials", "seed"):
            assert key in j

    def test_unknown_merchant_404(self, client, keys):
        r = client.post("/api/twin/simulate",
                        json={"scope": "nope"}, headers=_h(keys["admin1"]))
        assert r.status_code == 404


def db_exec_count() -> int:
    from paytwin_api.main import SessionLocal

    s = SessionLocal()
    try:
        return s.query(ActionExecution).count()
    finally:
        s.close()


class TestPoliciesRbac:
    def _create(self, client, key):
        return client.post("/api/policies", json={
            "merchant_id": "mer1", "name": "Tighter caps",
            "rules": {"amount_cap": 100_000}}, headers=_h(key))

    def test_viewer_cannot_create_or_edit(self, client, keys, seeded):
        assert self._create(client, keys["fin1"]).status_code == 403
        pol = client.get("/api/policies", headers=_h(keys["admin1"])).json()
        if pol:
            r = client.patch(f"/api/policies/{pol[0]['human_id']}",
                             json={"status": "archived"},
                             headers=_h(keys["fin1"]))
            assert r.status_code in (403, 404)

    def test_admin_creates_and_patches_new_version(self, client, keys, seeded):
        r = self._create(client, keys["admin1"])
        assert r.status_code == 200
        human = r.json()["human_id"]
        p2 = client.patch(f"/api/policies/{human}", json={"rules": {}},
                          headers=_h(keys["admin1"]))
        assert p2.status_code == 200 and p2.json()["version"] == 2
        lst = client.get("/api/policies", headers=_h(keys["admin1"])).json()
        mine = [p for p in lst if p["human_id"] == human]
        assert len(mine) == 1 and mine[0]["version"] == 2

    def test_unknown_rule_422(self, client, keys, seeded):
        r = client.post("/api/policies", json={
            "merchant_id": "mer1", "name": "x",
            "rules": {"not_a_rule": 1}}, headers=_h(keys["admin1"]))
        assert r.status_code == 422


class TestModelsCommanderAuditReportsChaos:
    def test_promote_rbac(self, client, keys, seeded, db):
        m = ModelVersion(name="success_prob", version="fv2-test-1",
                         stage="TRAINED", kind="HistGB+Isotonic")
        db.add(m)
        db.commit()
        fin = client.post(f"/api/models/{m.id}/promote",
                          json={"stage": "CHAMPION"}, headers=_h(keys["fin1"]))
        assert fin.status_code == 403
        # CHAMPION promotion is a PLATFORM operation (shared registry):
        # even a tenant risk_admin may not flip the global champion.
        risk = client.post(f"/api/models/{m.id}/promote",
                           json={"stage": "CHAMPION"}, headers=_h(keys["admin1"]))
        assert risk.status_code == 403
        from paytwin_api.auth import new_api_key

        raw, row = new_api_key("org1", "org_admin", user_id="plat")
        db.add(row); db.commit()
        adm = client.post(f"/api/models/{m.id}/promote",
                          json={"stage": "CHAMPION"}, headers=_h(raw))
        assert adm.status_code == 200 and adm.json()["stage"] == "CHAMPION"

    def test_commander_chat_grounding_over_http(self, client, keys, seeded):
        r = client.post("/api/commander/chat",
                        json={"message": "status of INC-2481?"},
                        headers=_h(keys["admin1"]))
        assert r.status_code == 200
        body = r.json()
        assert "[E" in body["reply_md"]
        assert set(body["citations"]) <= {e["id"] for e in body["evidence"]}
        assert all(t["name"] for t in body["tools"])
        assert body["mode"] == "fallback"

    def test_audit_verify_and_export(self, client, keys, seeded, db):
        append_audit(db, "org1", actor="t", actor_role="system",
                     action_type="action.executed", object_type="x",
                     object_id="y", summary="s")
        db.commit()
        v = client.get("/api/audit/verify", headers=_h(keys["admin1"])).json()
        assert v["ok"] is True and v["first_bad_seq"] is None
        exp = client.get("/api/audit/export?fmt=jsonl",
                         headers=_h(keys["admin1"]))
        assert exp.status_code == 200
        first_line = exp.text.strip().splitlines()[0]
        assert __import__("json").loads(first_line)["organization_id"] == "org1"

    def test_reports_batch_markdown(self, client, keys, seeded, db):
        experiment = experiment_service.create_experiment(
            db, "org1", "mer1", "canonical recovery", incident_id=None)
        action = ActionExecution(organization_id="org1", merchant_id="mer1",
                                 human_id="ACT-REPORT", kind="payment_link",
                                 idempotency_key="report-action", state="SUCCEEDED",
                                 outcome={"gross_action_cost_paise": 1_200,
                                          "stopping_events": [{"reason": "bounded_complete"}]})
        db.add(action)
        db.flush()
        for i in range(80):
            assignment = experiment_service.record_assignment(
                db, experiment, f"report_group_{i}", action_execution_id=action.id)
            recovered = (i % 4 != 0) if assignment.arm == "treatment" else (i % 5 == 0)
            experiment_service.record_outcome(db, assignment, recovered, 20_000)
        db.commit()
        r = client.get("/api/reports/recovery-batch?hours=24",
                       headers=_h(keys["admin1"]))
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert "Recovery batch report" in r.text
        assert "net incremental GMV" in r.text
        assert "intervention cost" in r.text
        assert "audit references: ACT-REPORT" in r.text

    def test_chaos_inject_ingests_webhooks(self, client, keys, seeded):
        r = client.post("/api/chaos/issuer_outage",
                        json={"scope": "mer1", "duration_min": 3},
                        headers=_h(keys["admin1"]))
        assert r.status_code == 200
        assert r.json()["events_ingested"] > 0

    def test_chaos_preview_and_compound_surge_are_explicitly_sandboxed(self, client, keys, seeded):
        h = _h(keys["admin1"])
        preview = client.post("/api/chaos/preview/surge_bank_failure",
                              json={"scope": "mer1", "duration_min": 10, "seed": 77},
                              headers=h)
        assert preview.status_code == 200
        body = preview.json()
        assert body["mode"] == "SANDBOX_FORECAST"
        assert body["forecast"]["traffic_multiplier"] == 4.0
        assert body["forecast"]["projected_failure_rate"] > body["forecast"]["baseline_failure_rate"]
        assert len(body["recommended_actions"]) == 4
        assert "Local workspace preflight" in body["risk_model"]["limitation"]

        injected = client.post("/api/chaos/surge_bank_failure",
                               json={"scope": "mer1", "duration_min": 1, "seed": 77},
                               headers=h)
        assert injected.status_code == 200
        result = injected.json()
        assert result["mode"] == "SANDBOX_INJECTION"
        assert result["events_ingested"] > 0
        assert result["ground_truth"]["top_cause"]["kind"] == "surge_bank_failure"

    def test_chaos_requires_write(self, client, keys, seeded):
        r = client.post("/api/chaos/issuer_outage",
                        json={"scope": "mer1"}, headers=_h(keys["fin1"]))
        assert r.status_code == 403
