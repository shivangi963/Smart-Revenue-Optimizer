
"""Database engine + session handling (infrastructure only; tables live in models.py)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if _is_sqlite
    else {}
)

# Verify the TiDB Cloud CA certificate and server hostname.
_ca_cert_path = os.getenv("TIDB_CA_CERT_PATH")

if not _is_sqlite and _ca_cert_path:
    if not Path(_ca_cert_path).is_file():
        raise FileNotFoundError(
            f"Database CA certificate not found at {_ca_cert_path!r}"
        )

    _connect_args.update({
        "ssl": {"ca": _ca_cert_path},
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    })

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=True,
    autocommit=False,
    expire_on_commit=False,
)
Base = declarative_base()


def init_db() -> None:
    from . import models

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
