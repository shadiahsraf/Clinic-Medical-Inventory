import pytest
from datetime import date
from clinic_inventory import db
from clinic_inventory.errors import AppError, PermissionDenied
from clinic_inventory.models import SupplierPayment, CashMovement, User, AuditLog
from clinic_inventory.money import to_e4
from clinic_inventory.permissions import ROLE_ADMIN, ROLE_KEEPER, ROLE_ISSUER
from clinic_inventory.services import auth, inventory as inv
from .conftest import user

D = date(2026, 10, 1)


def test_supplier_payment_lifecycle_and_guards(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Stock items via purchase: 10 @ cost 20 = 200 EGP total
    with db.session_scope() as s:
        doc = inv.create_incoming(s, keeper, "purchase", D,
                                  [dict(item_id=env.ids["item"], quantity=10, unit_cost=to_e4(20))],
                                  supplier_id=env.ids["sup"], reference="INV-555")
        inv.confirm_incoming(s, keeper, doc.id)
        doc_id = doc.id

    # Check outstanding
    with db.session_scope() as s:
        d = s.get(inv.IncomingDoc, doc_id)
        assert inv.outstanding(s, d) == to_e4(200)
        unpaid = inv.get_unpaid_purchase_docs(s, env.ids["sup"])
        assert len(unpaid) >= 1
        assert unpaid[0]["outstanding"] == to_e4(200)

    # Issuer cannot record payments
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            inv.record_payment(s, issuer, doc_id, to_e4(50), D)

    # Cannot pay 0 or negative
    with pytest.raises(AppError):
        with db.session_scope() as s:
            inv.record_payment(s, keeper, doc_id, 0, D)

    # Cannot pay more than outstanding (e.g. 250 > 200)
    with pytest.raises(AppError):
        with db.session_scope() as s:
            inv.record_payment(s, keeper, doc_id, to_e4(250), D)

    # Record partial payment: 80 EGP
    with db.session_scope() as s:
        p = inv.record_payment(s, keeper, doc_id, to_e4(80), D, method="شيك بنكي", notes="دفعة أولى")
        assert p.amount == to_e4(80)

    # Outstanding is now 120 EGP
    with db.session_scope() as s:
        d = s.get(inv.IncomingDoc, doc_id)
        assert inv.outstanding(s, d) == to_e4(120)
        # Check cash movement was logged
        cm = s.scalars(inv.select(CashMovement).where(CashMovement.ref_id == doc_id)).first()
        assert cm is not None
        assert cm.amount == -to_e4(80)

    # Record remaining payment: 120 EGP
    with db.session_scope() as s:
        inv.record_payment(s, keeper, doc_id, to_e4(120), D, method="نقدي")

    # Outstanding is now 0; doc no longer in unpaid list
    with db.session_scope() as s:
        d = s.get(inv.IncomingDoc, doc_id)
        assert inv.outstanding(s, d) == 0
        unpaid = inv.get_unpaid_purchase_docs(s, env.ids["sup"])
        assert not any(u["doc_id"] == doc_id for u in unpaid)

    # Any further payment attempt MUST be rejected
    with pytest.raises(AppError):
        with db.session_scope() as s:
            inv.record_payment(s, keeper, doc_id, to_e4(10), D)


def test_user_management_and_permission_enforcement(env):
    admin = user(env.ids["admin"])
    keeper = user(env.ids["keeper"])
    issuer = user(env.ids["issuer"])

    # Create new user
    with db.session_scope() as s:
        u = auth.create_user(s, admin, "pharmacist1", "صيدلي أول", "strongPass1", ROLE_ISSUER)
        u_id = u.id
        assert u.username == "pharmacist1"
        assert u.password_hash != "strongPass1"  # Not plain text!
        assert "strongPass1" not in u.password_hash

    # Ordinary user (keeper) CANNOT create user
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            auth.create_user(s, keeper, "hacker", "مخترق", "secret123", ROLE_ADMIN)

    # Ordinary user CANNOT grant themselves or others Admin role
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            auth.update_user_role(s, keeper, keeper.id, ROLE_ADMIN)

    # Change password
    with db.session_scope() as s:
        auth.change_password(s, admin, u_id, "newSecretPass2")

    # Login with new password succeeds, old password fails
    with db.session_scope() as s:
        with pytest.raises(AppError):
            auth.login(s, "pharmacist1", "strongPass1")
        logged_in = auth.login(s, "pharmacist1", "newSecretPass2")
        assert logged_in.id == u_id

    # User cannot deactivate themselves
    with pytest.raises(AppError):
        with db.session_scope() as s:
            auth.set_user_active(s, admin, admin.id, False)

    # Admin deactivates pharmacist1
    with db.session_scope() as s:
        auth.set_user_active(s, admin, u_id, False)

    # Deactivated user cannot login
    with db.session_scope() as s:
        with pytest.raises(AppError):
            auth.login(s, "pharmacist1", "newSecretPass2")

    # Check sensitive audit trail
    with db.session_scope() as s:
        trail = auth.get_user_audit_trail(s, u_id)
        assert len(trail) >= 2  # create_user, change_password, set_user_active


def test_phase3_ui_pages(env):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from clinic_inventory.ui.payments_page import SupplierPaymentsPage, RecordPaymentDialog
    from clinic_inventory.ui.users_page import UsersPage, AddUserDialog, ChangePasswordDialog

    app = QApplication.instance() or QApplication([])
    admin = user(env.ids["admin"])

    class DummyWin:
        def __init__(self, u):
            self.user = u
        def poll(self): pass
        def after_stock_change(self): pass

    win = DummyWin(admin)

    # Payments Page
    pp = SupplierPaymentsPage(win)
    pp.refresh()
    assert pp.t is not None

    # Users Page
    up = UsersPage(win)
    up.refresh()
    assert up.t is not None
    assert up.t.rowCount() >= 3
