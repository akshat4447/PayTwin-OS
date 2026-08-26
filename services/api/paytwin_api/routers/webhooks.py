"""Webhook ingress routes (HMAC-authenticated, provider-scoped)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from paytwin_api.deps import get_db
from paytwin_api.services.ingest import ingest_webhook

router = APIRouter()

MAX_WEBHOOK_BYTES = 1_000_000  # 1 MB — oversized bodies are rejected unread


@router.post("/webhooks/{provider}", tags=["ingest"])
async def webhook(provider: str, request: Request, merchant: str,
                  db: Session = Depends(get_db)) -> Response:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        return Response(content=json.dumps(
            {"error": {"code": "payload_too_large",
                       "message": f"webhook body exceeds {MAX_WEBHOOK_BYTES} bytes"}}),
            status_code=413, media_type="application/json")
    signature = (request.headers.get("x-paytwin-signature")
                 or request.headers.get("x-razorpay-signature") or "")
    headers = {k.lower(): v for k, v in request.headers.items()}
    res = ingest_webhook(db, provider, merchant, body, signature, headers=headers)
    return Response(content=_json(res.body), status_code=res.status,
                    media_type="application/json")


def _json(d: dict) -> str:
    return json.dumps(d)

