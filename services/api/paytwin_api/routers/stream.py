"""SSE stream: per-org fan-out of incident/action/policy_decision/metric events."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, get_db
from paytwin_api.services.bus import bus

router = APIRouter(tags=["stream"])


async def _gen(org_id: str):
    q = bus.subscribe(org_id)
    try:
        yield f"event: heartbeat\ndata: {json.dumps({'ok': True})}\n\n"
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15.0)
                yield (f"event: {ev.topic}\n"
                       f"data: {json.dumps(ev.payload, default=str)}\n\n")
            except asyncio.TimeoutError:
                yield f"event: heartbeat\ndata: {json.dumps({'ts': 'tick'})}\n\n"
    finally:
        bus.unsubscribe(org_id, q)


@router.get("/api/stream")
def stream(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return StreamingResponse(_gen(p.organization_id),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})