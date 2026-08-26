"""Transactional outbox + in-process SSE fan-out (Kafka-compatible seam, ADR-003/008).

Publish semantics: SSE events are emitted only AFTER the surrounding transaction
commits (SQLAlchemy after_commit hook). Clients can therefore never receive an
action/decision that was rolled back and never persisted; a rollback drops the
pending events silently.
"""
from __future__ import annotations

import asyncio
import json
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from paytwin_api.models import Outbox


@dataclass
class BusEvent:
    topic: str
    organization_id: str
    payload: dict


@dataclass
class Bus:
    """In-process pub/sub for SSE. Outbox rows remain the durable record."""
    _subs: dict[str, list] = field(default_factory=dict)

    def subscribe(self, org_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.setdefault(org_id, []).append(q)
        return q

    def unsubscribe(self, org_id: str, q: asyncio.Queue) -> None:
        try:
            self._subs.get(org_id, []).remove(q)
        except (KeyError, ValueError):
            pass

    def publish(self, org_id: str, topic: str, payload: dict) -> None:
        ev = BusEvent(topic=topic, organization_id=org_id, payload=payload)
        for q in list(self._subs.get(org_id, [])):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass  # slow consumer: SSE clients rely on periodic refetch anyway


bus = Bus()

# Pending fan-outs per session, flushed on after_commit, dropped on rollback.
_pending: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_hooked = False


def _ensure_commit_hooks() -> None:
    global _hooked
    if _hooked:
        return

    def _after_commit(session):
        evs = _pending.pop(session, None)
        if evs:
            for ev in evs:
                bus.publish(ev.organization_id, ev.topic, ev.payload)

    def _after_rollback(session):
        _pending.pop(session, None)

    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _hooked = True


def publish_outbox(db: Session, org_id: str, topic: str, payload: dict) -> None:
    """Durable record (outbox row) + fan-out DEFERRED until commit."""
    _ensure_commit_hooks()
    db.add(Outbox(organization_id=org_id, topic=topic, payload=payload))
    ev = BusEvent(topic=topic, organization_id=org_id, payload=payload)
    pending = _pending.get(db)
    if pending is None:
        _pending[db] = [ev]
    else:
        pending.append(ev)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def jsonable(payload: dict) -> dict:
    return json.loads(json.dumps(payload, default=str))
