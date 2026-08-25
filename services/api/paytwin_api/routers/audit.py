"""Audit: filtered listing, chain verify, jsonl/dossier export."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, get_db
from paytwin_api.models import AuditRecord
from paytwin_api.services.audit import verify_chain

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(p: Principal = Depends(current_principal),
               db: Session = Depends(get_db), scope: str | None = None,
               actor: str | None = None, type: str | None = None,
               limit: int = 100):
    q = db.query(AuditRecord).filter(AuditRecord.organization_id
                                     == p.organization_id)
    if actor:
        q = q.filter(AuditRecord.actor == actor)
    if type:
        q = q.filter(AuditRecord.action_type == type)
    rows = q.order_by(AuditRecord.seq.desc()).limit(min(limit, 500)).all()
    return [{"seq": r.seq, "id": r.id, "ts": r.created_at.isoformat(),
             "actor": r.actor, "actor_role": r.actor_role,
             "action_type": r.action_type, "object_type": r.object_type,
             "object_id": r.object_id, "summary": r.summary,
             "details": r.details} for r in rows]


@router.get("/verify")
def verify(p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)):
    ok, bad = verify_chain(db, p.organization_id)
    return {"ok": ok, "first_bad_seq": bad}


@router.get("/export")
def export(fmt: str = "jsonl", p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)):
    rows = (db.query(AuditRecord)
            .filter(AuditRecord.organization_id == p.organization_id)
            .order_by(AuditRecord.seq).all())
    if fmt == "dossier":
        lines = ["# PayTwin OS — Audit Dossier",
                 f"# organization: {p.organization_id}", ""]
        for r in rows:
            lines.append(f"## #{r.seq} {r.action_type}")
            lines.append(f"- when: {r.created_at.isoformat()}")
            lines.append(f"- actor: {r.actor} ({r.actor_role})")
            lines.append(f"- object: {r.object_type}/{r.object_id}")
            lines.append(f"- summary: {r.summary}")
            lines.append(f"- hash: {r.hash[:16]}… prev: {r.prev_hash[:16]}…")
            lines.append("")
        body = "\n".join(lines)
        return Response(content=body, media_type="text/markdown",
                        headers={"Content-Disposition":
                                 f'attachment; filename="audit-{p.organization_id}.md"'})
    body = "\n".join(
        __import__("json").dumps({
            "seq": r.seq, "id": r.id, "ts": r.created_at.isoformat(),
            "organization_id": r.organization_id, "actor": r.actor,
            "actor_role": r.actor_role, "action_type": r.action_type,
            "object_type": r.object_type, "object_id": r.object_id,
            "summary": r.summary, "details": r.details,
            "prev_hash": r.prev_hash, "hash": r.hash}, default=str)
        for r in rows)
    return Response(content=body, media_type="application/x-ndjson",
                    headers={"Content-Disposition":
                             f'attachment; filename="audit-{p.organization_id}.jsonl"'})