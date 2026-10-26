"""Database engine/session setup (SQLite by default, PostgreSQL-ready)."""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .orm import Base

_connect_args = {}
if settings.db_url.startswith("sqlite"):
    # Ensure the SQLite data directory exists (path is relative to backend/).
    path = settings.db_url.split("///", 1)[-1]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    _connect_args = {"check_same_thread": False}

engine = create_engine(settings.db_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate(engine)


def _migrate(eng) -> None:
    """Tiny in-place migrations for columns added after initial deployment."""
    from sqlalchemy import inspect, text

    inspector = inspect(eng)
    pf_cols = {c["name"] for c in inspector.get_columns("point_forecasts")}
    if "origin" not in pf_cols:
        with eng.begin() as conn:
            conn.execute(text(
                "ALTER TABLE point_forecasts ADD COLUMN origin VARCHAR(16) DEFAULT 'live'"
            ))


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def bulk_insert_ignore(session, table, rows: list[dict]) -> int:
    """Insert rows, silently skipping unique-constraint duplicates.

    Supports SQLite and PostgreSQL dialects.
    """
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(table).on_conflict_do_nothing()
    session.execute(stmt, rows)
    # executemany results don't reliably expose rowcount; report attempted rows.
    return len(rows)
