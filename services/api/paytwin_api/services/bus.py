"""Transactional outbox + in-process SSE fan-out (Kafka-compatible seam, ADR-003/008)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

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


def publish_outbox(db: Session, org_id: str, topic: str, payload: dict) -> None:
    """Durable record (outbox row) + immediate in-process fan-out."""
    db.add(Outbox(organization_id=org_id, topic=topic, payload=payload))
    bus.publish(org_id, topic, payload)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def jsonable(payload: dict) -> dict:
    return json.loads(json.dumps(payload, default=str))
