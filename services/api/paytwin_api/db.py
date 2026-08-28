"""SQLAlchemy engine/session + declarative base with portable naming convention."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from paytwin_api.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session, transaction, connection) -> None:
    """Re-apply PostgreSQL RLS scope for every transaction in this session."""
    org = session.info.get("paytwin.organization_id")
    if org and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('app.current_org', :org, true)"),
                           {"org": org})


def make_engine(url: str | None = None):
    s = get_settings()
    url = url or s.database_url
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)


def make_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def set_tenant_context(session: Session, organization_id: str) -> None:
    """Bind a request session to one org for PostgreSQL RLS.

    ``SET LOCAL`` is transaction-scoped, so the session event above repeats it
    after endpoint commits. SQLite intentionally remains a no-op for tests.
    """
    session.info["paytwin.organization_id"] = organization_id
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.current_org', :org, true)"),
                        {"org": organization_id})


@contextmanager
def session_scope(factory: sessionmaker) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
