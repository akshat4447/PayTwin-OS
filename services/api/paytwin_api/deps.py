"""Shared FastAPI dependencies (kept import-cycle-free)."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from paytwin_api.auth import AuthError, Principal, resolve_principal
from paytwin_api.main import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    return resolve_principal(db, request.headers.get("authorization"))
