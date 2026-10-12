import os
import glob
import sqlite3
import pytest
from sqlalchemy import select
from clinic_inventory import bootstrap, db
from clinic_inventory.models import Setting, Item, Batch, StockMovement
from clinic_inventory.money import to_e4
from clinic_inventory.services import auth, catalog, inventory as inv
from .conftest import user


def test_database_upgrade_migration_and_safety_backup(tmp_path):
    db_file = str(tmp_path / "upgrade_test.db")

    # Step 1: Create database at Version 1 manually
    engine = db.init_engine(db_file)
    with engine.begin() as conn:
        bootstrap.Base.metadata.create_all(conn)

    with db.session_scope() as s:
        # Set version 1
        s.add(Setting(key="schema_version", value="1"))
        auth.seed_roles(s)
        admin = auth.create_user(s, None, "admin1", "المدير", "secret1", "مدير النظام")
        keeper = auth.create_user(s, admin, "keeper1", "الأمين", "secret1", "أمين المخزن")
        item = catalog.create_item(s, admin, "خافض لسان خشبي", "علبة")
        sup = catalog.create_supplier(s, admin, "مورد النيل")
        doc = inv.create_incoming(s, keeper, "purchase", inv.date(2026, 10, 1),
                                  [dict(item_id=item.id, quantity=50, unit_cost=to_e4(3))],
                                  supplier_id=sup.id)
        inv.confirm_incoming(s, keeper, doc.id)

    db.get_engine().dispose()

    # Step 2: Run upgrade through init_database
    # bootstrap.SCHEMA_VERSION is 2
    assert bootstrap.SCHEMA_VERSION == 2

    # Verify existing file size > 0
    assert os.path.exists(db_file)
    assert os.path.getsize(db_file) > 0

    # Call init_database to perform upgrade
    upgraded_engine = bootstrap.init_database(db_file)

    # Step 3: Verify safety backup .bak was created
    bak_files = glob.glob(f"{db_file}.pre-v2-*.bak")
    assert len(bak_files) >= 1
    assert os.path.getsize(bak_files[0]) > 0

    # Step 4: Verify schema version is now 2
    with db.session_scope() as s:
        v = s.get(Setting, "schema_version")
        assert v.value == "2"

        # Step 5: Verify existing inventory data is 100% preserved
        it = s.scalar(select(Item).where(Item.name == "خافض لسان خشبي"))
        assert it is not None
        assert it.code == "IT-00001"

        b = s.scalar(select(Batch).where(Batch.item_id == it.id))
        assert b is not None
        assert b.remaining_qty == 50
        assert b.unit_cost == to_e4(3)

        m = s.scalar(select(StockMovement).where(StockMovement.item_id == it.id))
        assert m is not None
        assert m.qty_delta == 50

    # Step 6: Verify new indexes from migration_v2 exist in sqlite master
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_movements_kind_date'")
    idx1 = cur.fetchone()
    assert idx1 is not None

    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_payments_doc_date'")
    idx2 = cur.fetchone()
    assert idx2 is not None
    conn.close()
