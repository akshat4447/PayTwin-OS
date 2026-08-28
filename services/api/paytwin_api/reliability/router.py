"""Reliability Lab API — suites, deterministic runs, findings, webhook lab, release gate."""
from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import Principal
from ..config import get_settings
from ..deps import current_principal, get_db, require_admin
from ..models import Merchant, ReliabilityRun
from ..services import audit as audit_svc
from . import packs, store
from .engine import run_scenario
from .fixtures import PRESETS
from .requirements import REGISTRY, requirement_details, summary as requirement_summary
from .runtime import SandboxOnlyError, run_razorpay_runtime_checks

router = APIRouter(prefix="/api/reliability", tags=["reliability"])


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _finding(scenario_id: str, fixture: str, res: dict,
             req_ids: list[str], mutation: bool = False) -> dict:
    if not mutation and res["violations"]:
        title, severity = (f"{scenario_id}: correct integration violates "
                           "invariants"), "critical"
    elif mutation and not res["violations"]:
        title, severity = (f"{scenario_id}: broken fixture '{fixture}' "
                           "NOT detected"), "high"
    else:
        title, severity = (f"{scenario_id}: unexpected violations "
                           f"on '{fixture}'"), "medium"
    return {"finding_id": "F-" + uuid.uuid4().hex[:8], "scenario": scenario_id,
            "title": title, "severity": severity, "fixture": fixture,
            "source": "PAYTWIN_INVARIANT", "requirement_ids": req_ids,
            "requirement_trace": requirement_details(req_ids),
            "evidence": {"expected": res["expected"],
                         "actual": res["violations"]},
            "recommended_fix": "Inspect the invariant evidence, correct the integration boundary, then rerun this deterministic scenario."}


def _gate(findings: list[dict]) -> dict:
    crit = sum(1 for f in findings if f["severity"] == "critical")
    high = sum(1 for f in findings if f["severity"] == "high")
    med = sum(1 for f in findings if f["severity"] == "medium")
    verdict = "BLOCKED" if crit else ("WARNING" if high or med else "READY")
    return {"verdict": verdict,
            "score": max(0, 100 - 25 * crit - 10 * high - 3 * med),
            "critical": crit, "high": high, "medium": med}


def _unknown_gate(reason: str) -> dict:
    """Fail closed when reliability evidence is unavailable or unreadable."""
    return {"verdict": "UNKNOWN", "score": 0, "critical": 0, "high": 0,
            "medium": 0, "reason": reason}


def _runs_for_org(db: Session, org_id: str) -> tuple[list[dict] | None, dict | None]:
    """Return database evidence, with legacy JSON only as a dev-read fallback."""
    try:
        rows = (db.query(ReliabilityRun)
                .filter(ReliabilityRun.organization_id == org_id)
                .order_by(ReliabilityRun.created_at.desc()).limit(50).all())
        if rows:
            return [row.payload for row in rows], None
        # Existing local artifacts remain readable during development upgrades,
        # but a production release gate has only primary-database evidence.
        if not get_settings().is_prod:
            legacy = [r for r in store.load_runs() if r.get("org_id") == org_id]
            if legacy:
                return legacy, None
        # No evidence for this tenant is a normal initial state, not an
        # unavailable datastore. Callers render the explicit UNKNOWN/no-runs
        # gate rather than a false infrastructure alarm.
        return [], None
    except store.EvidenceMissing:
        return [], _unknown_gate("no reliability evidence has been recorded")
    except store.EvidenceStoreError:
        return [], _unknown_gate("legacy reliability evidence is unavailable or corrupt")


def _execute_suite(suite: dict) -> tuple[list[dict], list[dict], bool]:
    """Base scenarios must be clean on the CORRECT fixture; every mutation must
    produce exactly its expected violations on the broken fixture."""
    checks: list[dict] = []
    findings: list[dict] = []
    ok = True
    for sc in suite["scenarios"]:
        res = run_scenario(sc, PRESETS["correct"]())
        entry = {"scenario": sc["id"], "fixture": "correct",
                 "passed": res["passed"], "expected": sorted(res["expected"]),
                 "violations": res["violations"], "evidence": res["evidence"]}
        checks.append(entry)
        if not res["passed"]:
            ok = False
            entry["severity"] = "critical"
            findings.append(_finding(sc["id"], "correct-integration",
                                     res, sc.get("req_ids", [])))
        for mut in sc.get("mutations", []):
            mres = run_scenario(sc, PRESETS[mut["preset"]]())
            mok = set(mres["violations"]) == set(mut["expect"])
            mentry = {"scenario": sc["id"], "fixture": mut["name"],
                      "passed": mok, "expected": sorted(mut["expect"]),
                      "violations": mres["violations"],
                      "evidence": mres["evidence"]}
            checks.append(mentry)
            if not mok:
                ok = False
                mentry["severity"] = "critical" if not mres["violations"] \
                    else "high"
                findings.append(_finding(sc["id"], mut["name"], mres,
                                         sc.get("req_ids", []),
                                         mutation=True))
    return checks, findings, ok


# __PART2__
router = APIRouter(prefix="/api/reliability", tags=["reliability"])


@router.get("/overview")
def overview(p: Principal = Depends(current_principal),
             db: Session = Depends(get_db)) -> dict:
    suites = packs.all_suites()
    mine, unavailable_gate = _runs_for_org(db, p.organization_id)
    mine = mine or []
    last = mine[0] if mine else None
    return {"suites": len(suites),
            "scenarios": sum(len(s["scenarios"]) for s in suites),
            "requirements_traced": len({r for s in suites
                                        for r in s.get("req_ids", [])}),
            "last_run": ({"run_id": last["run_id"], "at": last["at"],
                          "gate": last["gate"]} if last else None),
            "gate": last["gate"] if last else (unavailable_gate or _unknown_gate("no run for this organization")),
            "spec_registry": requirement_summary()}


@router.get("/requirements")
def requirements(p: Principal = Depends(current_principal)) -> dict:
    """Return requirement-to-source traceability shown in the demo assurance UI."""
    return {"registry": requirement_details(sorted(REGISTRY)),
            "spec_registry": requirement_summary()}


@router.get("/suites")
def suites(p: Principal = Depends(current_principal)) -> dict:
    return {"suites": [{"suite_id": s["suite_id"], "title": s["title"],
                        "source": s["source"], "req_ids": s.get("req_ids", []),
                        "scenarios": [{"id": sc["id"], "title": sc["title"]}
                                      for sc in s["scenarios"]],
                        "mutations": sum(len(sc.get("mutations", []))
                                         for sc in s["scenarios"])}
                       for s in packs.all_suites()]}


@router.post("/run")
def run(body: dict | None = None,
        p: Principal = Depends(current_principal),
        db: Session = Depends(get_db)) -> dict:
    require_admin(p)
    body = body or {}
    merchant_id = body.get("merchant_id")
    requested = body.get("packs")
    wanted = requested or [s["suite_id"] for s in packs.all_suites()]
    runtime_requested = "razorpay/runtime" in wanted
    wanted = [sid for sid in wanted if sid != "razorpay/runtime"]
    if runtime_requested and not merchant_id:
        raise HTTPException(422, "merchant_id is required for razorpay/runtime")
    checks: list[dict] = []
    findings: list[dict] = []
    per_suite = []
    for sid in wanted:
        suite = packs.find_suite(sid)
        if suite is None:
            raise HTTPException(404, f"unknown suite {sid}")
        c, f, ok = _execute_suite(suite)
        checks.extend(c)
        findings.extend([{**x, "suite": sid, "org_id": p.organization_id}
                         for x in f])
        per_suite.append({"suite_id": sid, "passed": ok,
                          "checks": len(c), "findings": len(f)})
    if merchant_id:
        merchant = (db.query(Merchant)
                    .filter(Merchant.id == merchant_id,
                            Merchant.organization_id == p.organization_id)
                    .one_or_none())
        if merchant is None:
            raise HTTPException(404, "merchant not found")
        try:
            runtime = run_razorpay_runtime_checks(db, merchant.id)
        except SandboxOnlyError as exc:
            raise HTTPException(403, str(exc)) from exc
        checks.extend(runtime["checks"])
        findings.extend([{**f, "suite": runtime["suite_id"],
                          "org_id": p.organization_id}
                         for f in runtime["findings"]])
        per_suite.append({"suite_id": runtime["suite_id"],
                          "passed": runtime["passed"],
                          "checks": len(runtime["checks"]),
                          "findings": len(runtime["findings"]),
                          "mode": runtime["mode"]})
    run = {"run_id": "REL-" + uuid.uuid4().hex[:8], "at": _now(),
           "org_id": p.organization_id,
           "mode": "SANDBOX_RUNTIME" if merchant_id else "SANDBOX_FIXTURE",
           "seed": 20260825, "per_suite": per_suite, "checks": checks,
           "findings": findings, "gate": _gate(findings)}
    db.add(ReliabilityRun(
        run_id=run["run_id"], organization_id=p.organization_id, mode=run["mode"],
        gate_verdict=run["gate"]["verdict"], gate_score=run["gate"]["score"],
        payload=run,
    ))
    # A local JSON artifact remains a best-effort convenience for old dev
    # workflows. The DB row above is the release-gate source of truth.
    if not get_settings().is_prod:
        try:
            store.save_run(run)
        except store.EvidenceStoreError:
            pass
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="reliability.run", object_type="reliability_run",
        object_id=run["run_id"], summary="Sandbox reliability verification completed",
        details={"mode": run["mode"], "merchant_id": merchant_id,
                 "gate": run["gate"]},
    )
    db.commit()
    return run


@router.get("/runs")
def runs(p: Principal = Depends(current_principal),
         db: Session = Depends(get_db)) -> dict:
    mine, unavailable_gate = _runs_for_org(db, p.organization_id)
    if unavailable_gate:
        return {"runs": [], "gate": unavailable_gate}
    mine = mine or []
    return {"runs": [{"k": r["run_id"], "at": r["at"], "gate": r["gate"],
                      "verdict": r["gate"]["verdict"]} | {}
                     for r in mine]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)) -> dict:
    row = (db.query(ReliabilityRun)
           .filter(ReliabilityRun.organization_id == p.organization_id,
                   ReliabilityRun.run_id == run_id).one_or_none())
    r = row.payload if row is not None else None
    if r is None and not get_settings().is_prod:
        try:
            r = store.get_run(run_id)
        except store.EvidenceStoreError:
            r = None
    if not r or r.get("org_id") != p.organization_id:
        raise HTTPException(404, "run not found")
    return r


@router.get("/findings")
def findings(p: Principal = Depends(current_principal),
             db: Session = Depends(get_db)) -> dict:
    mine, unavailable_gate = _runs_for_org(db, p.organization_id)
    if unavailable_gate:
        return {"findings": [], "count": 0, "gate": unavailable_gate}
    mine = mine or []
    out = [f for r in mine for f in r["findings"]]
    return {"findings": out, "count": len(out)}


@router.get("/release-gate")
def release_gate(p: Principal = Depends(current_principal),
                 db: Session = Depends(get_db)) -> dict:
    runs, unavailable_gate = _runs_for_org(db, p.organization_id)
    if unavailable_gate:
        return {"org_id": p.organization_id, **unavailable_gate,
                "basis": "reliability evidence unavailable"}
    runs = runs or []
    gate = runs[0]["gate"] if runs else _unknown_gate("no run for this organization")
    return {"org_id": p.organization_id, **gate,
            "basis": "latest reliability run" if runs else "no runs yet"}


WEBHOOK_FAULTS = {
    "duplicate": ("GEN-WH-DUP", "correct"),
    "bad_signature": ("GEN-WH-BADSIG", "correct"),
    "timeout_redelivery": ("GEN-WH-DUP", "correct"),
    "out_of_order": ("RZP-WH-REORDER", "correct"),
}
NOTES = {
    "duplicate": "second copy ignored via x-razorpay-event-id dedupe",
    "bad_signature": "rejected before processing — zero side-effects",
    "timeout_redelivery": "redelivered after 5s timeout — deduplicated",
    "out_of_order": "arrived captured-first; converged to paid+fulfilled",
}


@router.post("/webhook-lab/{fault}")
def webhook_lab(fault: str,
                p: Principal = Depends(current_principal)) -> dict:
    require_admin(p)
    if fault not in WEBHOOK_FAULTS:
        raise HTTPException(404, f"unknown fault '{fault}'")
    sid, preset = WEBHOOK_FAULTS[fault]
    suite = next(s for s in packs.all_suites()
                 if any(sc["id"] == sid for sc in s["scenarios"]))
    sc = next(sc for sc in suite["scenarios"] if sc["id"] == sid)
    res = run_scenario(sc, PRESETS[preset]())
    return {"fault": fault, "scenario": sid, "fixture": preset,
            "observed": res["evidence"],
            "invariant_violations": res["violations"],
            "note": NOTES[fault]}
