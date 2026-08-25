"""Dashboard routers: overview, funnel, healthmap, merchants (all tenant-filtered)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db
from paytwin_api.models import (
    ActionExecution,
    AuditRecord,
    Incident,
    Merchant,
    Payment,
    PolicyDecision,
)

router = APIRouter(tags=["dashboard"])


def _scope_merchant(db: Session, org_id: str, scope: str | None) -> str | None:
    if scope and scope != "org":
        m = (db.query(Merchant)
             .filter(Merchant.organization_id == org_id, Merchant.id == scope)
             .one_or_none())
        return m.id if m else None
    return None


def _utc(r: Payment) -> datetime:
    dt = r.occurred_at
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _sr_bp(rows: list[Payment]) -> int:
    if not rows:
        return 10000
    ok = sum(1 for r in rows if r.status == "success")
    return int(ok * 10000 / len(rows))


@router.get("/api/overview")
def overview(p: Principal = Depends(current_principal), db: Session = Depends(get_db),
             scope: str | None = None):
    mer_id = _scope_merchant(db, p.organization_id, scope)
    q = db.query(Payment).filter(Payment.organization_id == p.organization_id)
    if mer_id:
        q = q.filter(Payment.merchant_id == mer_id)
    pays = q.all()
    gmv = sum(r.amount_paise for r in pays if r.status == "success")
    open_q = db.query(Incident).filter(
        Incident.organization_id == p.organization_id,
        Incident.state.notin_(("RESOLVED", "POSTMORTEM")))
    if mer_id:
        open_q = open_q.filter(Incident.merchant_id == mer_id)
    open_inc = open_q.all()
    recovered = sum((r.outcome or {}).get("recovered", 0)
                    for r in db.query(ActionExecution)
                    .filter(ActionExecution.organization_id == p.organization_id,
                            ActionExecution.state == "SUCCEEDED").all())
    protected = sum(m.protected_mtd_paise for m in
                    db.query(Merchant).filter(
                        Merchant.organization_id == p.organization_id).all())

    now = datetime.now(timezone.utc)
    pulse = []
    for b in range(16, 0, -1):
        lo, hi = now - timedelta(minutes=5 * b), now - timedelta(minutes=5 * (b - 1))
        pulse.append(_sr_bp([r for r in pays if lo <= _utc(r) < hi]))
    labels, vals = [], []
    for h in range(12, 0, -1):
        lo, hi = now - timedelta(hours=h), now - timedelta(hours=h - 1)
        bucket = [r for r in pays if lo <= _utc(r) < hi]
        labels.append(lo.strftime("%H:%M"))
        vals.append(sum(r.amount_paise for r in bucket if r.status == "success"))

    audits = (db.query(AuditRecord)
              .filter(AuditRecord.organization_id == p.organization_id)
              .order_by(AuditRecord.seq.desc()).limit(6).all())
    blocked = (db.query(PolicyDecision)
               .filter(PolicyDecision.organization_id == p.organization_id,
                       PolicyDecision.decision == "block")
               .order_by(PolicyDecision.created_at.desc()).limit(5).all())
    overall = _sr_bp(pays)

    return {
        "metrics": {"gmv_mtd_paise": gmv, "sr_bp": overall,
                    "rar_paise": sum(i.rar_paise for i in open_inc),
                    "protected_paise": protected,
                    "active_incidents": len(open_inc), "retries_avoided": recovered},
        "pulse": pulse,
        "series": {"labels": labels, "values": vals},
        "incidents": [{"human_id": i.human_id, "sev": i.sev, "title": i.title,
                       "state": i.state, "rar_paise": i.rar_paise}
                      for i in sorted(open_inc, key=lambda x: -x.rar_paise)[:3]],
        "stream_rows": [{"seq": a.seq, "ts": a.created_at.isoformat(),
                         "actor": a.actor, "summary": a.summary}
                        for a in audits],
        "notifs": [{"id": d.id, "failed_rules": d.failed_rules} for d in blocked],
        "lvl": {"network": ("ok" if overall >= 9500 else
                            "degraded" if overall >= 9000 else "critical"),
                "merchant": "ok" if not open_inc else "degraded",
                "payment": "ok"},
    }


@router.get("/api/funnel")
def funnel(p: Principal = Depends(current_principal), db: Session = Depends(get_db),
           scope: str | None = None):
    mer_id = _scope_merchant(db, p.organization_id, scope)
    q = db.query(Payment).filter(Payment.organization_id == p.organization_id)
    if mer_id:
        q = q.filter(Payment.merchant_id == mer_id)
    pays = q.all()
    # v1 funnel is outcome-based; checkout-stage events arrive with the web SDK later
    return {"stages": [
        {"stage": "initiated", "count": len(pays)},
        {"stage": "completed", "count": sum(1 for r in pays if r.status == "success")},
        {"stage": "failed_or_timeout",
         "count": sum(1 for r in pays if r.status in ("failed", "timeout"))},
    ]}


@router.get("/api/healthmap")
def healthmap(p: Principal = Depends(current_principal),
              db: Session = Depends(get_db), scope: str | None = None):
    mer_id = _scope_merchant(db, p.organization_id, scope)
    q = db.query(Payment).filter(Payment.organization_id == p.organization_id)
    if mer_id:
        q = q.filter(Payment.merchant_id == mer_id)
    rows: dict[str, dict] = {}
    for r in q.all():
        for dim, v in (("issuer", r.issuer), ("method", r.method),
                       ("psp", r.psp), ("gateway", r.gateway)):
            if not v:
                continue
            s = rows.setdefault(f"{dim}:{v}",
                                {"dim": dim, "value": v, "attempts": 0, "ok": 0})
            s["attempts"] += 1
            s["ok"] += 1 if r.status == "success" else 0
    out = [{**s, "sr_bp": int(s["ok"] * 10000 / s["attempts"])}
           for s in rows.values() if s["attempts"] > 0]
    return sorted(out, key=lambda s: s["sr_bp"])


@router.get("/api/merchants")
def merchants_list(p: Principal = Depends(current_principal),
                   db: Session = Depends(get_db)):
    ms = (db.query(Merchant).filter(Merchant.organization_id == p.organization_id)
          .order_by(Merchant.created_at).all())
    return [{"id": m.id, "name": m.name, "short_code": m.short_code,
             "autonomy_mode": m.autonomy_mode, "stage": m.stage,
             "gmv_mtd_paise": m.gmv_mtd_paise,
             "protected_mtd_paise": m.protected_mtd_paise} for m in ms]


@router.get("/api/merchants/{merchant_id}")
def merchant_detail(merchant_id: str, p: Principal = Depends(current_principal),
                    db: Session = Depends(get_db)):
    m = (db.query(Merchant)
         .filter(Merchant.organization_id == p.organization_id,
                 Merchant.id == merchant_id).one_or_none())
    if m is None:
        return err(404, "not_found", f"merchant {merchant_id}")
    pays = db.query(Payment).filter(Payment.merchant_id == m.id).all()
    return {"id": m.id, "name": m.name, "short_code": m.short_code,
            "autonomy_mode": m.autonomy_mode, "stages": m.stage,
            "industry": (m.config or {}).get("industry"),
            "sr_bp": _sr_bp(pays), "gmv_mtd_paise": m.gmv_mtd_paise,
            "protected_mtd_paise": m.protected_mtd_paise,
            "payments": len(pays)}