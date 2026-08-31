"""Incidents: list, detail, policy-gated execute, resolve."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db, require_write
from paytwin_api.models import (
    ActionCandidate,
    ActionExecution,
    AuditRecord,
    Incident,
    IncidentEvidence,
    Merchant,
    PolicyDecision,
    RootCauseCandidate,
)
from paytwin_api.services import executor as executor_svc
from paytwin_api.services import incident_service
from paytwin_api.services.bus import publish_outbox
from paytwin_api.services.policy import PolicyContext, active_rules, evaluate, merge_rules

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _get(db: Session, org_id: str, human_id: str) -> Incident | None:
    return (db.query(Incident)
            .filter(Incident.organization_id == org_id,
                    Incident.human_id == human_id.upper()).one_or_none())


@router.get("")
def list_incidents(p: Principal = Depends(current_principal),
                   db: Session = Depends(get_db), scope: str | None = None,
                   state: str | None = None):
    q = db.query(Incident).filter(Incident.organization_id == p.organization_id)
    if scope and scope != "org":
        q = q.filter(Incident.merchant_id == scope)
    if state:
        q = q.filter(Incident.state == state)
    rows = q.order_by(Incident.detected_at.desc()).limit(100).all()
    return [{"human_id": i.human_id, "title": i.title, "sev": i.sev,
             "state": i.state, "merchant_id": i.merchant_id,
             "rar_paise": i.rar_paise,
             "rar_lo_paise": i.rar_lo_paise, "rar_hi_paise": i.rar_hi_paise,
             "affected_payments": i.affected_payments,
             "confidence": i.confidence,
             "cohort": {k: v for k, v in i.cohort().items() if v}}
            for i in rows]


class ExecuteBody(BaseModel):
    candidate_id: str


@router.post("/{human_id}/execute")
def execute(human_id: str, body: ExecuteBody,
            p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)):
    require_write(p)
    inc = _get(db, p.organization_id, human_id)
    if inc is None:
        return err(404, "not_found", f"incident {human_id}")
    cand = (db.query(ActionCandidate)
            .filter(ActionCandidate.id == body.candidate_id,
                    ActionCandidate.incident_id == inc.id).one_or_none())
    if cand is None:
        return err(404, "not_found", f"candidate {body.candidate_id}")
    merchant = (db.query(Merchant)
                .filter(Merchant.organization_id == p.organization_id,
                        Merchant.id == inc.merchant_id).one_or_none())
    if merchant is None:
        return err(404, "not_found", "merchant")
    ex, res = executor_svc.request_execution(
        db, p, merchant, cand,
        actor=p.user_id or f"{p.role}@{p.key_prefix}")
    if res is None:
        # idempotent replay: same execution returned, no second business action
        db.commit()
        return {"decision": "duplicate", "execution_id": ex.id,
                "human_id": ex.human_id, "state": ex.state, "failed_rules": []}
    publish_outbox(db, p.organization_id, "policy_decision",
                   {"incident": inc.human_id, "decision": res.decision,
                    "failed_rules": res.failed_rules})
    if ex.state not in ("REJECTED_BY_POLICY", "VALIDATED"):
        publish_outbox(db, p.organization_id, "action",
                       {"execution": ex.human_id or ex.id, "kind": ex.kind,
                        "state": ex.state})
    db.commit()
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=202, content={
        "decision": res.decision, "execution_id": ex.id,
        "human_id": ex.human_id, "state": ex.state,
        "failed_rules": res.failed_rules})


@router.post("/{human_id}/resolve")
def resolve_route(human_id: str, p: Principal = Depends(current_principal),
                  db: Session = Depends(get_db)):
    require_write(p)
    inc = _get(db, p.organization_id, human_id)
    if inc is None:
        return err(404, "not_found", f"incident {human_id}")
    incident_service.resolve(db, inc, actor=p.user_id or p.role)
    publish_outbox(db, p.organization_id, "incident",
                   {"incident": inc.human_id, "state": inc.state})
    db.commit()
    return {"human_id": inc.human_id, "state": inc.state}


@router.post("/{human_id}/approve")
def approve_route(human_id: str, p: Principal = Depends(current_principal),
                  db: Session = Depends(get_db)):
    """Approve-and-execute the incident's pending VALIDATED execution."""
    require_write(p)
    inc = _get(db, p.organization_id, human_id)
    if inc is None:
        return err(404, "not_found", f"incident {human_id}")
    ex = (db.query(ActionExecution)
          .filter(ActionExecution.incident_id == inc.id,
                  ActionExecution.state.in_(("VALIDATED", "APPROVED")))
          .order_by(ActionExecution.created_at.desc()).first())
    if ex is None:
        return err(409, "nothing_to_approve",
                   f"incident {human_id} has no execution awaiting approval")
    actor = p.user_id or f"{p.role}@{p.key_prefix}"
    try:
        executor_svc.approve_and_execute(db, p, ex.id, actor)
    except ValueError as e:
        return err(409, "not_approvable", str(e))
    publish_outbox(db, p.organization_id, "action",
                   {"incident": inc.human_id, "human_id": ex.human_id,
                    "state": ex.state})
    db.commit()
    return {"human_id": inc.human_id, "execution_id": ex.id,
            "execution_human_id": ex.human_id, "state": ex.state}


@router.post("/{human_id}/halt")
def halt_route(human_id: str, p: Principal = Depends(current_principal),
               db: Session = Depends(get_db)):
    """Human takes the wheel: stop autopilot on this incident."""
    require_write(p)
    inc = _get(db, p.organization_id, human_id)
    if inc is None:
        return err(404, "not_found", f"incident {human_id}")
    if inc.state == "RESOLVED":
        return err(409, "already_resolved", f"incident {human_id} is resolved")
    inc.state = "HALTED"
    from paytwin_api.services import audit as audit_svc

    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or p.role,
        actor_role="human-operator", action_type="autopilot.halt",
        object_type="incident", object_id=inc.human_id,
        summary=f"Autopilot halted on {inc.human_id} by operator",
        incident_id=inc.id)
    publish_outbox(db, p.organization_id, "incident",
                   {"incident": inc.human_id, "state": inc.state})
    db.commit()
    return {"human_id": inc.human_id, "state": inc.state}


@router.get("/{human_id}")
def detail(human_id: str, p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)):
    inc = _get(db, p.organization_id, human_id)
    if inc is None:
        return err(404, "not_found", f"incident {human_id}")
    merchant = (db.query(Merchant).filter(Merchant.id == inc.merchant_id)
                .one_or_none())
    if merchant is not None:
        # Same enforcement source as the executor: live versioned policies.
        rules, _policy_label = active_rules(db, inc.organization_id, merchant)
    else:
        rules = merge_rules(None)
    causes = [[
        " x ".join(f"{k}={v}" for k, v in {
            "issuer": r.edge_issuer, "method": r.edge_method,
            "psp": r.edge_psp}.items() if v),
        round(r.score, 3), r.counterfactual_share > 0.5]
        for r in db.query(RootCauseCandidate)
        .filter(RootCauseCandidate.incident_id == inc.id)
        .order_by(RootCauseCandidate.rank).all()]
    executions = (db.query(ActionExecution)
                  .filter(ActionExecution.incident_id == inc.id)
                  .order_by(ActionExecution.created_at.desc()).all())
    latest_execution_by_candidate = {}
    for execution in executions:
        if execution.candidate_id and execution.candidate_id not in latest_execution_by_candidate:
            latest_execution_by_candidate[execution.candidate_id] = execution

    cands = []
    for c in (db.query(ActionCandidate).filter(ActionCandidate.incident_id == inc.id)
              .order_by(ActionCandidate.rank).all()):
        verdict = evaluate(rules, PolicyContext(
            merchant_id=inc.merchant_id,
            autonomy_mode=merchant.autonomy_mode if merchant else 0,
            action_kind=c.kind,
            amount_paise=int(c.params.get(
                "slice_value_paise",
                c.params.get("amount_cap_paise", c.value_paise or 0))),
            attempts_used=int(c.params.get("attempts_used", 1)),
        ))
        execution = latest_execution_by_candidate.get(c.id)
        cands.append({"id": c.id, "kind": c.kind, "label": c.label,
                      "detail": c.detail, "ev_paise": c.ev_paise,
                      "p_succ_delta": c.p_succ_delta,
                      "policy": verdict.decision,
                      "execution": ({"id": execution.id,
                                     "human_id": execution.human_id,
                                     "state": execution.state}
                                    if execution else None)})
    evidence = [{"kind": e.kind, "ref": e.ref, "summary": e.summary}
                for e in db.query(IncidentEvidence)
                .filter_by(incident_id=inc.id).all()]
    timeline = (
        [{"ts": a.created_at.isoformat(), "kind": a.action_type,
          "summary": a.summary}
         for a in db.query(AuditRecord)
         .filter(AuditRecord.incident_id == inc.id)
         .order_by(AuditRecord.seq).all()])
    return {
        "header": {"human_id": inc.human_id, "title": inc.title, "sev": inc.sev,
                   "state": inc.state, "confidence": inc.confidence,
                   "cohort": {k: v for k, v in inc.cohort().items() if v},
                   "detected_at": inc.detected_at.isoformat()},
        "timeline": timeline,
        "causes": causes,
        "candidates": cands,
        "evidence": evidence,
        "rar": {"expected_paise": inc.rar_paise, "lo_paise": inc.rar_lo_paise,
                "hi_paise": inc.rar_hi_paise,
                "affected_payments": inc.affected_payments,
                "affected_customers": inc.affected_customers},
        "sr": {"baseline_bp": inc.baseline_sr_bp, "current_bp": inc.current_sr_bp},
    }
