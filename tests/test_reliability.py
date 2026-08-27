"""Reliability Lab: invariant engine, fixture mutations, deterministic runner,
API surface (suites/run/findings/release-gate), tenant isolation."""
from __future__ import annotations

import pytest
import httpx

from paytwin_api.main import app
from paytwin_api.models import Merchant, Organization
from paytwin_api.reliability import packs, store
from paytwin_api.reliability.engine import run_scenario
from paytwin_api.reliability.fixtures import FixturePolicy, PRESETS


# ------------------------------------------------------------- engine core
def test_correct_fixture_is_clean_on_every_base_scenario():
    for suite in packs.all_suites():
        for sc in suite["scenarios"]:
            res = run_scenario(sc, PRESETS["correct"]())
            assert not res["violations"], (sc["id"], res)


def test_every_mutation_is_detected():
    found = 0
    for suite in packs.all_suites():
        for sc in suite["scenarios"]:
            for mut in sc.get("mutations", []):
                res = run_scenario(sc, PRESETS[mut["preset"]]())
                assert set(res["violations"]) == set(mut["expect"]), \
                    (sc["id"], mut["name"], res)
                found += 1
    assert found >= 6  # test-the-tester coverage floor


def test_runner_deterministic():
    sc = packs.GENERIC_WEBHOOKS["scenarios"][0]
    assert run_scenario(sc, PRESETS["correct"]()) == \
        run_scenario(sc, PRESETS["correct"]())


def test_late_auth_broken_fixture_violates_capture_gating():
    sc = next(s for s in packs.RAZORPAY_CORE["scenarios"]
              if s["id"] == "RZP-LATE-AUTH")
    res = run_scenario(sc, PRESETS["fulfil_on_authorized"]())
    assert "PTWIN-INV-001" in res["violations"]


def test_multiple_captured_attempts_cannot_fulfil_one_order_twice():
    sc = next(s for s in packs.RAZORPAY_CORE["scenarios"]
              if s["id"] == "RZP-ONE-FULFILMENT")
    assert not run_scenario(sc, PRESETS["correct"]())["violations"]
    broken = run_scenario(sc, PRESETS["duplicate_fulfilment"]())
    assert set(broken["violations"]) == {"PTWIN-INV-008"}


def test_unsigned_webhook_zero_effects_when_verified():
    sc = next(s for s in packs.RAZORPAY_CORE["scenarios"]
              if s["id"] == "RZP-WH-FORGED")
    good = run_scenario(sc, PRESETS["correct"]())
    assert not good["violations"] and good["evidence"]["effects"] == 0


# ------------------------------------------------------------- API surface
class ApiClient:
    """Sync facade over httpx.AsyncClient+ASGITransport (async-only transport)."""
    def __init__(self):
        self._a = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://t")

    @staticmethod
    def _run(coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def get(self, path, headers=None, **kw):
        return self._run(self._a.get(path, headers=headers, **kw))

    def post(self, path, json=None, headers=None, **kw):
        return self._run(self._a.post(path, json=json, headers=headers, **kw))

    def close(self):
        if not self._a.is_closed:
            self._run(self._a.aclose())


@pytest.fixture()
def api(monkeypatch):
    import os
    from paytwin_api.auth import new_api_key
    from paytwin_api.db import Base, make_engine
    from sqlalchemy.orm import sessionmaker
    import paytwin_api.models  # noqa: F401

    eng = make_engine(os.environ["PAYTWIN_DATABASE_URL"])
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add_all([Organization(id="org1", name="Nova"),
               Organization(id="org2", name="Other")])
    raw_a, row_a = new_api_key("org1", "risk_admin", user_id="rel-a")
    raw_b, row_b = new_api_key("org2", "risk_admin", user_id="rel-b")
    s.add_all([row_a, row_b]); s.commit(); s.close(); eng.dispose()

    captured: dict = {}
    monkeypatch.setattr(store, "save_run",
                        lambda run: (captured.update({run["run_id"]: run}),
                                     run)[1])
    monkeypatch.setattr(store, "load_runs", lambda: list(captured.values()))
    monkeypatch.setattr(store, "get_run", lambda rid: captured.get(rid))
    monkeypatch.setattr(store, "latest",
                        lambda: next(iter(captured.values()), None))

    client = ApiClient()
    yield client, {"A": f"Bearer {raw_a}", "B": f"Bearer {raw_b}"}, captured
    client.close()


def test_run_overview_gate_and_tenant_isolation(api):
    client, toks, _ = api
    r = client.post("/api/reliability/run",
                    headers={"Authorization": toks["A"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gate"]["verdict"] == "READY", body["findings"]
    assert len(body["per_suite"]) == 4

    ov = client.get("/api/reliability/overview",
                    headers={"Authorization": toks["A"]}).json()
    assert ov["suites"] == 4 and ov["requirements_traced"] >= 8
    assert ov["gate"]["verdict"] == "READY"

    f_b = client.get("/api/reliability/findings",
                     headers={"Authorization": toks["B"]}).json()
    g_b = client.get("/api/reliability/release-gate",
                     headers={"Authorization": toks["B"]}).json()
    runs_b = client.get("/api/reliability/runs",
                        headers={"Authorization": toks["B"]}).json()
    assert f_b["count"] == 0
    assert g_b["basis"] == "no runs yet"
    assert runs_b["runs"] == []


def test_critical_finding_blocks_release_gate(api):
    client, toks, captured = api
    sc = packs.GENERIC_WEBHOOKS["scenarios"][0]
    res = run_scenario(sc, PRESETS["no_dedupe"]())
    assert res["violations"], "broken fixture must be detected"
    store.save_run({
        "run_id": "REL-forced", "at": "t", "org_id": "org1", "mode": "test",
        "seed": 1, "per_suite": [], "checks": [],
        "findings": [{"finding_id": "F-FORCED", "scenario": sc["id"],
                      "title": "duplicate effects", "severity": "critical",
                      "fixture": "no_dedupe", "source": "PAYTWIN_INVARIANT",
                      "requirement_ids": sc.get("req_ids", []),
                      "evidence": res["violations"],
                      "suite": "generic/webhooks", "org_id": "org1"}],
        "gate": {"verdict": "BLOCKED", "score": 75, "critical": 1,
                 "high": 0, "medium": 0}})
    g = client.get("/api/reliability/release-gate",
                   headers={"Authorization": toks["A"]}).json()
    assert g["verdict"] == "BLOCKED" and g["critical"] >= 1


def test_webhook_lab_fault_injections(api):
    client, toks, _ = api
    h = {"Authorization": toks["A"]}
    for fault in ("duplicate", "bad_signature", "timeout_redelivery",
                  "out_of_order"):
        r = client.post(f"/api/reliability/webhook-lab/{fault}", headers=h)
        assert r.status_code == 200, (fault, r.text)
        if fault != "bad_signature":
            assert r.json()["invariant_violations"] == {}
    assert client.post("/api/reliability/webhook-lab/nope",
                       headers=h).status_code == 404


def test_unknown_suite_404(api):
    client, toks, _ = api
    r = client.post("/api/reliability/run", json={"packs": ["nope/x"]},
                    headers={"Authorization": toks["A"]})
    assert r.status_code == 404


def test_requirement_registry_exposes_source_traceability(api):
    client, toks, _ = api
    r = client.get("/api/reliability/requirements", headers={"Authorization": toks["A"]})
    assert r.status_code == 200
    registry = {item["id"]: item for item in r.json()["registry"]}
    assert registry["RZPREQ-WEBHOOK-006"]["source"] == "RAZORPAY_DOCUMENTATION"
    assert registry["RZPREQ-WEBHOOK-006"]["source_url"].startswith("https://razorpay.com/")
    assert registry["PTWIN-INV-008"]["source"] == "PAYTWIN_INVARIANT"


def test_razorpay_runtime_suite_uses_the_real_ingestion_path(api):
    """The judge-facing runtime pack is tenant-scoped and explicitly sandboxed."""
    import os
    from paytwin_api.db import make_engine
    from sqlalchemy.orm import sessionmaker

    client, toks, _ = api
    db = sessionmaker(bind=make_engine(os.environ["PAYTWIN_DATABASE_URL"]))()
    try:
        db.add(Merchant(id="mer_rzp", organization_id="org1", name="Razorpay Demo",
                        short_code="RZ", config={"connector": "simulator"}))
        db.commit()
    finally:
        db.close()
    r = client.post("/api/reliability/run",
                    json={"merchant_id": "mer_rzp", "packs": ["razorpay/runtime"]},
                    headers={"Authorization": toks["A"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "SANDBOX_RUNTIME"
    assert body["gate"]["verdict"] == "READY"
    assert body["per_suite"] == [{"suite_id": "razorpay/runtime", "passed": True,
                                   "checks": 6, "findings": 0,
                                   "mode": "SANDBOX_RUNTIME"}]
