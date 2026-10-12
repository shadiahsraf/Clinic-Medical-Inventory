"""Detailed Inventory Movement History page (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QDateEdit, QFileDialog, QGridLayout
)
from sqlalchemy import select
from .. import db
from ..models import Item, Department
from ..money import fmt_egp
from ..services import reports, exports, catalog
from .common import Page, kill, ar_error, table


class MovementHistoryPage(Page):
    def __init__(self, win):
        super().__init__(win, "سجل حركة المخزون")
        self.t = None
        self.movements = []

        # Filters Bar
        f_box = QGroupBox("خيارات البحث والتصفية")
        f_lay = QGridLayout(f_box)

        self.item_filter = QComboBox()
        self.dept_filter = QComboBox()
        self.type_filter = QComboBox()
        self.type_filter.addItems([
            "جميع الحركات",
            "وارد إلى المخزن",
            "صرف إلى قسم",
            "مرتجع من قسم",
            "استبعاد هالك/تالف",
            "تسوية جرد",
            "إلغاء وارد"
        ])
        self.type_keys = [None, "incoming", "issue", "return", "damage", "adjustment", "incoming_reversal"]

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث برقم السند (مثال: OUT-000005) أو الصنف أو الطرف...")
        self.search_input.returnPressed.connect(self.refresh)

        self.d1_edit = QDateEdit()
        self.d1_edit.setCalendarPopup(True)
        today = date.today()
        self.d1_edit.setDate(date(today.year, 1, 1))

        self.d2_edit = QDateEdit()
        self.d2_edit.setCalendarPopup(True)
        self.d2_edit.setDate(today)

        filter_btn = QPushButton("بحث وتصفية")
        filter_btn.clicked.connect(self.refresh)

        reset_btn = QPushButton("إعادة تعيين")
        reset_btn.setObjectName("btn-secondary")
        reset_btn.clicked.connect(self.reset_filters)

        f_lay.addWidget(QLabel("بحث سريع:"), 0, 0)
        f_lay.addWidget(self.search_input, 0, 1, 1, 2)
        f_lay.addWidget(QLabel("الصنف:"), 0, 3)
        f_lay.addWidget(self.item_filter, 0, 4)
        f_lay.addWidget(QLabel("العيادة/القسم:"), 0, 5)
        f_lay.addWidget(self.dept_filter, 0, 6)

        f_lay.addWidget(QLabel("نوع الحركة:"), 1, 0)
        f_lay.addWidget(self.type_filter, 1, 1)
        f_lay.addWidget(QLabel("الفترة من:"), 1, 2)
        f_lay.addWidget(self.d1_edit, 1, 3)
        f_lay.addWidget(QLabel("إلى:"), 1, 4)
        f_lay.addWidget(self.d2_edit, 1, 5)
        btn_h = QHBoxLayout()
        btn_h.addWidget(filter_btn)
        btn_h.addWidget(reset_btn)
        f_lay.addLayout(btn_h, 1, 6)

        self.lay.addWidget(f_box)

        # Export & Actions bar
        act_bar = QHBoxLayout()
        export_excel_btn = QPushButton("تصدير Excel")
        export_excel_btn.clicked.connect(self.export_excel)

        export_pdf_btn = QPushButton("تصدير PDF")
        export_pdf_btn.clicked.connect(self.export_pdf)

        self.print_voucher_btn = QPushButton("طباعة سند الصرف المحدد")
        self.print_voucher_btn.clicked.connect(self.print_selected_voucher)

        act_bar.addWidget(self.print_voucher_btn)
        act_bar.addStretch()
        act_bar.addWidget(export_excel_btn)
        act_bar.addWidget(export_pdf_btn)
        self.lay.addLayout(act_bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def reset_filters(self):
        self.search_input.clear()
        self.item_filter.setCurrentIndex(0)
        self.dept_filter.setCurrentIndex(0)
        self.type_filter.setCurrentIndex(0)
        today = date.today()
        self.d1_edit.setDate(date(today.year, 1, 1))
        self.d2_edit.setDate(today)
        self.refresh()

    def refresh(self):
        # Update comboboxes
        cur_item_id = self.item_filter.currentData()
        cur_dept_id = self.dept_filter.currentData()

        self.item_filter.blockSignals(True)
        self.dept_filter.blockSignals(True)
        self.item_filter.clear()
        self.dept_filter.clear()

        self.item_filter.addItem("جميع الأصناف", None)
        self.dept_filter.addItem("جميع العيادات والأقسام", None)

        with db.session_scope() as s:
            for it in catalog.search_items(s, active_only=False):
                self.item_filter.addItem(f"{it.code} - {it.name}", it.id)
            for d in catalog.search_departments(s, active_only=False):
                self.dept_filter.addItem(d.name, d.id)

        if cur_item_id:
            idx = self.item_filter.findData(cur_item_id)
            if idx >= 0: self.item_filter.setCurrentIndex(idx)
        if cur_dept_id:
            idx = self.dept_filter.findData(cur_dept_id)
            if idx >= 0: self.dept_filter.setCurrentIndex(idx)

        self.item_filter.blockSignals(False)
        self.dept_filter.blockSignals(False)

        kill(self.t)
        item_id = self.item_filter.currentData()
        dept_id = self.dept_filter.currentData()
        kind = self.type_keys[self.type_filter.currentIndex()]
        d1 = self.d1_edit.date().toPython()
        d2 = self.d2_edit.date().toPython()
        search_kw = self.search_input.text().strip() or None

        with db.session_scope() as s:
            self.movements = reports.query_movement_history(s, item_id=item_id, department_id=dept_id,
                                                            kind=kind, d1=d1, d2=d2, search=search_kw)

        headers = ["رقم المستند", "التاريخ والوقت", "نوع الحركة", "الجهة / الطرف", "كود الصنف", "اسم الصنف", "الكمية", "سعر الوحدة", "إجمالي القيمة", "الدفعة", "المسؤول"]
        rows = []
        for m in self.movements:
            qty_str = f"+{m['qty_delta']}" if m["qty_delta"] > 0 else str(m["qty_delta"])
            rows.append([
                m["ref_doc"],
                m["ts"].strftime("%Y-%m-%d %H:%M"),
                m["kind_ar"],
                m["partner"],
                m["item_code"],
                m["item_name"],
                qty_str,
                fmt_egp(m["unit_cost"]),
                fmt_egp(m["value_delta"]),
                f"#{m['batch_id']}",
                m["user_name"]
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.doubleClicked.connect(self.print_selected_voucher)
        self.table_container.addWidget(self.t)

    def print_selected_voucher(self):
        if not self.t:
            return
        r = self.t.currentRow()
        if r < 0 or r >= len(self.movements):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد حركة صرف من الجدول أولاً.")
            return
        m = self.movements[r]
        if m["kind"] != "issue":
            QMessageBox.information(self, "تنبيه", "الطباعة متاحة لحركات الصرف.")
            return

        # Find issue doc id
        ref_doc = m["ref_doc"]  # e.g. OUT-000001
        with db.session_scope() as s:
            from ..models import IssueDoc
            doc = s.scalars(select(IssueDoc).where(IssueDoc.number == ref_doc)).first()
            if not doc:
                QMessageBox.warning(self, "خطأ", "لم يتم العثور على سند الصرف.")
                return
            voucher = reports.get_issue_voucher_data(s, doc.id)

        path, _ = QFileDialog.getSaveFileName(self, "حفظ سند الصرف كملف PDF", f"voucher_{voucher['number']}.pdf", "*.pdf")
        if path:
            try:
                exports.export_issue_voucher_pdf(path, voucher)
                QMessageBox.information(self, "تم بنجاح", f"تم إنشاء وتصدير سند الصرف المطبوع بنجاح إلى:\n{path}")
            except Exception as e:
                ar_error(self, e)

    def export_excel(self):
        if not self.movements:
            QMessageBox.information(self, "تنبيه", "لا توجد بيانات للتصدير.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ كملف Excel", "movement_history.xlsx", "*.xlsx")
        if path:
            try:
                headers = ["التاريخ والوقت", "كود الصنف", "اسم الصنف", "نوع الحركة", "الكمية", "الدفعة", "سعر الوحدة", "إجمالي القيمة", "الجهة / الطرف", "المستند المرجعي", "المسؤول"]
                rows = [[m["ts"].strftime("%Y-%m-%d %H:%M"), m["item_code"], m["item_name"], m["kind_ar"], m["qty_delta"], m["batch_id"], fmt_egp(m["unit_cost"]), fmt_egp(m["value_delta"]), m["partner"], m["ref_doc"], m["user_name"]] for m in self.movements]
                exports.export_excel(path, "سجل حركة المخزون", headers, rows)
                QMessageBox.information(self, "تم", "تم تصدير سجل حركة المخزون بنجاح.")
            except Exception as e:
                ar_error(self, e)

    def export_pdf(self):
        if not self.movements:
            QMessageBox.information(self, "تنبيه", "لا توجد بيانات للتصدير.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ كملف PDF", "movement_history.pdf", "*.pdf")
        if path:
            try:
                headers = ["التاريخ", "الكود", "الصنف", "الحركة", "الكمية", "سعر الوحدة", "القيمة", "الطرف", "المستند"]
                rows = [[m["move_date"].strftime("%Y-%m-%d"), m["item_code"], m["item_name"], m["kind_ar"], m["qty_delta"], fmt_egp(m["unit_cost"]), fmt_egp(m["value_delta"]), m["partner"], m["ref_doc"]] for m in self.movements[:100]]
                exports.export_pdf(path, "سجل حركة المخزون", headers, rows)
                QMessageBox.information(self, "تم", "تم إنشاء ملف PDF بنجاح.")
            except Exception as e:
                ar_error(self, e)
