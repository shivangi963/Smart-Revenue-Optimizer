"""Database engine + session handling (infrastructure only; tables live in models.py)."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **({"connect_args": {"check_same_thread": False, "timeout": 30}} if _is_sqlite else {}),
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the scheduler's writes
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=True, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables on Base)

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """For background jobs: commit on success, rollback on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
