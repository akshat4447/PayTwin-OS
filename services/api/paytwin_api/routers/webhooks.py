"""Webhook ingress routes (HMAC-authenticated, provider-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from paytwin_api.deps import get_db
from paytwin_api.services.ingest import ingest_webhook

router = APIRouter()


@router.post("/webhooks/{provider}", tags=["ingest"])
async def webhook(provider: str, request: Request, merchant: str,
                  db: Session = Depends(get_db)) -> Response:
    body = await request.body()
    signature = (request.headers.get("x-paytwin-signature")
                 or request.headers.get("x-razorpay-signature") or "")
    res = ingest_webhook(db, provider, merchant, body, signature)
    return Response(content=_json(res.body), status_code=res.status,
                    media_type="application/json")


def _json(d: dict) -> str:
    import json

    return json.dumps(d)

