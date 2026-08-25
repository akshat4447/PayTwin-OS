"""Policies: list, create, version-bump edit, blocked log, historical preview."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db, require_admin
from paytwin_api.models import (
    ActionExecution,
    Merchant,
    Policy,
    PolicyDecision,
)
from paytwin_api.services.policy import DEFAULT_RULES, merge_rules

router = APIRouter(prefix="/api/policies", tags=["policies"])


@router.get("")
def list_policies(p: Principal = Depends(current_principal),
                  db: Session = Depends(get_db), scope: str | None = None):
    q = db.query(Policy).filter(Policy.organization_id == p.organization_id)
    if scope and scope != "org":
        q = q.filter(Policy.merchant_id == scope)
    rows = q.order_by(Policy.human_id, Policy.version.desc()).all()
    seen: set[str] = set()
    out = []
    for r in rows:
        if r.human_id in seen:
            continue  # latest version per human id
        seen.add(r.human_id)
        out.append({"human_id": r.human_id, "name": r.name, "version": r.version,
                    "status": r.status, "rules": r.rules,
                    "merchant_id": r.merchant_id})
    return out


class PolicyBody(BaseModel):
    merchant_id: str
    name: str
    rules: dict = {}
    status: str = "live"


def _next_human_id(db: Session, org_id: str) -> str:
    n = db.query(Policy).filter(Policy.organization_id == org_id).count()
    return f"RP-{7 + (n % 990)}"


@router.post("")
def create_policy(body: PolicyBody, p: Principal = Depends(current_principal),
                  db: Session = Depends(get_db)):
    require_admin(p)
    if (db.query(Merchant)
            .filter(Merchant.organization_id == p.organization_id,
                    Merchant.id == body.merchant_id).one_or_none() is None):
        return err(404, "not_found", f"merchant {body.merchant_id}")
    unknown = set(body.rules) - set(DEFAULT_RULES)
    if unknown:
        return err(422, "unknown_rule", f"unrecognized rule ids: {sorted(unknown)}")
    row = Policy(organization_id=p.organization_id, merchant_id=body.merchant_id,
                 human_id=_next_human_id(db, p.organization_id), name=body.name,
                 version=1, status=body.status, rules=body.rules,
                 created_by=p.user_id or p.role)
    db.add(row)
    db.commit()
    return {"human_id": row.human_id, "version": row.version, "status": row.status}


class PatchBody(BaseModel):
    rules: dict | None = None
    status: str | None = None


@router.patch("/{human_id}")
def patch_policy(human_id: str, body: PatchBody,
                 p: Principal = Depends(current_principal),
                 db: Session = Depends(get_db)):
    require_admin(p)
    latest = (db.query(Policy)
              .filter(Policy.organization_id == p.organization_id,
                      Policy.human_id == human_id.upper())
              .order_by(Policy.version.desc()).first())
    if latest is None:
        return err(404, "not_found", f"policy {human_id}")
    if body.rules:
        unknown = set(body.rules) - set(DEFAULT_RULES)
        if unknown:
            return err(422, "unknown_rule", f"unrecognized rule ids: {sorted(unknown)}")
    row = Policy(organization_id=latest.organization_id,
                 merchant_id=latest.merchant_id, human_id=latest.human_id,
                 name=latest.name, version=latest.version + 1,
                 status=body.status or latest.status,
                 rules=body.rules if body.rules is not None else latest.rules,
                 created_by=p.user_id or p.role)
    latest.status = "archived"
    db.add(row)
    db.commit()
    return {"human_id": row.human_id, "version": row.version, "status": row.status,
            "rules": row.rules}


@router.get("/blocked")
def blocked_log(p: Principal = Depends(current_principal),
                db: Session = Depends(get_db), scope: str | None = None):
    q = (db.query(PolicyDecision, ActionExecution)
         .join(ActionExecution,
               ActionExecution.id == PolicyDecision.action_execution_id)
         .filter(PolicyDecision.organization_id == p.organization_id,
                 PolicyDecision.decision == "block"))
    if scope and scope != "org":
        q = q.filter(PolicyDecision.merchant_id == scope)
    rows = q.order_by(PolicyDecision.created_at.desc()).limit(50).all()
    return [{"human_id": ex.human_id, "kind": ex.kind, "state": ex.state,
             "failed_rules": d.failed_rules,
             "at": d.created_at.isoformat()} for d, ex in rows]


class PreviewBody(BaseModel):
    merchant_id: str
    draft_rules: dict


@router.post("/preview")
def preview(body: PreviewBody, p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)):
    """Historical replay: what would the draft rules have done to past actions?"""
    require_admin(p)
    from paytwin_api.services.policy import PolicyContext, evaluate

    draft = merge_rules(body.draft_rules)
    rows = (db.query(ActionExecution, PolicyDecision)
            .join(PolicyDecision,
                  PolicyDecision.action_execution_id == ActionExecution.id)
            .filter(ActionExecution.organization_id == p.organization_id,
                    ActionExecution.merchant_id == body.merchant_id)
            .order_by(ActionExecution.created_at.desc()).limit(200).all())
    flips, unchanged, would_block = 0, 0, 0
    for ex, dec in rows:
        merchant = db.query(Merchant).filter(Merchant.id == ex.merchant_id).one()
        ctx = PolicyContext(
            merchant_id=ex.merchant_id, autonomy_mode=merchant.autonomy_mode,
            action_kind=ex.kind,
            amount_paise=int(ex.params.get(
                "slice_value_paise", ex.params.get("amount_cap_paise", 0))),
            attempts_used=int(ex.params.get("attempts_used", 1)),
        )
        new_dec = evaluate(draft, ctx).decision
        would_block += new_dec == "block"
        flips += new_dec != dec.decision
        unchanged += new_dec == dec.decision
    return {"replayed": len(rows), "would_block": would_block,
            "verdict_changes": flips, "unchanged": unchanged}