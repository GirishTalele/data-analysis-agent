from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        from config.settings import get_settings
        database_url = get_settings().database_url
        is_sqlite = database_url.startswith("sqlite")
        connect_args: dict = {}
        if is_sqlite:
            # SQLite defaults to a 0s busy timeout, so a concurrent writer
            # fails immediately with "database is locked". Make writers queue.
            connect_args = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(database_url, echo=False, connect_args=connect_args)

        if is_sqlite:
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA busy_timeout=30000;")
                finally:
                    cursor.close()
    return _engine


def _get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    with _get_session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


@contextmanager
def create_db_session() -> Generator[Session, None, None]:
    """Standalone — for graph nodes, CLI, scripts."""
    with _get_session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def init_db() -> None:
    from db.models import Base
    Base.metadata.create_all(bind=_get_engine())
