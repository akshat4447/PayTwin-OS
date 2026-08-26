"""FastAPI application: health, meta, webhook ingress; routers added per module."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from paytwin_api import __version__
from paytwin_api.auth import AuthError, Principal
from paytwin_api.config import get_settings
from paytwin_api.db import make_engine, make_session_factory
from paytwin_api.deps import current_principal, get_db

settings = get_settings()
engine = make_engine()
SessionLocal = make_session_factory(engine)

app = FastAPI(title="PayTwin OS API", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json")


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


@app.get("/api/meta", tags=["system"])
def meta(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    from paytwin_api.models import Merchant

    merchants = (
        db.query(Merchant)
        .filter(Merchant.organization_id == p.organization_id)
        .order_by(Merchant.created_at)
        .all()
    )
    return {
        "org": p.organization_id,
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
from paytwin_api.reliability.router import router as reliability_router  # noqa: E402

for _r in (overview_router, incidents_router, twin_router, policies_router,
           commander_router, experiments_router, models_router, audit_router,
           reports_router, chaos_router, stream_router, reliability_router):
    app.include_router(_r)


def _mount_web() -> None:
    """Serve the prototype UI (apps/web) at / when present."""
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    if (web / "index.html").exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")


_mount_web()
