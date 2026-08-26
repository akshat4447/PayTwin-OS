"""AUDIT-001: append-only, per-organization SHA-256 hash chain.

Every decision, block, action, and model promotion lands here. Hardening:
- Fork guard: UNIQUE(organization_id, prev_hash) — two concurrent writers can
  never both claim the same chain position; the loser retries against the
  winner's head.
- Tail guard: a per-org AuditHead checkpoint (last seq/hash + record count).
  verify_chain() requires the live records to agree with the head, so deleting
  the newest record (or any tail record) fails verification even though the
  remaining prefix still hashes correctly.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paytwin_api.models import AuditHead, AuditRecord

_MAX_APPEND_RETRIES = 4


def _hash(prev: str, payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev + canon).encode()).hexdigest()


def _payload(organization_id: str, actor: str, actor_role: str, action_type: str,
             object_type: str, object_id: str, summary: str, details: dict,
             policy_version: str | None) -> dict:
    return {
        "organization_id": organization_id, "actor": actor, "actor_role": actor_role,
        "action_type": action_type, "object_type": object_type, "object_id": object_id,
        "summary": summary, "details": details, "policy_version": policy_version,
    }


def append_audit(db: Session, organization_id: str, actor: str, actor_role: str,
                 action_type: str, object_type: str, object_id: str, summary: str,
                 details: dict | None = None, incident_id: str | None = None,
                 policy_version: str | None = None) -> AuditRecord:
    details = details or {}
    payload = _payload(organization_id, actor, actor_role, action_type,
                       object_type, object_id, summary, details, policy_version)
    last_error: IntegrityError | None = None
    for _attempt in range(_MAX_APPEND_RETRIES):
        head = (db.query(AuditHead)
                .filter(AuditHead.organization_id == organization_id)
                .one_or_none())
        if head is not None:
            prev_hash = head.last_hash
            base_count = head.record_count or 0
        else:
            # Legacy chain without a checkpoint yet: adopt the existing tail.
            last_rec = (db.query(AuditRecord)
                        .filter(AuditRecord.organization_id == organization_id)
                        .order_by(AuditRecord.seq.desc()).first())
            prev_hash = last_rec.hash if last_rec else ""
            base_count = (db.query(AuditRecord)
                          .filter(AuditRecord.organization_id == organization_id)
                          .count())
        rec = AuditRecord(
            organization_id=organization_id, actor=actor, actor_role=actor_role,
            action_type=action_type, object_type=object_type, object_id=object_id,
            incident_id=incident_id, summary=summary, details=details,
            policy_version=policy_version, prev_hash=prev_hash,
            hash=_hash(prev_hash, payload),
        )
        try:
            with db.begin_nested():  # fork loser rolls back only this savepoint
                db.add(rec)
                db.flush()
                if head is None:
                    head = AuditHead(organization_id=organization_id,
                                     last_seq=rec.seq, last_hash=rec.hash,
                                     record_count=base_count + 1)
                    db.add(head)
                else:
                    head.last_seq = rec.seq
                    head.last_hash = rec.hash
                    head.record_count = base_count + 1
                db.flush()
            return rec
        except IntegrityError as e:  # concurrent writer claimed this chain position
            last_error = e
            continue
    raise RuntimeError(
        "audit chain contention: could not append after "
        f"{_MAX_APPEND_RETRIES} retries") from last_error


def verify_chain(db: Session, organization_id: str) -> tuple[bool, int | None]:
    """Recompute the chain AND the tail checkpoint; returns (ok, first_bad_seq or None)."""
    prev = ""
    count = 0
    last: AuditRecord | None = None
    for rec in (db.query(AuditRecord)
                .filter(AuditRecord.organization_id == organization_id)
                .order_by(AuditRecord.seq.asc()).all()):
        expect = _hash(rec.prev_hash, _payload(
            rec.organization_id, rec.actor, rec.actor_role, rec.action_type,
            rec.object_type, rec.object_id, rec.summary, rec.details or {},
            rec.policy_version))
        if rec.prev_hash != prev or rec.hash != expect:
            return False, rec.seq
        prev = rec.hash
        count += 1
        last = rec
    head = (db.query(AuditHead)
            .filter(AuditHead.organization_id == organization_id)
            .one_or_none())
    if head is not None and (head.record_count or 0) > 0:
        # Deletion/tail tampering: a valid prefix that lost records still fails.
        if count != head.record_count or last is None or last.hash != head.last_hash:
            return False, head.last_seq
    return True, None
