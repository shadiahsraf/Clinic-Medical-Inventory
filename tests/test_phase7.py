import os
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from clinic_inventory.ui.app import MainWindow
from .conftest import user


def test_sidebar_contains_all_16_modules(env):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication([])

    admin = user(env.ids["admin"])
    w = MainWindow(admin)

    expected_modules = [
        "لوحة التحكم",
        "إدارة الأصناف",
        "الوارد إلى المخزن",
        "صرف المستلزمات",
        "إدارة العيادات والأقسام",
        "إدارة الموردين",
        "إدارة التبرعات",
        "المرتجعات",
        "الهالك والتالف",
        "الجرد والتسويات",
        "سجل حركة المخزون",
        "التقارير",
        "التنبيهات",
        "المستخدمون والصلاحيات",
        "النسخ الاحتياطي والاستعادة",
        "الإعدادات"
    ]

    # Verify count
    assert len(w.pages) == 16
    assert len(w.navs) == 16

    # Verify exact names and order
    for idx, expected_name in enumerate(expected_modules):
        btn, name = w.navs[idx]
        assert name == expected_name
        # Test navigation to page
        w.go(idx)
        assert w.stack.currentIndex() == idx

    # Verify right-to-left layout
    assert w.layoutDirection() == Qt.RightToLeft
    w.close()
