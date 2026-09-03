"""FastAPI application: health, meta, webhook ingress; routers added per module."""
from __future__ import annotations

import json
import hashlib
import time
import uuid
from collections import OrderedDict, deque
from pathlib import Path

from fastapi import FastAPI, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from paytwin_api import __version__
from paytwin_api.auth import (AuthError, Principal, WORKSPACE_SESSION_COOKIE,
                              issue_workspace_session)
from paytwin_api.config import get_settings
from paytwin_api.db import make_engine, make_session_factory
from paytwin_api.deps import current_principal, get_db

settings = get_settings()
settings.validate_for_env()  # fail fast on unsafe production configuration
engine = make_engine()
SessionLocal = make_session_factory(engine)

app = FastAPI(title="PayTwin OS API", version=__version__,
              docs_url=None if settings.is_prod else "/api/docs",
              openapi_url=None if settings.is_prod else "/api/openapi.json")


class RequestMetrics:
    """Small dependency-free Prometheus exposition for staging operations."""

    def __init__(self):
        self.requests = 0
        self.errors = 0
        self.duration_seconds = 0.0

    def render(self) -> str:
        return "\n".join([
            "# HELP paytwin_http_requests_total Total HTTP requests handled",
            "# TYPE paytwin_http_requests_total counter",
            f"paytwin_http_requests_total {self.requests}",
            "# HELP paytwin_http_errors_total HTTP responses with status >= 500",
            "# TYPE paytwin_http_errors_total counter",
            f"paytwin_http_errors_total {self.errors}",
            "# HELP paytwin_http_request_duration_seconds_sum Aggregate request duration",
            "# TYPE paytwin_http_request_duration_seconds_sum counter",
            f"paytwin_http_request_duration_seconds_sum {self.duration_seconds:.6f}",
            "",
        ])


metrics = RequestMetrics()


class SecurityAndObservabilityMiddleware:
    """Adds correlation/security headers without logging or retaining credentials."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        supplied = next((v.decode() for k, v in scope.get("headers", [])
                         if k.lower() == b"x-request-id"), "")
        request_id = supplied if 8 <= len(supplied) <= 80 and supplied.replace("-", "").isalnum() \
            else uuid.uuid4().hex

        async def secured_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"content-security-policy",
                     b"default-src 'self'; img-src 'self' data:; "
                     b"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                     b"font-src 'self' https://fonts.gstatic.com; "
                     b"script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                     b"base-uri 'self'; frame-ancestors 'none'"),
                ])
                # The SPA is a single, actively-edited index.html with no build
                # step or cache-busted filename; without an explicit directive
                # a browser can silently keep serving a stale copy after a fix.
                if scope.get("path") == "/":
                    headers.append((b"cache-control", b"no-cache"))
                status = int(message["status"])
                metrics.requests += 1
                if status >= 500:
                    metrics.errors += 1
                metrics.duration_seconds += max(0.0, time.perf_counter() - started)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, secured_send)


class RateLimitMiddleware:
    """Sliding-window per-identity limiter on /api/* (settings.rate_limit_per_min).

    Identity = bearer credential when present, else client host. Webhook ingress
    (/webhooks/*) and /api/health are exempt: machine traffic is HMAC-authed and
    bursty by design. Pure ASGI middleware — safe for SSE streaming.
    """

    def __init__(self, app, limit: int = 240):
        self.app = app
        self.limit = max(0, int(limit))
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._max_identities = 10_000

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or self.limit <= 0
                or not scope["path"].startswith("/api/")
                or scope["path"] == "/api/health"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        raw_ident = headers.get("authorization", "") or (
            scope.get("client", ("?", 0))[0] if scope.get("client") else "?")
        # Do not retain bearer tokens in a long-lived in-process dict. A stable
        # hash keeps the per-credential limiter behavior without credential
        # exposure through memory inspection/debugging.
        ident = hashlib.sha256(raw_ident.encode()).hexdigest()
        now = time.monotonic()
        window = self._hits.get(ident)
        if window is None:
            if len(self._hits) >= self._max_identities:
                self._hits.popitem(last=False)
            window = deque()
            self._hits[ident] = window
        else:
            self._hits.move_to_end(ident)
        while window and window[0] <= now - 60.0:
            window.popleft()
        if len(window) >= self.limit:
            body = json.dumps({"error": {"code": "rate_limited",
                                         "message": "too many requests"}}).encode()
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode()),
                                    (b"retry-after", b"60")]})
            await send({"type": "http.response.body", "body": body})
            return
        window.append(now)
        await self.app(scope, receive, send)


app.add_middleware(RateLimitMiddleware, limit=settings.rate_limit_per_min)
app.add_middleware(SecurityAndObservabilityMiddleware)


@app.exception_handler(AuthError)
async def _auth_error(request: Request, exc: AuthError):
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": "unauthorized"}})


@app.get("/api/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    from sqlalchemy import text

    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok,
            "version": __version__, "env": settings.env}


@app.get("/api/ready", tags=["system"])
def readiness(db: Session = Depends(get_db)):
    """Deployment readiness: database must be queryable before traffic is sent."""
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "db": False})
    return {"status": "ready", "db": True, "env": settings.env}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/api/meta", tags=["system"])
def meta(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    from paytwin_api.models import Merchant, Organization

    merchants = (
        db.query(Merchant)
        .filter(Merchant.organization_id == p.organization_id)
        .order_by(Merchant.created_at)
        .all()
    )
    org = db.query(Organization).filter(Organization.id == p.organization_id).one_or_none()
    return {
        "org": p.organization_id,
        "org_name": org.name if org is not None else p.organization_id,
        "role": p.role,
        "merchants": [
            {"id": m.id, "name": m.name, "short": m.short_code, "color": m.color,
             "mode": f"Mode {m.autonomy_mode}", "stage": m.stage,
             "sr_base": m.sr_base_bp / 100, "gmv": m.gmv_mtd_paise,
             "protected": m.protected_mtd_paise}
            for m in merchants
        ],
        "feature_flags": {"llm": settings.llm_provider, "env": settings.env},
    }


@app.post("/api/workspace/session", tags=["system"])
def establish_workspace_session(response: Response,
                                p: Principal = Depends(current_principal)):
    """Exchange an entered bearer key for a same-origin HttpOnly workspace session.

    The raw key is never stored in browser URL, local/session storage, or the
    cookie itself.  Browser refreshes retain the signed session until expiry.
    """
    response.set_cookie(
        key=WORKSPACE_SESSION_COOKIE,
        value=issue_workspace_session(p, settings.secret_key),
        max_age=settings.workspace_session_ttl_seconds,
        httponly=True,
        secure=settings.is_prod,
        samesite="strict",
        path="/",
    )
    return {"connected": True, "expires_in_seconds": settings.workspace_session_ttl_seconds}


# Webhook ingress (HMAC-authenticated, not bearer-authenticated)
from paytwin_api.routers.webhooks import router as webhooks_router  # noqa: E402

app.include_router(webhooks_router)

# API routers (bearer-authenticated, tenant-filtered)
from paytwin_api.routers.overview import router as overview_router  # noqa: E402
from paytwin_api.routers.incidents import router as incidents_router  # noqa: E402
from paytwin_api.routers.twin import router as twin_router  # noqa: E402
from paytwin_api.routers.policies import router as policies_router  # noqa: E402
from paytwin_api.routers.commander import router as commander_router  # noqa: E402
from paytwin_api.routers.experiments import router as experiments_router  # noqa: E402
from paytwin_api.routers.models import router as models_router  # noqa: E402
from paytwin_api.routers.audit import router as audit_router  # noqa: E402
from paytwin_api.routers.reports import router as reports_router  # noqa: E402
from paytwin_api.routers.chaos import router as chaos_router  # noqa: E402
from paytwin_api.routers.stream import router as stream_router  # noqa: E402
from paytwin_api.routers.integrations import router as integrations_router  # noqa: E402
from paytwin_api.routers.checkout import router as checkout_router  # noqa: E402
from paytwin_api.routers.operations import router as operations_router  # noqa: E402
from paytwin_api.routers.razorpay import router as razorpay_router  # noqa: E402
from paytwin_api.reliability.router import router as reliability_router  # noqa: E402

for _r in (overview_router, incidents_router, twin_router, policies_router,
           commander_router, experiments_router, models_router, audit_router,
           reports_router, chaos_router, stream_router, integrations_router,
           checkout_router, operations_router, reliability_router):
    app.include_router(_r)

app.include_router(razorpay_router)


def _mount_web() -> None:
    """Serve the prototype UI (apps/web) at / when present."""
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    if (web / "index.html").exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")


_mount_web()
