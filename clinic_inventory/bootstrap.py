"""Schema creation + versioned migrations (lightweight, documented alternative to Alembic:
the app must self-upgrade on a single offline PC, so migrations are plain ordered Python
steps recorded in settings['schema_version'] and are always preceded by a backup)."""
import os, sqlite3, shutil
from datetime import datetime
from sqlalchemy import inspect
from .models import Base, Setting
from . import db
from .services import auth

def migration_v2(conn):
    """Upgrade from Schema v1 to v2:
    - Adds performance indexes on stock movement kinds and supplier payments
    - Preserves all existing records and schema intact
    """
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_movements_kind_date ON stock_movements(kind, move_date)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_payments_doc_date ON supplier_payments(doc_id, pay_date)")


SCHEMA_VERSION = 2
MIGRATIONS: dict[int, callable] = {
    2: migration_v2
}


def init_database(path: str | None = None):
    path = path or db.default_db_path()
    engine = db.init_engine(path)
    existing = os.path.exists(path) and os.path.getsize(path) > 0
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    with db.session_scope() as s:
        row = s.get(Setting, "schema_version")
        cur = int(row.value) if row else 0
        if row is None:
            s.add(Setting(key="schema_version", value=str(SCHEMA_VERSION))); cur = SCHEMA_VERSION
        auth.seed_roles(s)
    if cur < SCHEMA_VERSION:
        if existing:   # safety copy BEFORE touching a real database
            shutil.copyfile(path, f"{path}.pre-v{SCHEMA_VERSION}-{datetime.now():%Y%m%d%H%M%S}.bak")
        with engine.begin() as conn:
            for v in range(cur + 1, SCHEMA_VERSION + 1):
                MIGRATIONS[v](conn)
        with db.session_scope() as s:
            s.get(Setting, "schema_version").value = str(SCHEMA_VERSION)
    return engine
