import os
import pytest
from datetime import date
from clinic_inventory import db
from clinic_inventory.errors import AppError, PermissionDenied
from clinic_inventory.services import backup, settings
from .conftest import user


def test_backup_and_restore_with_safety_copy(env, tmp_path):
    admin = user(env.ids["admin"])
    issuer = user(env.ids["issuer"])
    dest_dir = str(tmp_path / "backups")
    safety_dir = str(tmp_path / "safety")

    # Issuer lacks backup.manage
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            backup.create_backup(s, issuer, env.path, dest_dir)

    # Admin creates backup
    with db.session_scope() as s:
        bk_path = backup.create_backup(s, admin, env.path, dest_dir, kind="manual")
        assert os.path.exists(bk_path)
        assert backup.verify_backup(bk_path) is True

    # List backups
    with db.session_scope() as s:
        bks = backup.list_backups(s)
        assert len(bks) >= 1
        assert bks[0]["status"] == "ok"

    # Restore backup
    safety = backup.restore_backup(admin, bk_path, env.path, safety_dir, db.get_engine().dispose)
    assert os.path.exists(safety)
    db.init_engine(env.path)


def test_settings_save_and_audit_logging(env):
    admin = user(env.ids["admin"])
    issuer = user(env.ids["issuer"])

    # Issuer lacks settings.manage
    with pytest.raises(PermissionDenied):
        with db.session_scope() as s:
            settings.save_settings(s, issuer, {"app_name": "اختراق"})

    # Admin saves settings
    with db.session_scope() as s:
        settings.save_settings(s, admin, {
            "app_name": "مجمع عيادات الشفاء التخصصي",
            "default_min_stock": "25",
            "currency_symbol": "ج.م"
        })

    with db.session_scope() as s:
        all_s = settings.get_all_settings(s)
        assert all_s["app_name"] == "مجمع عيادات الشفاء التخصصي"
        assert all_s["default_min_stock"] == "25"
        assert all_s["currency_symbol"] == "ج.م"

    # Check audit log
    with db.session_scope() as s:
        logs = settings.list_audit_logs(s, action="update_settings")
        assert len(logs) >= 1
        assert "مجمع عيادات الشفاء التخصصي" in logs[0]["new_value"]


def test_phase4_ui_pages(env):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from clinic_inventory.ui.backup_page import BackupPage
    from clinic_inventory.ui.settings_page import SettingsPage

    app = QApplication.instance() or QApplication([])
    admin = user(env.ids["admin"])

    class DummyWin:
        def __init__(self, u):
            self.user = u
        def poll(self): pass
        def after_stock_change(self): pass

    win = DummyWin(admin)

    bp = BackupPage(win)
    bp.refresh()
    assert bp.t is not None

    sp = SettingsPage(win)
    sp.refresh()
    assert sp.audit_table is not None
    assert sp.app_name_edit.text() != ""
