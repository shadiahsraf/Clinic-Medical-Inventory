"""Supplier payments management page (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QDoubleSpinBox, QDateEdit, QFileDialog
)
from .. import db
from ..models import Supplier
from ..money import fmt_egp, to_e4
from ..services import inventory as inv, exports
from .common import Page, kill, ar_error, table


class RecordPaymentDialog(QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("تسجيل دفعة لمورد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(600, 480)

        lay = QVBoxLayout(self)
        f = QFormLayout()

        # Supplier
        self.sup_combo = QComboBox()
        self.sup_combo.currentIndexChanged.connect(self.on_supplier_changed)
        f.addRow("المورد *:", self.sup_combo)

        # Invoice
        self.doc_combo = QComboBox()
        self.doc_combo.currentIndexChanged.connect(self.on_doc_changed)
        f.addRow("فاتورة الشراء المستحقة *:", self.doc_combo)

        # Balances info frame
        self.info_frame = QFrame()
        self.info_frame.setObjectName("card")
        if_lay = QVBoxLayout(self.info_frame)
        self.doc_total_lbl = QLabel("إجمالي الفاتورة: 0.00 جنيه")
        self.paid_so_far_lbl = QLabel("المدفوع سابقًا: 0.00 جنيه")
        self.rem_lbl = QLabel("المتبقي المستحق: 0.00 جنيه")
        self.rem_lbl.setStyleSheet("font-size:15px; font-weight:bold; color:#c0392b;")
        for l in (self.doc_total_lbl, self.paid_so_far_lbl, self.rem_lbl):
            if_lay.addWidget(l)
        f.addRow(self.info_frame)

        # Payment Amount
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, 10000000.0)
        self.amount_spin.setDecimals(2)
        f.addRow("مبلغ الدفعة المسدد *:", self.amount_spin)

        # Payment Date
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(date.today())
        f.addRow("تاريخ السداد:", self.date_edit)

        # Payment Method
        self.method_combo = QComboBox()
        self.method_combo.addItems(["نقدي (خزينة)", "شيك بنكي", "تحويل بنكي", "أخرى"])
        f.addRow("طريقة الدفع:", self.method_combo)

        # Notes / Reference
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("رقم إيصال السداد / رقم الشيك / ملاحظات...")
        self.notes_edit.setMaximumHeight(60)
        f.addRow("الملاحظات / المرجع:", self.notes_edit)

        lay.addLayout(f)

        buttons = QDialogButtonBox()
        self.ok_btn = buttons.addButton("تأكيد السداد", QDialogButtonBox.AcceptRole)
        self.cancel_btn = buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.confirm_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.docs = []
        self.load_suppliers()

    def load_suppliers(self):
        with db.session_scope() as s:
            sups = s.scalars(inv.select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
            self.sup_combo.addItem("— اختر المورد —", None)
            for sup in sups:
                self.sup_combo.addItem(sup.name, sup.id)

    def on_supplier_changed(self, idx):
        sup_id = self.sup_combo.currentData()
        self.doc_combo.clear()
        if not sup_id:
            self.reset_info()
            return
        with db.session_scope() as s:
            self.docs = inv.get_unpaid_purchase_docs(s, supplier_id=sup_id)

        if not self.docs:
            self.doc_combo.addItem("لا توجد فواتير غير مسددة لهذا المورد", None)
            self.reset_info()
            self.ok_btn.setEnabled(False)
            return

        self.ok_btn.setEnabled(True)
        for d in self.docs:
            self.doc_combo.addItem(
                f"{d['number']} (المتبقي: {fmt_egp(d['outstanding'])} | التاريخ: {d['doc_date']})",
                d
            )

    def on_doc_changed(self, idx):
        d = self.doc_combo.currentData()
        if d:
            self.doc_total_lbl.setText(f"إجمالي الفاتورة: {fmt_egp(d['total_cost'])}")
            self.paid_so_far_lbl.setText(f"المدفوع سابقًا: {fmt_egp(d['paid'])}")
            self.rem_lbl.setText(f"المتبقي المستحق: {fmt_egp(d['outstanding'])}")
            # Maximum allowed payment is the outstanding balance in EGP
            # 1 EGP = 10,000 units (e4)
            max_egp = d['outstanding'] / 10000.0
            self.amount_spin.setMaximum(max_egp)
            self.amount_spin.setValue(max_egp)
        else:
            self.reset_info()

    def reset_info(self):
        self.doc_total_lbl.setText("إجمالي الفاتورة: 0.00 جنيه")
        self.paid_so_far_lbl.setText("المدفوع سابقًا: 0.00 جنيه")
        self.rem_lbl.setText("المتبقي المستحق: 0.00 جنيه")
        self.amount_spin.setValue(0.0)

    def confirm_and_accept(self):
        d = self.doc_combo.currentData()
        if not d:
            QMessageBox.warning(self, "تنبيه", "يرجى اختيار فاتورة شراء مستحقة.")
            return

        amt_e4 = to_e4(str(self.amount_spin.value()))
        if amt_e4 <= 0:
            QMessageBox.warning(self, "خطأ", "يجب أن يكون مبلغ الدفعة أكبر من صفر.")
            return

        if amt_e4 > d["outstanding"]:
            QMessageBox.warning(self, "خطأ", "مبلغ الدفعة أكبر من الرصيد المتبقي على الفاتورة.")
            return

        reply = QMessageBox.question(
            self, "تأكيد سداد الدفعة",
            f"هل تريد تأكيد سداد مبلغ {self.amount_spin.value():,.2f} جنيه للمورد «{self.sup_combo.currentText()}»؟\nالفاتورة: {d['number']}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.accept()

    def get_data(self):
        d = self.doc_combo.currentData()
        return {
            "doc_id": d["doc_id"],
            "amount": to_e4(str(self.amount_spin.value())),
            "pay_date": self.date_edit.date().toPython(),
            "method": self.method_combo.currentText(),
            "notes": self.notes_edit.toPlainText().strip() or None
        }


class SupplierPaymentsPage(Page):
    def __init__(self, win):
        super().__init__(win, "مدفوعات الموردين")
        self.t = None
        self.payments = []

        # Action bar
        bar = QHBoxLayout()
        self.sup_filter = QComboBox()
        self.sup_filter.currentIndexChanged.connect(self.refresh)

        add_btn = QPushButton("تسجيل دفعة جديدة")
        add_btn.clicked.connect(self.new_payment)

        export_excel_btn = QPushButton("تصدير Excel")
        export_excel_btn.clicked.connect(self.export_excel)

        export_pdf_btn = QPushButton("تصدير PDF / طباعة")
        export_pdf_btn.clicked.connect(self.export_pdf)

        bar.addWidget(QLabel("المورد:"))
        bar.addWidget(self.sup_filter)
        bar.addStretch()
        bar.addWidget(add_btn)
        bar.addWidget(export_excel_btn)
        bar.addWidget(export_pdf_btn)
        self.lay.addLayout(bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        # Update suppliers filter without resetting selection if possible
        cur_sup_id = self.sup_filter.currentData()
        self.sup_filter.blockSignals(True)
        self.sup_filter.clear()
        self.sup_filter.addItem("جميع الموردين", None)
        with db.session_scope() as s:
            for sup in s.scalars(inv.select(Supplier).order_by(Supplier.name)):
                self.sup_filter.addItem(sup.name, sup.id)
        if cur_sup_id:
            idx = self.sup_filter.findData(cur_sup_id)
            if idx >= 0:
                self.sup_filter.setCurrentIndex(idx)
        self.sup_filter.blockSignals(False)

        kill(self.t)
        selected_sup_id = self.sup_filter.currentData()
        with db.session_scope() as s:
            self.payments = inv.list_supplier_payments(s, supplier_id=selected_sup_id)

        headers = ["المعرف", "تاريخ السداد", "المورد", "رقم الفاتورة", "المبلغ المدفوع", "طريقة الدفع", "إجمالي الفاتورة", "المتبقي بعد الدفعة", "المسؤول", "ملاحظات"]
        rows = []
        for p in self.payments:
            rows.append([
                p["id"],
                p["pay_date"].strftime("%Y-%m-%d"),
                p["supplier_name"],
                p["doc_number"],
                fmt_egp(p["amount"]),
                p["method"],
                fmt_egp(p["doc_total"]),
                fmt_egp(p["remaining"]),
                p["creator_name"],
                p["notes"]
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_container.addWidget(self.t)

    def new_payment(self):
        dlg = RecordPaymentDialog(self, self.user)
        if dlg.exec():
            data = dlg.get_data()
            try:
                with db.session_scope() as s:
                    inv.record_payment(s, self.user, **data)
                QMessageBox.information(self, "تم", "تم تسجيل الدفعة بنجاح وتحديث الرصيد المستحق للمورد.")
                self.refresh()
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)

    def export_excel(self):
        if not self.payments:
            QMessageBox.information(self, "تنبيه", "لا توجد سجلات مدفوعات للتصدير.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ كملف Excel", "supplier_payments.xlsx", "*.xlsx")
        if path:
            try:
                headers = ["المعرف", "تاريخ السداد", "المورد", "رقم الفاتورة", "المبلغ المدفوع", "طريقة الدفع", "المسؤول", "ملاحظات"]
                rows = [[p["id"], p["pay_date"].strftime("%Y-%m-%d"), p["supplier_name"], p["doc_number"], fmt_egp(p["amount"]), p["method"], p["creator_name"], p["notes"]] for p in self.payments]
                exports.export_excel(path, "سجل مدفوعات الموردين", headers, rows)
                QMessageBox.information(self, "تم", "تم تصدير سجل المدفوعات بنجاح.")
            except Exception as e:
                ar_error(self, e)

    def export_pdf(self):
        if not self.payments:
            QMessageBox.information(self, "تنبيه", "لا توجد سجلات مدفوعات للتصدير.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ كملف PDF", "supplier_payments.pdf", "*.pdf")
        if path:
            try:
                headers = ["المعرف", "تاريخ السداد", "المورد", "رقم الفاتورة", "المبلغ", "طريقة الدفع", "المسؤول"]
                rows = [[p["id"], p["pay_date"].strftime("%Y-%m-%d"), p["supplier_name"], p["doc_number"], fmt_egp(p["amount"]), p["method"], p["creator_name"]] for p in self.payments]
                exports.export_pdf(path, "سجل مدفوعات الموردين", headers, rows)
                QMessageBox.information(self, "تم", "تم إنشاء ملف PDF بنجاح.")
            except Exception as e:
                ar_error(self, e)
