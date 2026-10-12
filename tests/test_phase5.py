import os
import pytest
from datetime import date, timedelta
from clinic_inventory import db
from clinic_inventory.models import IssueDoc
from clinic_inventory.money import to_e4
from clinic_inventory.services import inventory as inv, reports, exports
from .conftest import user

D = date(2026, 10, 1)


def test_movement_history_and_filters(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Stock items
    with db.session_scope() as s:
        d = inv.create_incoming(s, keeper, "purchase", D,
                                [dict(item_id=env.ids["item"], quantity=20, unit_cost=to_e4(10))],
                                supplier_id=env.ids["sup"])
        inv.confirm_incoming(s, keeper, d.id)

    # Issue items
    with db.session_scope() as s:
        iss = inv.create_issue(s, issuer, env.ids["dept"],
                               [dict(item_id=env.ids["item"], quantity=5)],
                               recipient="د. عائشة")

    with db.session_scope() as s:
        # All movements
        all_movs = reports.query_movement_history(s)
        assert len(all_movs) >= 2

        # Check fields of latest movement (issue)
        issue_mov = next(m for m in all_movs if m["kind"] == "issue")
        assert issue_mov["item_code"] == "IT-00001"
        assert issue_mov["qty_delta"] == -5
        assert issue_mov["unit_cost"] == to_e4(10)
        assert issue_mov["value_delta"] == -to_e4(50)
        assert "عيادة الباطنة" in issue_mov["partner"]
        assert issue_mov["ref_doc"].startswith("OUT-")
        assert issue_mov["user_name"] == "مسؤول الصرف"

        # Check incoming movement
        inc_mov = next(m for m in all_movs if m["kind"] == "incoming")
        assert inc_mov["qty_delta"] == 20
        assert "مورد الشفاء" in inc_mov["partner"]

        # Filter by kind
        filtered_kind = reports.query_movement_history(s, kind="issue")
        assert all(m["kind"] == "issue" for m in filtered_kind)

        # Filter by department
        filtered_dept = reports.query_movement_history(s, department_id=env.ids["dept"])
        assert all(m["partner"] == "عيادة الباطنة" for m in filtered_dept)


def test_issue_voucher_data_and_pdf_export(env, tmp_path):
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Stock & issue
    with db.session_scope() as s:
        d = inv.create_incoming(s, keeper, "purchase", D,
                                [dict(item_id=env.ids["item"], quantity=30, unit_cost=to_e4(7))],
                                supplier_id=env.ids["sup"])
        inv.confirm_incoming(s, keeper, d.id)

        iss = inv.create_issue(s, issuer, env.ids["dept"],
                               [dict(item_id=env.ids["item"], quantity=12)],
                               recipient="د. خالد", reference="طلب قسم 44")
        doc_id = iss.id

    with db.session_scope() as s:
        voucher = reports.get_issue_voucher_data(s, doc_id)
        assert voucher["number"].startswith("OUT-")
        assert voucher["department_name"] == "عيادة الباطنة"
        assert voucher["recipient"] == "د. خالد"
        assert voucher["total_cost"] == to_e4(84)  # 12 * 7
        assert len(voucher["lines"]) == 1
        assert voucher["lines"][0]["quantity"] == 12

    # Export voucher to PDF
    pdf_path = str(tmp_path / "voucher.pdf")
    exports.export_issue_voucher_pdf(pdf_path, voucher)
    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 1000  # Valid non-empty PDF


def test_phase5_ui_page(env):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from clinic_inventory.ui.movement_history_page import MovementHistoryPage

    app = QApplication.instance() or QApplication([])
    admin = user(env.ids["admin"])

    class DummyWin:
        def __init__(self, u):
            self.user = u
        def poll(self): pass
        def after_stock_change(self): pass

    win = DummyWin(admin)

    mhp = MovementHistoryPage(win)
    mhp.refresh()
    assert mhp.t is not None
