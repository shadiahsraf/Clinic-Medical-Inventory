import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from datetime import date
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from clinic_inventory import db
from clinic_inventory.services import inventory as inv, catalog
from clinic_inventory.money import to_e4
from clinic_inventory.ui.app import MainWindow, STYLE
from .conftest import user


def test_ui_builds_rtl_and_pages_refresh(env, tmp_path):
    app = QApplication.instance() or QApplication([]); app.setLayoutDirection(Qt.RightToLeft); app.setStyleSheet(STYLE)
    from PySide6.QtGui import QFontDatabase, QFont
    fd = os.path.join(os.path.dirname(__file__), "..", "clinic_inventory", "assets", "fonts")
    for f in os.listdir(fd): QFontDatabase.addApplicationFont(os.path.join(fd, f))
    app.setFont(QFont("Tajawal", 11))
    k = user(env.ids["keeper"])
    with db.session_scope() as s:
        d = inv.create_incoming(s, k, "donation", date.today(), [dict(item_id=env.ids["item"], quantity=5, unit_cost=to_e4(2))])
        inv.confirm_incoming(s, k, d.id)
    w = MainWindow(user(env.ids["admin"]))
    assert w.layoutDirection() == Qt.RightToLeft
    assert len(w.pages) == 16
    for i in range(len(w.pages)):
        w.go(i)
    alert_btn = next(b for b, name in w.navs if "التنبيهات" in name)
    assert "(1)" in alert_btn.text()          # badge: 5 < min 20 => 1 new alert
    w.poll()                                      # second poll must not re-notify
    from clinic_inventory.services import alerts
    with db.session_scope() as s:
        assert alerts.pending_desktop_notifications(s) == []
    w.go(0); w.grab().save(str(tmp_path / "shot_dash.png"))
    w.go(3); w.grab().save(str(tmp_path / "shot_issue.png"))
    w.go(12); w.grab().save(str(tmp_path / "shot_alerts.png")); w.close()
