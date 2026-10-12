"""Donations management page (In-kind & Cash) (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QDoubleSpinBox, QSpinBox, QDateEdit, QTabWidget
)
from .. import db
from ..money import fmt_egp, to_e4
from ..services import catalog, inventory as inv
from .common import Page, kill, ar_error, table


class AddInKindDonationDialog(QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("تسجيل تبرع عيني بمستلزمات طبية")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(550, 420)

        f = QFormLayout(self)
        self.donor_edit = QLineEdit("فاعل خير")
        self.item_combo = QComboBox()
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1000000)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0.0, 10000000.0)
        self.cost_spin.setDecimals(2)

        self.exp_edit = QLineEdit()
        self.exp_edit.setPlaceholderText("YYYY-MM-DD (اختياري)")

        self.ref_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(60)

        f.addRow("اسم المتبرع / الجهة *:", self.donor_edit)
        f.addRow("الصنف المتبرع به *:", self.item_combo)
        f.addRow("الكمية المتبرع بها *:", self.qty_spin)
        f.addRow("القيمة التقديرية للوحدة (جنيه):", self.cost_spin)
        f.addRow("تاريخ الصلاحية:", self.exp_edit)
        f.addRow("رقم الإيصال / المرجع:", self.ref_edit)
        f.addRow("ملاحظات:", self.notes_edit)

        with db.session_scope() as s:
            for it in catalog.search_items(s, active_only=True):
                self.item_combo.addItem(f"{it.code} - {it.name}", it.id)

        buttons = QDialogButtonBox()
        buttons.addButton("تأكيد استلام التبرع", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def get_data(self):
        exp = None
        if self.exp_edit.text().strip():
            exp = date.fromisoformat(self.exp_edit.text().strip())
        return {
            "donor_name": self.donor_edit.text().strip() or "فاعل خير",
            "item_id": self.item_combo.currentData(),
            "quantity": self.qty_spin.value(),
            "unit_cost": to_e4(str(self.cost_spin.value())),
            "expiry_date": exp,
            "reference": self.ref_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None
        }


class AddCashDonationDialog(QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("تسجيل تبرع نقدي للخزينة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(450, 300)

        f = QFormLayout(self)
        self.donor_edit = QLineEdit("فاعل خير")
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(1.0, 100000000.0)
        self.amount_spin.setDecimals(2)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(date.today())

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("رقم إيصال استلام النقدية / ملاحظات...")
        self.notes_edit.setMaximumHeight(60)

        f.addRow("اسم المتبرع *:", self.donor_edit)
        f.addRow("المبلغ المتبرع به (جنيه) *:", self.amount_spin)
        f.addRow("تاريخ الاستلام:", self.date_edit)
        f.addRow("ملاحظات / إيصال:", self.notes_edit)

        buttons = QDialogButtonBox()
        buttons.addButton("تأكيد استلام النقدية", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def get_data(self):
        return {
            "donor_name": self.donor_edit.text().strip() or "فاعل خير",
            "amount": to_e4(str(self.amount_spin.value())),
            "move_date": self.date_edit.date().toPython(),
            "notes": self.notes_edit.toPlainText().strip() or None
        }


class DonationsPage(Page):
    def __init__(self, win):
        super().__init__(win, "إدارة التبرعات")
        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.RightToLeft)
        self.lay.addWidget(self.tabs, 1)

        # Tab 1: In-kind donations
        self.inkind_tab = QWidget()
        self.init_inkind_tab()
        self.tabs.addTab(self.inkind_tab, "التبرعات العينية (مستلزمات)")

        # Tab 2: Cash donations
        self.cash_tab = QWidget()
        self.init_cash_tab()
        self.tabs.addTab(self.cash_tab, "التبرعات النقدية")

    def init_inkind_tab(self):
        lay = QVBoxLayout(self.inkind_tab)

        bar = QHBoxLayout()
        self.total_inkind_lbl = QLabel("إجمالي القيمة التقديرية للتبرعات: 0.00 جنيه")
        self.total_inkind_lbl.setStyleSheet("font-weight:bold; color:#24585c;")

        add_btn = QPushButton("تسجيل تبرع عيني جديد")
        add_btn.clicked.connect(self.add_inkind_donation)

        bar.addWidget(self.total_inkind_lbl)
        bar.addStretch()
        bar.addWidget(add_btn)
        lay.addLayout(bar)

        self.inkind_container = QVBoxLayout()
        lay.addLayout(self.inkind_container, 1)
        self.inkind_table = None

    def init_cash_tab(self):
        lay = QVBoxLayout(self.cash_tab)

        bar = QHBoxLayout()
        self.total_cash_lbl = QLabel("إجمالي التبرعات النقدية: 0.00 جنيه")
        self.total_cash_lbl.setStyleSheet("font-weight:bold; color:#1e7e34;")

        add_btn = QPushButton("تسجيل تبرع نقدي جديد")
        add_btn.clicked.connect(self.add_cash_donation)

        bar.addWidget(self.total_cash_lbl)
        bar.addStretch()
        bar.addWidget(add_btn)
        lay.addLayout(bar)

        self.cash_container = QVBoxLayout()
        lay.addLayout(self.cash_container, 1)
        self.cash_table = None

    def refresh(self):
        # 1. In-kind
        kill(self.inkind_table)
        with db.session_scope() as s:
            inkind_list = inv.list_inkind_donations(s)
            cash_list = inv.list_cash_donations(s)

        tot_inkind = sum(d["estimated_value"] for d in inkind_list if d["status"] == "confirmed")
        self.total_inkind_lbl.setText(f"إجمالي القيمة التقديرية للتبرعات العينية: {fmt_egp(tot_inkind)}")

        status_ar = {"confirmed": "مؤكد", "draft": "مسودة", "cancelled": "ملغى"}
        headers_inkind = ["رقم المستند", "التاريخ", "اسم المتبرع", "الأصناف المتبرع بها", "القيمة التقديرية", "الحالة", "المرجع", "المسؤول"]
        rows_inkind = []
        for d in inkind_list:
            rows_inkind.append([
                d["number"],
                d["doc_date"].strftime("%Y-%m-%d"),
                d["donor_name"],
                d["items_summary"],
                fmt_egp(d["estimated_value"]),
                status_ar.get(d["status"], d["status"]),
                d["reference"],
                d["creator_name"]
            ])

        self.inkind_table = table(headers_inkind, rows_inkind)
        self.inkind_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inkind_container.addWidget(self.inkind_table)

        # 2. Cash
        kill(self.cash_table)
        tot_cash = sum(m["amount"] for m in cash_list)
        self.total_cash_lbl.setText(f"إجمالي التبرعات النقدية المستلمة: {fmt_egp(tot_cash)}")

        headers_cash = ["المعرف", "تاريخ الاستلام", "اسم المتبرع", "المبلغ", "المسؤول", "ملاحظات"]
        rows_cash = []
        for m in cash_list:
            rows_cash.append([
                m["id"],
                m["move_date"].strftime("%Y-%m-%d"),
                m["donor_name"],
                fmt_egp(m["amount"]),
                m["creator_name"],
                m["notes"]
            ])

        self.cash_table = table(headers_cash, rows_cash)
        self.cash_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cash_container.addWidget(self.cash_table)

    def add_inkind_donation(self):
        dlg = AddInKindDonationDialog(self, self.user)
        if dlg.exec():
            try:
                data = dlg.get_data()
                with db.session_scope() as s:
                    doc = inv.create_incoming(
                        s, self.user, "donation", date.today(),
                        [dict(item_id=data["item_id"], quantity=data["quantity"],
                              unit_cost=data["unit_cost"], expiry_date=data["expiry_date"])],
                        donor_name=data["donor_name"], reference=data["reference"], notes=data["notes"]
                    )
                    inv.confirm_incoming(s, self.user, doc.id)
                    num = doc.number
                QMessageBox.information(self, "تم", f"تم تسجيل وتأكيد التبرع العيني رقم {num} وإضافته إلى رصيد المخزن بنجاح.")
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)

    def add_cash_donation(self):
        dlg = AddCashDonationDialog(self, self.user)
        if dlg.exec():
            try:
                data = dlg.get_data()
                with db.session_scope() as s:
                    inv.record_cash_donation(s, self.user, **data)
                QMessageBox.information(self, "تم", "تم تسجيل التبرع النقدي في حركة الخزينة بنجاح.")
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)
