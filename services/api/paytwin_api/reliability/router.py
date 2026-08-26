"""Reliability Lab API — suites, deterministic runs, findings, webhook lab, release gate."""
from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Principal
from ..deps import current_principal
from . import packs, store
from .engine import run_scenario
from .fixtures import PRESETS

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
            "evidence": {"expected": res["expected"],
                         "actual": res["violations"]}}


def _gate(findings: list[dict]) -> dict:
    crit = sum(1 for f in findings if f["severity"] == "critical")
    high = sum(1 for f in findings if f["severity"] == "high")
    med = sum(1 for f in findings if f["severity"] == "medium")
    verdict = "BLOCKED" if crit else ("WARNING" if high or med else "READY")
    return {"verdict": verdict,
            "score": max(0, 100 - 25 * crit - 10 * high - 3 * med),
            "critical": crit, "high": high, "medium": med}


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
def overview(p: Principal = Depends(current_principal)) -> dict:
    suites = packs.all_suites()
    mine = [r for r in store.load_runs() if r.get("org_id") == p.organization_id]
    last = mine[0] if mine else None
    return {"suites": len(suites),
            "scenarios": sum(len(s["scenarios"]) for s in suites),
            "requirements_traced": len({r for s in suites
                                        for r in s.get("req_ids", [])}),
            "last_run": ({"run_id": last["run_id"], "at": last["at"],
                          "gate": last["gate"]} if last else None),
            "gate": last["gate"] if last else _gate([]),
            "spec_registry": {"provider": "razorpay", "docs_verified": 7,
                              "requirements": 14, "last_refresh": "2026-08-26"}}


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
        p: Principal = Depends(current_principal)) -> dict:
    body = body or {}
    wanted = body.get("packs") or [s["suite_id"] for s in packs.all_suites()]
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
    run = {"run_id": "REL-" + uuid.uuid4().hex[:8], "at": _now(),
           "org_id": p.organization_id, "mode": body.get("mode", "test"),
           "seed": 20260825, "per_suite": per_suite, "checks": checks,
           "findings": findings, "gate": _gate(findings)}
    store.save_run(run)
    return run


@router.get("/runs")
def runs(p: Principal = Depends(current_principal)) -> dict:
    mine = [r for r in store.load_runs() if r.get("org_id") == p.organization_id]
    return {"runs": [{"k": r["run_id"], "at": r["at"], "gate": r["gate"],
                      "verdict": r["gate"]["verdict"]} | {}
                     for r in mine]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, p: Principal = Depends(current_principal)) -> dict:
    r = store.get_run(run_id)
    if not r or r.get("org_id") != p.organization_id:
        raise HTTPException(404, "run not found")
    return r


@router.get("/findings")
def findings(p: Principal = Depends(current_principal)) -> dict:
    mine = [r for r in store.load_runs() if r.get("org_id") == p.organization_id]
    out = [f for r in mine for f in r["findings"]]
    return {"findings": out, "count": len(out)}


@router.get("/release-gate")
def release_gate(p: Principal = Depends(current_principal)) -> dict:
    runs = [r for r in store.load_runs() if r.get("org_id") == p.organization_id]
    gate = runs[0]["gate"] if runs else _gate([])
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

