"""Webhook ingress: bounded streaming read, opaque integration route, durable ack."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.deps import get_db
from paytwin_api.models import Integration
from paytwin_api.services.ingest import IngestResult, accept_webhook

router = APIRouter()

MAX_WEBHOOK_BYTES = 1_000_000


async def _read_bounded(request: Request) -> bytes | None:
    """Reject oversized bodies while streaming rather than after buffering all."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BYTES:
                return None
        except ValueError:
            return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_WEBHOOK_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _signature(request: Request) -> str:
    return (request.headers.get("x-paytwin-signature")
            or request.headers.get("x-razorpay-signature") or "")


def _response(result: IngestResult) -> Response:
    return Response(content=json.dumps(result.body), status_code=result.status,
                    media_type="application/json")


def _oversize_response() -> Response:
    return Response(content=json.dumps({"error": {"code": "payload_too_large",
                                                    "message": "webhook body exceeds limit"}}),
                    status_code=413, media_type="application/json")


@router.post("/webhooks/{provider}/{route_token}", tags=["ingest"])
async def routed_webhook(provider: str, route_token: str, request: Request,
                         db: Session = Depends(get_db)) -> Response:
    """Preferred provider route: opaque token resolves one tenant integration."""
    integration = (db.query(Integration)
                   .filter(Integration.provider == provider,
                           Integration.webhook_route_token == route_token)
                   .one_or_none())
    if integration is None:
        # Do not reveal which merchant/integration may exist at a guessed URL.
        return Response(status_code=404)
    body = await _read_bounded(request)
    if body is None:
        return _oversize_response()
    headers = {k.lower(): v for k, v in request.headers.items()}
    return _response(accept_webhook(db, provider, integration.merchant_id, body,
                                    _signature(request), headers=headers))


@router.post("/webhooks/{provider}", tags=["ingest"], deprecated=True)
async def legacy_webhook(provider: str, request: Request, merchant: str,
                         db: Session = Depends(get_db)) -> Response:
    """Temporary local-development compatibility route.

    A real provider configuration must use the opaque route above. This seam
    keeps existing local scripts working while preventing query routing in prod.
    """
    if get_settings().is_prod:
        return Response(content=json.dumps({"error": {"code": "legacy_route_disabled",
                                                        "message": "use the integration webhook path"}}),
                        status_code=410, media_type="application/json")
    body = await _read_bounded(request)
    if body is None:
        return _oversize_response()
    headers = {k.lower(): v for k, v in request.headers.items()}
    response = _response(accept_webhook(db, provider, merchant, body,
                                        _signature(request), headers=headers))
    response.headers["Deprecation"] = "true"
    return response
