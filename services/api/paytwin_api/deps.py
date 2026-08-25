"""Shared FastAPI dependencies (kept import-cycle-free)."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from paytwin_api.auth import AuthError, Principal, resolve_principal

_SessionLocal = None


def get_db():
    """Request-scoped session. Built lazily here (not imported from paytwin_api.main)
    to keep the main<->deps import cycle broken."""
    global _SessionLocal
    if _SessionLocal is None:
        from paytwin_api.db import make_engine, make_session_factory

        _SessionLocal = make_session_factory(make_engine())
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    return resolve_principal(db, request.headers.get("authorization"))


def require_write(p: Principal) -> Principal:
    if not p.can_write:
        raise AuthError("forbidden_role", status=403)
    return p


def require_admin(p: Principal) -> Principal:
    if not p.is_admin:
        raise AuthError("forbidden_role", status=403)
    return p


def err(status: int, code: str, message: str = ""):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})
