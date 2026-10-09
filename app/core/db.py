"""Database engine and per-request sessions (SQLAlchemy 2, Postgres).

Client separation lives in the database: every client table has row-level security, and each transaction
tells Postgres which client it is working for (`app.tenant_id`) or that it is platform work (`app.platform`).
Both are set with SET LOCAL semantics, so they end with the transaction and can't leak to the next request
that reuses the pooled connection.
"""

from collections.abc import Iterator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _set_scope(session: Session, _transaction, connection) -> None:
    """Every transaction starts by saying whose data it may see. With neither setting, it sees no client rows."""
    tenant_id = session.info.get("tenant_id")
    platform = session.info.get("platform", False)
    connection.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.platform', :p, true)"),
        {"t": str(tenant_id) if tenant_id else "", "p": "on" if platform else "off"},
    )


def scoped_session(tenant_id: UUID | None = None, platform: bool = False) -> Session:
    """A session for one client (tenant_id) or for platform work across clients (platform=True)."""
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    db.info["platform"] = platform
    return db


def get_db(request: Request) -> Iterator[Session]:
    """One session per request, scoped to the client this request's address belongs to.
    Commits if the request succeeded; rolls back on any error."""
    tenant = getattr(request.state, "tenant", None)
    db = scoped_session(tenant.id if tenant else None, platform=bool(getattr(request.state, "is_platform", False)))
    try:
        yield db
        if db.new or db.dirty or db.deleted or db.info.get("wrote"):
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@event.listens_for(Session, "after_flush")
def _note_write(session, _ctx):
    session.info["wrote"] = True


# The commit must finish before the response is sent, so a failed commit becomes an error the person sees
# instead of a "Saved" message for something that wasn't. "function" scope closes the dependency as soon as
# the endpoint is done, before the response goes out.
DB = Depends(get_db, scope="function")


def is_transient(exc: BaseException) -> bool:
    """Errors that mean "try again in a moment": the database restarting or a dropped connection."""
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    return isinstance(exc, OperationalError)
