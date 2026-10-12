import pytest
from datetime import date, timedelta
from clinic_inventory import db
from clinic_inventory.errors import AppError, PermissionDenied
from clinic_inventory.models import Batch, StockMovement, ReturnRecord, DamageRecord, StocktakeSession
from clinic_inventory.money import to_e4
from clinic_inventory.services import catalog, inventory as inv
from .conftest import user

D = date(2026, 10, 1)


def test_returns_eligible_qty_and_fifo_cost_preservation(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Stock 2 batches: 10 @ cost 5, then 10 @ cost 8
    with db.session_scope() as s:
        d1 = inv.create_incoming(s, keeper, "purchase", D,
                                 [dict(item_id=env.ids["item"], quantity=10, unit_cost=to_e4(5))],
                                 supplier_id=env.ids["sup"])
        inv.confirm_incoming(s, keeper, d1.id)

        d2 = inv.create_incoming(s, keeper, "purchase", D + timedelta(days=1),
                                 [dict(item_id=env.ids["item"], quantity=10, unit_cost=to_e4(8))],
                                 supplier_id=env.ids["sup"])
        inv.confirm_incoming(s, keeper, d2.id)

    # Issue 15 items: will consume 10 @ 5, and 5 @ 8
    with db.session_scope() as s:
        iss = inv.create_issue(s, issuer, env.ids["dept"],
                               [dict(item_id=env.ids["item"], quantity=15)],
                               recipient="د. أحمد")
        iss_id = iss.id
        line_id = iss.lines[0].id

    # Check eligible docs query
    with db.session_scope() as s:
        docs = inv.get_issue_docs_for_return(s)
        assert len(docs) >= 1
        found = next(d for d in docs if d["doc_id"] == iss_id)
        assert found["lines"][0]["eligible_qty"] == 15

    # Cannot return more than issued (e.g. 16 > 15)
    with pytest.raises(AppError):
        with db.session_scope() as s:
            inv.record_return(s, issuer, line_id, 16, "reusable")

    # Record return of 3 reusable items
    with db.session_scope() as s:
        ret = inv.record_return(s, issuer, line_id, 3, "reusable", reason="فائض عن الحاجة")
        assert ret.status == "pending"
        ret_id = ret.id

    # Eligible quantity is now 15 - 3 = 12
    with db.session_scope() as s:
        docs = inv.get_issue_docs_for_return(s)
        found = next(d for d in docs if d["doc_id"] == iss_id)
        assert found["lines"][0]["eligible_qty"] == 12

    # Issuer cannot approve return
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            inv.approve_return(s, issuer, ret_id, approve=True)

    # Keeper / Admin approves return:
    # 3 items were consumed from second batch (cost 8), so return must restore batch 2 at cost 8!
    with db.session_scope() as s:
        inv.approve_return(s, keeper, ret_id, approve=True)

    with db.session_scope() as s:
        r = s.get(ReturnRecord, ret_id)
        assert r.status == "approved"
        assert r.cost == to_e4(24)  # 3 * 8 = 24
        # Check that batch remaining_qty increased by 3
        b2 = s.scalars(inv.select(Batch).where(Batch.item_id == env.ids["item"]).order_by(Batch.id.desc())).first()
        # Batch 2 had 10 - 5 = 5 remaining, plus 3 returned = 8
        assert b2.remaining_qty == 8


def test_damaged_supplies_recording_and_authorization(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Stock items
    with db.session_scope() as s:
        doc = inv.create_incoming(s, keeper, "purchase", D,
                                  [dict(item_id=env.ids["item"], quantity=20, unit_cost=to_e4(12))],
                                  supplier_id=env.ids["sup"])
        inv.confirm_incoming(s, keeper, doc.id)
        batch = doc.lines[0].item_id

    with db.session_scope() as s:
        batches = inv.list_batches_for_damage(s, env.ids["item"])
        assert len(batches) >= 1
        b_id = batches[0]["id"]

    # Issuer lacks damage.create permission
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            inv.record_damage(s, issuer, b_id, 2, "damaged")

    # Keeper records damage of 4 items
    with db.session_scope() as s:
        rec = inv.record_damage(s, keeper, b_id, 4, "damaged", reason="كسر أثناء النقل")
        assert rec.quantity == 4
        assert rec.cost == to_e4(48)  # 4 * 12

    with db.session_scope() as s:
        records = inv.list_damage_records(s)
        assert len(records) >= 1
        found = next(r for r in records if r["batch_id"] == b_id)
        assert found["quantity"] == 4
        assert found["cost"] == to_e4(48)


def test_stocktake_lifecycle_shortage_and_surplus(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Stock 10 items
    with db.session_scope() as s:
        d = inv.create_incoming(s, keeper, "purchase", D,
                                [dict(item_id=env.ids["item"], quantity=10, unit_cost=to_e4(15))],
                                supplier_id=env.ids["sup"])
        inv.confirm_incoming(s, keeper, d.id)

    # Issuer cannot manage stocktake
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            inv.start_stocktake(s, issuer)

    # Keeper starts stocktake
    with db.session_scope() as s:
        ss = inv.start_stocktake(s, keeper, item_ids=[env.ids["item"]], notes="جرد تجريبي")
        sid = ss.id
        assert ss.status == "open"
        assert ss.lines[0].book_qty == 10

    # Count with discrepancy requires explanation
    with db.session_scope() as s:
        inv.record_count(s, keeper, sid, env.ids["item"], 8, explanation="")

    # Submitting without explanation MUST raise error
    with pytest.raises(AppError):
        with db.session_scope() as s:
            inv.submit_stocktake(s, keeper, sid)

    # Add explanation and submit
    with db.session_scope() as s:
        inv.record_count(s, keeper, sid, env.ids["item"], 8, explanation="تلف عبوتين بسبب الرطوبة")
        inv.submit_stocktake(s, keeper, sid)

    with db.session_scope() as s:
        sess = s.get(StocktakeSession, sid)
        assert sess.status == "submitted"

    # Keeper cannot approve stocktake (only admin with stocktake.approve)
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            inv.approve_stocktake(s, keeper, sid)

    # Admin approves stocktake
    with db.session_scope() as s:
        inv.approve_stocktake(s, admin, sid)

    with db.session_scope() as s:
        sess = s.get(StocktakeSession, sid)
        assert sess.status == "approved"
        # Book quantity adjusted via FIFO consumption from 10 to 8
        assert inv.onhand_qty(s, env.ids["item"]) == 8


def test_phase2_ui_pages(env):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from clinic_inventory.ui.returns_page import ReturnsPage, NewReturnDialog
    from clinic_inventory.ui.damage_page import DamagePage, RecordDamageDialog
    from clinic_inventory.ui.stocktake_page import StocktakePage, StocktakeCountDialog

    app = QApplication.instance() or QApplication([])
    admin = user(env.ids["admin"])

    class DummyWin:
        def __init__(self, u):
            self.user = u
        def poll(self): pass
        def after_stock_change(self): pass

    win = DummyWin(admin)

    # Returns Page
    rp = ReturnsPage(win)
    rp.refresh()
    assert rp.t is not None

    # Damage Page
    dp = DamagePage(win)
    dp.refresh()
    assert dp.t is not None

    # Stocktake Page
    sp = StocktakePage(win)
    sp.refresh()
    assert sp.t is not None
