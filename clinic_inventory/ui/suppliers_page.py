"""Suppliers management page (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame
)
from .. import db
from ..models import Supplier
from ..money import fmt_egp
from ..services import catalog
from .common import Page, kill, ar_error, table


class SupplierEditDialog(QDialog):
    def __init__(self, parent=None, supplier=None):
        super().__init__(parent)
        self.supplier = supplier
        self.setWindowTitle("تعديل بيانات مورد" if supplier else "إضافة مورد جديد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(450, 380)

        f = QFormLayout(self)
        self.name_edit = QLineEdit(supplier.name if supplier else "")
        self.phone_edit = QLineEdit(supplier.phone or "" if supplier else "")
        self.contact_edit = QLineEdit(supplier.contact_person or "" if supplier else "")
        self.address_edit = QLineEdit(supplier.address or "" if supplier else "")
        self.notes_edit = QTextEdit(supplier.notes or "" if supplier else "")
        self.notes_edit.setMaximumHeight(80)

        f.addRow("اسم المورد *:", self.name_edit)
        f.addRow("رقم الهاتف:", self.phone_edit)
        f.addRow("الشخص المسؤول:", self.contact_edit)
        f.addRow("العنوان:", self.address_edit)
        f.addRow("ملاحظات:", self.notes_edit)

        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton("حفظ", QDialogButtonBox.AcceptRole)
        self.cancel_btn = buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "phone": self.phone_edit.text().strip() or None,
            "contact_person": self.contact_edit.text().strip() or None,
            "address": self.address_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }


class SupplierHistoryDialog(QDialog):
    def __init__(self, parent, supplier_id, supplier_name):
        super().__init__(parent)
        self.supplier_id = supplier_id
        self.setWindowTitle(f"سجل مششتريات وحساب المورد: {supplier_name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(850, 500)

        lay = QVBoxLayout(self)

        # Summary Frame
        summary_frame = QFrame()
        summary_frame.setObjectName("card")
        sum_lay = QHBoxLayout(summary_frame)

        self.total_purchases_lbl = QLabel("إجمالي المشتريات: 0.00 جنيه")
        self.total_paid_lbl = QLabel("إجمالي المدفوع: 0.00 جنيه")
        self.balance_lbl = QLabel("الرصيد المتبقي المستحق: 0.00 جنيه")
        self.balance_lbl.setStyleSheet("font-weight:bold; color:#c0392b;")

        for lbl in (self.total_purchases_lbl, self.total_paid_lbl, self.balance_lbl):
            sum_lay.addWidget(lbl)
        lay.addWidget(summary_frame)

        # History Table
        with db.session_scope() as s:
            history = catalog.get_supplier_history(s, supplier_id)

        headers = ["رقم الفاتورة", "تاريخ الوارد", "المرجع / إذن التوريد", "إجمالي الفاتورة", "المدفوع", "المتبقي", "الحالة"]
        status_map = {"confirmed": "مؤكد", "draft": "مسودة", "cancelled": "ملغى"}

        tot_purchases = sum(h["total_cost"] for h in history if h["status"] == "confirmed")
        tot_paid = sum(h["paid"] for h in history)
        tot_outstanding = sum(h["outstanding"] for h in history)

        self.total_purchases_lbl.setText(f"إجمالي المشتريات: {fmt_egp(tot_purchases)}")
        self.total_paid_lbl.setText(f"إجمالي المدفوع: {fmt_egp(tot_paid)}")
        self.balance_lbl.setText(f"الرصيد المستحق: {fmt_egp(tot_outstanding)}")

        rows = []
        for h in history:
            rows.append([
                h["number"],
                h["doc_date"].strftime("%Y-%m-%d"),
                h["reference"],
                fmt_egp(h["total_cost"]),
                fmt_egp(h["paid"]),
                fmt_egp(h["outstanding"]),
                status_map.get(h["status"], h["status"])
            ])

        t = table(headers, rows)
        lay.addWidget(t, 1)

        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn, 0, Qt.AlignCenter)


class SuppliersPage(Page):
    def __init__(self, win):
        super().__init__(win, "إدارة الموردين")
        self.t = None
        self.suppliers_list = []

        # Action bar
        bar = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("بحث باسم المورد أو الهاتف أو المسؤول...")
        self.q.textChanged.connect(self.refresh)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["الكل", "النشطين فقط", "المعطلين فقط"])
        self.status_filter.currentIndexChanged.connect(self.refresh)

        add_btn = QPushButton("إضافة مورد جديد")
        add_btn.clicked.connect(self.add_supplier)

        bar.addWidget(QLabel("بحث:"))
        bar.addWidget(self.q, 2)
        bar.addWidget(QLabel("الحالة:"))
        bar.addWidget(self.status_filter)
        bar.addWidget(add_btn)
        self.lay.addLayout(bar)

        # Control buttons for selected supplier
        ops_bar = QHBoxLayout()
        self.history_btn = QPushButton("سجل المشتريات والرصيد")
        self.history_btn.clicked.connect(self.view_history)

        self.edit_btn = QPushButton("تعديل بيانات المورد")
        self.edit_btn.clicked.connect(self.edit_supplier)

        self.toggle_active_btn = QPushButton("تعطيل / تفعيل")
        self.toggle_active_btn.clicked.connect(self.toggle_active)

        self.delete_btn = QPushButton("حذف المورد")
        self.delete_btn.setObjectName("btn-danger")
        self.delete_btn.clicked.connect(self.delete_supplier)

        for btn in (self.history_btn, self.edit_btn, self.toggle_active_btn, self.delete_btn):
            ops_bar.addWidget(btn)
        self.lay.addLayout(ops_bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        kill(self.t)
        active_idx = self.status_filter.currentIndex()
        active_filter = None if active_idx == 0 else (True if active_idx == 1 else False)

        with db.session_scope() as s:
            sups = catalog.search_suppliers(s, self.q.text(), active_only=False)
            if active_filter is not None:
                sups = [x for x in sups if x.active is active_filter]

            self.suppliers_list = [(x.id, x.name, x.phone or "", x.contact_person or "", x.address or "", x.notes or "", x.active) for x in sups]

            rows = []
            for sup in self.suppliers_list:
                status_str = "نشط" if sup[6] else "معطل"
                rows.append([sup[0], sup[1], sup[2], sup[3], sup[4], sup[5], status_str])

        headers = ["المعرف", "اسم المورد", "الهاتف", "الشخص المسؤول", "العنوان", "ملاحظات", "الحالة"]
        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.doubleClicked.connect(self.view_history)
        self.table_container.addWidget(self.t)

    def _selected_supplier(self):
        if not self.t:
            return None
        r = self.t.currentRow()
        if r < 0 or r >= len(self.suppliers_list):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد مورد من الجدول أولاً.")
            return None
        return self.suppliers_list[r]

    def add_supplier(self):
        dlg = SupplierEditDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            try:
                with db.session_scope() as s:
                    catalog.create_supplier(s, self.user, **data)
                QMessageBox.information(self, "تم", "تم إضافة المورد بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def edit_supplier(self):
        item = self._selected_supplier()
        if not item:
            return
        sup_id = item[0]
        with db.session_scope() as s:
            supplier = s.get(Supplier, sup_id)
            if not supplier:
                return
            dlg = SupplierEditDialog(self, supplier)
            if dlg.exec():
                data = dlg.get_data()
                try:
                    catalog.update_supplier(s, self.user, sup_id, **data)
                    QMessageBox.information(self, "تم", "تم تحديث بيانات المورد بنجاح.")
                except Exception as e:
                    ar_error(self, e)
                    return
        self.refresh()

    def view_history(self):
        item = self._selected_supplier()
        if not item:
            return
        dlg = SupplierHistoryDialog(self, item[0], item[1])
        dlg.exec()

    def toggle_active(self):
        item = self._selected_supplier()
        if not item:
            return
        sup_id, sup_name, _, _, _, _, is_active = item
        new_state = not is_active
        action_name = "تفعيل" if new_state else "تعطيل"

        reply = QMessageBox.question(
            self, "تأكيد", f"هل أنت متأكد من {action_name} المورد «{sup_name}»؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    catalog.set_supplier_active(s, self.user, sup_id, new_state)
                QMessageBox.information(self, "تم", f"تم {action_name} المورد بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def delete_supplier(self):
        item = self._selected_supplier()
        if not item:
            return
        sup_id, sup_name = item[0], item[1]

        reply = QMessageBox.warning(
            self, "تأكيد الحذف",
            f"هل أنت متأكد من حذف المورد «{sup_name}» نهائيًا؟\nملاحظة: لا يمكن حذف المورد إذا كان له حركات شراء.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    catalog.delete_supplier(s, self.user, sup_id)
                QMessageBox.information(self, "تم", "تم حذف المورد بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)
