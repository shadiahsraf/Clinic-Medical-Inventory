"""Settings and Audit Log page (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QSpinBox, QCheckBox, QTabWidget, QDateEdit
)
from .. import db
from ..services import settings, auth
from .common import Page, kill, ar_error, table


class SettingsPage(Page):
    def __init__(self, win):
        super().__init__(win, "الإعدادات وسجل المراجعة")
        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.RightToLeft)
        self.lay.addWidget(self.tabs, 1)

        # Tab 1: General Settings
        self.settings_tab = QWidget()
        self.init_settings_tab()
        self.tabs.addTab(self.settings_tab, "إعدادات النظام العامة")

        # Tab 2: Audit Log
        self.audit_tab = QWidget()
        self.init_audit_tab()
        self.tabs.addTab(self.audit_tab, "سجل المراجعة والعمليات")

    def init_settings_tab(self):
        s_lay = QVBoxLayout(self.settings_tab)
        f = QFormLayout()

        # Application Info
        self.app_name_edit = QLineEdit()
        f.addRow("اسم المنشأة الطبية / العيادة:", self.app_name_edit)

        # Default minimum stock
        self.min_stock_spin = QSpinBox()
        self.min_stock_spin.setRange(0, 100000)
        f.addRow("الحد الأدنى الافتراضي لمخزون الأصناف:", self.min_stock_spin)

        # Currency
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(["جنيه", "ج.م", "EGP"])
        f.addRow("رمز وعملة النظام المعروضة:", self.currency_combo)

        # Numbers display
        self.arabic_num_check = QCheckBox("استخدام الأرقام العربية المشرقية (١، ٢، ٣...) بدلاً من اللاتينية")
        f.addRow("تفضيل الأرقام:", self.arabic_num_check)

        # Date format
        self.date_fmt_combo = QComboBox()
        self.date_fmt_combo.addItems(["YYYY-MM-DD", "DD/MM/YYYY"])
        f.addRow("صيغة عرض التاريخ:", self.date_fmt_combo)

        # Notifications
        self.notify_low_check = QCheckBox("تنبيهات المخزون المنخفض (عند بلوغ الحد الأدنى)")
        self.notify_out_check = QCheckBox("تنبيهات نفاد المخزون (عند وصول الرصيد إلى صفر)")
        f.addRow("إعدادات التنبيهات:", self.notify_low_check)
        f.addRow("", self.notify_out_check)

        # Print settings
        self.header_text_edit = QLineEdit()
        self.footer_text_edit = QLineEdit()
        f.addRow("ترويسة السندات والتقارير المطبوعة:", self.header_text_edit)
        f.addRow("تذييل السندات المطبوعة:", self.footer_text_edit)

        s_lay.addLayout(f)

        save_btn = QPushButton("حفظ جميع الإعدادات")
        save_btn.clicked.connect(self.save_all_settings)
        s_lay.addWidget(save_btn, 0, Qt.AlignRight)
        s_lay.addStretch()

    def init_audit_tab(self):
        a_lay = QVBoxLayout(self.audit_tab)

        # Filter bar
        filter_bar = QHBoxLayout()

        self.user_filter = QComboBox()
        self.action_filter = QComboBox()
        self.action_filter.addItems(["جميع العمليات", "create_item", "update_item", "confirm_incoming", "create_issue", "record_return", "approve_return", "record_damage", "approve_stocktake", "supplier_payment", "backup", "create_user", "change_password", "update_settings"])

        self.d1_edit = QDateEdit()
        self.d1_edit.setCalendarPopup(True)
        self.d1_edit.setDate(date(2026, 1, 1))

        self.d2_edit = QDateEdit()
        self.d2_edit.setCalendarPopup(True)
        self.d2_edit.setDate(date.today())

        filter_btn = QPushButton("تصفية وبحث")
        filter_btn.clicked.connect(self.refresh_audit)

        filter_bar.addWidget(QLabel("المستخدم:"))
        filter_bar.addWidget(self.user_filter)
        filter_bar.addWidget(QLabel("العملية:"))
        filter_bar.addWidget(self.action_filter)
        filter_bar.addWidget(QLabel("من:"))
        filter_bar.addWidget(self.d1_edit)
        filter_bar.addWidget(QLabel("إلى:"))
        filter_bar.addWidget(self.d2_edit)
        filter_bar.addWidget(filter_btn)
        a_lay.addLayout(filter_bar)

        self.audit_container = QVBoxLayout()
        a_lay.addLayout(self.audit_container, 1)
        self.audit_table = None

    def refresh(self):
        # Refresh Settings
        with db.session_scope() as s:
            st = settings.get_all_settings(s)
            self.app_name_edit.setText(st.get("app_name", ""))
            self.min_stock_spin.setValue(int(st.get("default_min_stock", "10")))
            curr_idx = self.currency_combo.findText(st.get("currency_symbol", "جنيه"))
            if curr_idx >= 0: self.currency_combo.setCurrentIndex(curr_idx)
            self.arabic_num_check.setChecked(st.get("arabic_numbers", "0") == "1")
            df_idx = self.date_fmt_combo.findText(st.get("date_format", "YYYY-MM-DD"))
            if df_idx >= 0: self.date_fmt_combo.setCurrentIndex(df_idx)
            self.notify_low_check.setChecked(st.get("alert_low_stock_enabled", "1") == "1")
            self.notify_out_check.setChecked(st.get("alert_out_of_stock_enabled", "1") == "1")
            self.header_text_edit.setText(st.get("print_header_text", ""))
            self.footer_text_edit.setText(st.get("print_footer_text", ""))

            # Populate users filter
            cur_uid = self.user_filter.currentData()
            self.user_filter.clear()
            self.user_filter.addItem("جميع المستخدمين", None)
            for u in auth.list_users(s):
                self.user_filter.addItem(u.display_name, u.id)
            if cur_uid:
                idx = self.user_filter.findData(cur_uid)
                if idx >= 0: self.user_filter.setCurrentIndex(idx)

        self.refresh_audit()

    def save_all_settings(self):
        new_settings = {
            "app_name": self.app_name_edit.text().strip(),
            "default_min_stock": str(self.min_stock_spin.value()),
            "currency_symbol": self.currency_combo.currentText(),
            "arabic_numbers": "1" if self.arabic_num_check.isChecked() else "0",
            "date_format": self.date_fmt_combo.currentText(),
            "alert_low_stock_enabled": "1" if self.notify_low_check.isChecked() else "0",
            "alert_out_of_stock_enabled": "1" if self.notify_out_check.isChecked() else "0",
            "print_header_text": self.header_text_edit.text().strip(),
            "print_footer_text": self.footer_text_edit.text().strip()
        }
        try:
            with db.session_scope() as s:
                settings.save_settings(s, self.user, new_settings)
            QMessageBox.information(self, "تم", "تم حفظ وتطبيق جميع الإعدادات بنجاح.")
        except Exception as e:
            ar_error(self, e)

    def refresh_audit(self):
        kill(self.audit_table)
        user_id = self.user_filter.currentData()
        action_text = self.action_filter.currentText()
        action = None if action_text == "جميع العمليات" else action_text
        d1 = self.d1_edit.date().toPython()
        d2 = self.d2_edit.date().toPython()

        with db.session_scope() as s:
            logs = settings.list_audit_logs(s, user_id=user_id, action=action, d1=d1, d2=d2)

        headers = ["المعرف", "التاريخ والوقت", "المستخدم", "نوع العملية", "الكيان", "معرف الكيان", "القيمة السابقة", "القيمة الجديدة"]
        rows = []
        for l in logs:
            rows.append([
                l["id"],
                l["ts"].strftime("%Y-%m-%d %H:%M:%S"),
                l["user_name"],
                l["action"],
                l["entity_type"],
                l["entity_id"],
                l["old_value"],
                l["new_value"]
            ])

        self.audit_table = table(headers, rows)
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.audit_container.addWidget(self.audit_table)
