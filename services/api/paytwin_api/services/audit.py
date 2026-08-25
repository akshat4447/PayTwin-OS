"""AUDIT-001: append-only, per-organization SHA-256 hash chain.

Every decision, block, action, and model promotion lands here. verify_chain() recomputes
the whole chain; any tampering breaks it at the exact seq.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from paytwin_api.models import AuditRecord


def _hash(prev: str, payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev + canon).encode()).hexdigest()


def append_audit(db: Session, organization_id: str, actor: str, actor_role: str,
                 action_type: str, object_type: str, object_id: str, summary: str,
                 details: dict | None = None, incident_id: str | None = None,
                 policy_version: str | None = None) -> AuditRecord:
    prev = (
        db.query(AuditRecord.hash)
        .filter(AuditRecord.organization_id == organization_id)
        .order_by(AuditRecord.seq.desc())
        .first()
    )
    prev_hash = prev[0] if prev else ""
    details = details or {}
    h = _hash(prev_hash, {
        "organization_id": organization_id, "actor": actor, "actor_role": actor_role,
        "action_type": action_type, "object_type": object_type, "object_id": object_id,
        "summary": summary, "details": details, "policy_version": policy_version,
    })
    rec = AuditRecord(
        organization_id=organization_id, actor=actor, actor_role=actor_role,
        action_type=action_type, object_type=object_type, object_id=object_id,
        incident_id=incident_id, summary=summary, details=details,
        policy_version=policy_version, prev_hash=prev_hash, hash=h,
    )
    db.add(rec)
    db.flush()
    return rec


def verify_chain(db: Session, organization_id: str) -> tuple[bool, int | None]:
    """Recompute the chain; returns (ok, first_bad_seq or None)."""
    prev = ""
    for rec in (db.query(AuditRecord)
                .filter(AuditRecord.organization_id == organization_id)
                .order_by(AuditRecord.seq.asc()).all()):
        expect = _hash(rec.prev_hash, {
            "organization_id": rec.organization_id, "actor": rec.actor,
            "actor_role": rec.actor_role, "action_type": rec.action_type,
            "object_type": rec.object_type, "object_id": rec.object_id,
            "summary": rec.summary, "details": rec.details or {},
            "policy_version": rec.policy_version,
        })
        if rec.prev_hash != prev or rec.hash != expect:
            return False, rec.seq
        prev = rec.hash
    return True, None
