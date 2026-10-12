import os
import pytest
from clinic_inventory import db
from clinic_inventory.models import Alert, Item
from clinic_inventory.services import catalog, alerts, settings
from .conftest import user


def test_arabic_notifications_text_and_delivery(env):
    admin = user(env.ids["admin"])

    with db.session_scope() as s:
        it = catalog.create_item(s, admin, "شاش معقم 10 سم", "علبة", min_stock=15)
        item_id = it.id

        # 1. Low stock alert
        a_low = Alert(item_id=item_id, kind="low", qty_at_creation=10, min_at_creation=15)
        s.add(a_low)
        s.flush()
        title_low, body_low = alerts.notification_text_ar(a_low)
        assert title_low == "تنبيه انخفاض المخزون"
        assert "شاش معقم 10 سم" in body_low
        assert "الرصيد الحالي: 10" in body_low
        assert "الحد الأدنى: 15" in body_low

        # Resolve low alert so another alert can be created (ux_one_open_alert unique index)
        a_low.status = "resolved"
        s.flush()

        # 2. Out of stock alert
        a_out = Alert(item_id=item_id, kind="out", qty_at_creation=0, min_at_creation=15)
        s.add(a_out)
        s.flush()
        title_out, body_out = alerts.notification_text_ar(a_out)
        assert title_out == "تنبيه نفاد المخزون"
        assert "شاش معقم 10 سم" in body_out
        assert "الرصيد الحالي: صفر" in body_out


def test_packaged_assets_integrity():
    # Verify assets packaged with PyInstaller exist and are accessible
    root = os.path.dirname(os.path.dirname(__file__))
    assets_dir = os.path.join(root, "clinic_inventory", "assets")
    fonts_dir = os.path.join(assets_dir, "fonts")

    assert os.path.isdir(assets_dir), "Assets directory must exist"
    assert os.path.isdir(fonts_dir), "Fonts directory must exist"

    font_files = os.listdir(fonts_dir)
    assert any("Tajawal" in f for f in font_files), "Tajawal font must be present"

    # Verify run_app.py entrypoint exists
    entrypoint = os.path.join(root, "run_app.py")
    assert os.path.isfile(entrypoint), "run_app.py entrypoint must exist"
