import pytest
from datetime import date, timedelta
from clinic_inventory import db
from clinic_inventory.errors import AppError, PermissionDenied
from clinic_inventory.models import Supplier, Department
from clinic_inventory.money import to_e4
from clinic_inventory.services import catalog, inventory as inv
from .conftest import user

D = date(2026, 10, 1)


def test_supplier_crud_and_validation(env):
    admin = user(env.ids["admin"])
    issuer = user(env.ids["issuer"])

    # Permission check: issuer cannot manage partners
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            catalog.create_supplier(s, issuer, "مورد غير مصرح")

    # Required name validation
    with pytest.raises(AppError):
        with db.session_scope() as s:
            catalog.create_supplier(s, admin, "   ")

    # Create supplier
    with db.session_scope() as s:
        sup = catalog.create_supplier(
            s, admin, "شركة الأمل للمستلزمات",
            phone="01012345678", address="القاهرة - المعادي",
            contact_person="أحمد محمود", notes="توريد دوري"
        )
        sup_id = sup.id
        assert sup.name == "شركة الأمل للمستلزمات"
        assert sup.phone == "01012345678"
        assert sup.active is True

    # Duplicate name validation
    with pytest.raises(AppError):
        with db.session_scope() as s:
            catalog.create_supplier(s, admin, "شركة الأمل للمستلزمات")

    # Search suppliers
    with db.session_scope() as s:
        results = catalog.search_suppliers(s, "الأمل")
        assert len(results) == 1
        assert results[0].id == sup_id

        results_phone = catalog.search_suppliers(s, "01012345678")
        assert len(results_phone) == 1

    # Edit / Update supplier
    with db.session_scope() as s:
        catalog.update_supplier(s, admin, sup_id, phone="01299998888", contact_person="محمد علي")
    with db.session_scope() as s:
        updated = s.get(Supplier, sup_id)
        assert updated.phone == "01299998888"
        assert updated.contact_person == "محمد علي"

    # Deactivate / reactivate
    with db.session_scope() as s:
        catalog.set_supplier_active(s, admin, sup_id, False)
    with db.session_scope() as s:
        assert s.get(Supplier, sup_id).active is False
        assert len(catalog.search_suppliers(s, "الأمل", active_only=True)) == 0
        assert len(catalog.search_suppliers(s, "الأمل", active_only=False)) == 1

    # Delete unreferenced supplier succeeds
    with db.session_scope() as s:
        catalog.delete_supplier(s, admin, sup_id)
    with db.session_scope() as s:
        assert s.get(Supplier, sup_id) is None


def test_supplier_deletion_protected_when_referenced_and_history(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    sup_id = env.ids["sup"]

    # Record purchase incoming
    with db.session_scope() as s:
        doc = inv.create_incoming(
            s, keeper, "purchase", D,
            [dict(item_id=env.ids["item"], quantity=20, unit_cost=to_e4(10))],
            supplier_id=sup_id, reference="INV-100"
        )
        inv.confirm_incoming(s, keeper, doc.id, paid_now=to_e4(50))
        doc_id = doc.id

    # Check supplier history
    with db.session_scope() as s:
        history = catalog.get_supplier_history(s, sup_id)
        assert len(history) == 1
        h = history[0]
        assert h["id"] == doc_id
        assert h["total_cost"] == to_e4(200)
        assert h["paid"] == to_e4(50)
        assert h["outstanding"] == to_e4(150)

    # Attempting to delete supplier with transactions MUST fail
    with pytest.raises(AppError) as excinfo:
        with db.session_scope() as s:
            catalog.delete_supplier(s, admin, sup_id)
    assert "لا يمكن حذف المورد" in str(excinfo.value)


def test_department_crud_and_validation(env):
    admin = user(env.ids["admin"])

    # Required name validation
    with pytest.raises(AppError):
        with db.session_scope() as s:
            catalog.create_department(s, admin, "   ")

    # Create department
    with db.session_scope() as s:
        dept = catalog.create_department(
            s, admin, "عيادة الأسنان",
            dept_type="عيادة تخصصية", doctor="د. هاني",
            notes="الدور الثاني", location="مبنى أ"
        )
        dept_id = dept.id
        assert dept.name == "عيادة الأسنان"
        assert dept.doctor == "د. هاني"
        assert dept.active is True

    # Duplicate name validation
    with pytest.raises(AppError):
        with db.session_scope() as s:
            catalog.create_department(s, admin, "عيادة الأسنان")

    # Search
    with db.session_scope() as s:
        res = catalog.search_departments(s, "الأسنان")
        assert len(res) == 1
        assert res[0].id == dept_id

    # Update
    with db.session_scope() as s:
        catalog.update_department(s, admin, dept_id, doctor="د. إبراهيم", notes="تم التعديل")
    with db.session_scope() as s:
        updated = s.get(Department, dept_id)
        assert updated.doctor == "د. إبراهيم"
        assert updated.notes == "تم التعديل"

    # Deactivate
    with db.session_scope() as s:
        catalog.set_department_active(s, admin, dept_id, False)
    with db.session_scope() as s:
        assert s.get(Department, dept_id).active is False
        assert len(catalog.search_departments(s, "الأسنان", active_only=True)) == 0

    # Delete unreferenced department
    with db.session_scope() as s:
        catalog.delete_department(s, admin, dept_id)
    with db.session_scope() as s:
        assert s.get(Department, dept_id) is None


def test_department_issue_history_and_deletion_protection(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])
    dept_id = env.ids["dept"]

    # Stock items
    with db.session_scope() as s:
        doc = inv.create_incoming(
            s, keeper, "donation", D,
            [dict(item_id=env.ids["item"], quantity=50, unit_cost=to_e4(5))]
        )
        inv.confirm_incoming(s, keeper, doc.id)

    # Issue to department
    with db.session_scope() as s:
        iss = inv.create_issue(
            s, issuer, dept_id,
            [dict(item_id=env.ids["item"], quantity=15)],
            recipient="د. أحمد"
        )
        iss_id = iss.id

    # Department issue history
    with db.session_scope() as s:
        history = catalog.get_department_issue_history(s, dept_id)
        assert len(history) == 1
        assert history[0]["id"] == iss_id
        assert history[0]["recipient"] == "د. أحمد"
        assert history[0]["total_qty"] == 15
        assert history[0]["total_cost"] == to_e4(75)

    # Department consumption summary for date period
    with db.session_scope() as s:
        summary = catalog.get_department_consumption_summary(s, dept_id, D, D + timedelta(days=10))
        assert summary["issued_qty"] == 15
        assert summary["issue_cost"] == to_e4(75)
        assert summary["net_qty"] == 15
        assert summary["net_cost"] == to_e4(75)

    # Attempting to delete department with issue history MUST fail
    with pytest.raises(AppError) as excinfo:
        with db.session_scope() as s:
            catalog.delete_department(s, admin, dept_id)
    assert "لا يمكن حذف العيادة أو القسم" in str(excinfo.value)


def test_suppliers_and_departments_ui_pages(env):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from clinic_inventory.ui.suppliers_page import SuppliersPage, SupplierHistoryDialog
    from clinic_inventory.ui.departments_page import DepartmentsPage, DepartmentHistoryDialog

    app = QApplication.instance() or QApplication([])
    admin = user(env.ids["admin"])

    class DummyWin:
        def __init__(self, u):
            self.user = u
        def poll(self): pass
        def after_stock_change(self): pass

    win = DummyWin(admin)

    # Suppliers Page
    sp = SuppliersPage(win)
    sp.refresh()
    assert sp.t is not None
    assert sp.t.rowCount() >= 1

    # Search filter
    sp.q.setText("الشفاء")
    sp.refresh()
    assert sp.t.rowCount() >= 1

    # Supplier History Dialog
    sh_dlg = SupplierHistoryDialog(sp, env.ids["sup"], "مورد الشفاء")
    assert sh_dlg.windowTitle() != ""

    # Departments Page
    dp = DepartmentsPage(win)
    dp.refresh()
    assert dp.t is not None
    assert dp.t.rowCount() >= 1

    # Search filter
    dp.q.setText("الباطنة")
    dp.refresh()
    assert dp.t.rowCount() >= 1

    # Department History Dialog
    dh_dlg = DepartmentHistoryDialog(dp, env.ids["dept"], "عيادة الباطنة")
    assert dh_dlg.windowTitle() != ""
