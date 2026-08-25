"""Shared pytest fixtures. Sets test env BEFORE any paytwin import."""
from __future__ import annotations

import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ["PAYTWIN_DATABASE_URL"] = f"sqlite:///{_ROOT}/data/test.db"
os.environ["PAYTWIN_ENV"] = "development"
os.environ["PAYTWIN_LLM_PROVIDER"] = "none"
pathlib.Path(_ROOT / "data").mkdir(exist_ok=True)

import pytest  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from paytwin_api.db import Base, make_engine  # noqa: E402
import paytwin_api.models  # noqa: E402,F401


@pytest.fixture()
def db():
    """Fresh schema per test on sqlite; yields a Session."""
    engine = make_engine(os.environ["PAYTWIN_DATABASE_URL"])
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def db_factory():
    """Fresh schema; yields a sessionmaker (for service-layer code)."""
    engine = make_engine(os.environ["PAYTWIN_DATABASE_URL"])
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()
