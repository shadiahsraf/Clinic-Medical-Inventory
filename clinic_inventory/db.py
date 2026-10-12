"""Database engine/session setup (SQLite, FK enforcement, write locking)."""
import os
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

_engine = None
_Session = None


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "ClinicInventory")
    os.makedirs(path, exist_ok=True)
    return path


def default_db_path() -> str:
    return os.path.join(app_data_dir(), "inventory.db")


def make_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi_conn, _):
        dbapi_conn.isolation_level = None  # we control BEGIN ourselves
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()

    @event.listens_for(eng, "begin")
    def _on_begin(conn):
        # Take the write lock up-front: two writers can never interleave
        # allocation of the same batch quantity.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return eng


def init_engine(path: str | None = None):
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(path or default_db_path())
    _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine():
    return _engine


@contextmanager
def session_scope():
    """One transaction per business operation: commit on success, rollback on error."""
    s: Session = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
