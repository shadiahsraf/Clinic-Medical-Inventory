"""Departments and Clinics management page (Arabic RTL, PySide6)."""
from datetime import date, timedelta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QDateEdit
)
from .. import db
from ..models import Department
from ..money import fmt_egp
from ..services import catalog
from .common import Page, kill, ar_error, table


class DepartmentEditDialog(QDialog):
    def __init__(self, parent=None, department=None):
        super().__init__(parent)
        self.department = department
        self.setWindowTitle("تعديل بيانات القسم / العيادة" if department else "إضافة عيادة / قسم جديد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(450, 360)

        f = QFormLayout(self)
        self.name_edit = QLineEdit(department.name if department else "")
        self.type_edit = QLineEdit(department.dept_type or "" if department else "")
        self.doctor_edit = QLineEdit(department.doctor or "" if department else "")
        self.location_edit = QLineEdit(department.location or "" if department else "")
        self.notes_edit = QTextEdit(department.notes or "" if department else "")
        self.notes_edit.setMaximumHeight(80)

        f.addRow("اسم العيادة / القسم *:", self.name_edit)
        f.addRow("النوع (عيادة/قسم/مختبر):", self.type_edit)
        f.addRow("الطبيب / المسؤول (اختياري):", self.doctor_edit)
        f.addRow("الموقع / المبنى:", self.location_edit)
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
            "dept_type": self.type_edit.text().strip() or None,
            "doctor": self.doctor_edit.text().strip() or None,
            "location": self.location_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }


class DepartmentHistoryDialog(QDialog):
    def __init__(self, parent, dept_id, dept_name):
        super().__init__(parent)
        self.dept_id = dept_id
        self.setWindowTitle(f"سجل الصرف واستهلاك: {dept_name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 560)

        lay = QVBoxLayout(self)

        # Date Filter Bar
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("من تاريخ:"))
        self.d1_edit = QDateEdit()
        self.d1_edit.setCalendarPopup(True)
        today = date.today()
        m1 = today.replace(day=1)
        self.d1_edit.setDate(m1)

        filter_bar.addWidget(self.d1_edit)
        filter_bar.addWidget(QLabel("إلى تاريخ:"))
        self.d2_edit = QDateEdit()
        self.d2_edit.setCalendarPopup(True)
        self.d2_edit.setDate(today)
        filter_bar.addWidget(self.d2_edit)

        filter_btn = QPushButton("تصفية وحساب الاستهلاك")
        filter_btn.clicked.connect(self.load_data)
        filter_bar.addWidget(filter_btn)
        lay.addLayout(filter_bar)

        # Summary Frame
        summary_frame = QFrame()
        summary_frame.setObjectName("card")
        sum_lay = QHBoxLayout(summary_frame)

        self.issued_qty_lbl = QLabel("الكميات المصروفة: 0")
        self.returned_qty_lbl = QLabel("الكميات المرتجعة: 0")
        self.net_qty_lbl = QLabel("صافي الكميات: 0")
        self.net_qty_lbl.setStyleSheet("font-weight:bold; color:#24585c;")
        self.cost_lbl = QLabel("تكلفة الاستهلاك (FIFO): 0.00 جنيه")
        self.cost_lbl.setStyleSheet("font-weight:bold; color:#1b4346;")

        for lbl in (self.issued_qty_lbl, self.returned_qty_lbl, self.net_qty_lbl, self.cost_lbl):
            sum_lay.addWidget(lbl)
        lay.addWidget(summary_frame)

        self.table_container = QVBoxLayout()
        lay.addLayout(self.table_container, 1)
        self.t = None

        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn, 0, Qt.AlignCenter)

        self.load_data()

    def load_data(self):
        kill(self.t)
        d1 = self.d1_edit.date().toPython()
        d2 = self.d2_edit.date().toPython()

        with db.session_scope() as s:
            summary = catalog.get_department_consumption_summary(s, self.dept_id, d1, d2)
            history = catalog.get_department_issue_history(s, self.dept_id, d1, d2)

        self.issued_qty_lbl.setText(f"الكميات المصروفة: {summary['issued_qty']}")
        self.returned_qty_lbl.setText(f"الكميات المرتجعة: {summary['returned_qty']}")
        self.net_qty_lbl.setText(f"صافي الاستهلاك: {summary['net_qty']}")
        self.cost_lbl.setText(f"صافي التكلفة (FIFO): {fmt_egp(summary['net_cost'])}")

        headers = ["رقم السند", "تاريخ الصرف", "المستلم", "الأصناف المصروفة", "إجمالي الكمية", "التكلفة (FIFO)"]
        rows = []
        for h in history:
            rows.append([
                h["number"],
                h["issued_at"].strftime("%Y-%m-%d %H:%M"),
                h["recipient"],
                h["items_summary"],
                h["total_qty"],
                fmt_egp(h["total_cost"])
            ])

        self.t = table(headers, rows)
        self.table_container.addWidget(self.t)


class DepartmentsPage(Page):
    def __init__(self, win):
        super().__init__(win, "إدارة العيادات والأقسام")
        self.t = None
        self.departments_list = []

        # Action bar
        bar = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("بحث باسم العيادة أو القسم أو الطبيب أو النوع...")
        self.q.textChanged.connect(self.refresh)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["الكل", "النشطة فقط", "المعطلة فقط"])
        self.status_filter.currentIndexChanged.connect(self.refresh)

        add_btn = QPushButton("إضافة عيادة / قسم جديد")
        add_btn.clicked.connect(self.add_department)

        bar.addWidget(QLabel("بحث:"))
        bar.addWidget(self.q, 2)
        bar.addWidget(QLabel("الحالة:"))
        bar.addWidget(self.status_filter)
        bar.addWidget(add_btn)
        self.lay.addLayout(bar)

        # Control buttons for selected department
        ops_bar = QHBoxLayout()
        self.history_btn = QPushButton("سجل الصرف والاستهلاك")
        self.history_btn.clicked.connect(self.view_history)

        self.edit_btn = QPushButton("تعديل بيانات القسم")
        self.edit_btn.clicked.connect(self.edit_department)

        self.toggle_active_btn = QPushButton("تعطيل / تفعيل")
        self.toggle_active_btn.clicked.connect(self.toggle_active)

        self.delete_btn = QPushButton("حذف القسم")
        self.delete_btn.setObjectName("btn-danger")
        self.delete_btn.clicked.connect(self.delete_department)

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
            depts = catalog.search_departments(s, self.q.text(), active_only=False)
            if active_filter is not None:
                depts = [x for x in depts if x.active is active_filter]

            self.departments_list = [(x.id, x.name, x.dept_type or "", x.doctor or "", x.location or "", x.notes or "", x.active) for x in depts]

            rows = []
            for d in self.departments_list:
                status_str = "نشط" if d[6] else "معطل"
                rows.append([d[0], d[1], d[2], d[3], d[4], d[5], status_str])

        headers = ["المعرف", "اسم العيادة / القسم", "النوع", "الطبيب / المسؤول", "الموقع", "ملاحظات", "الحالة"]
        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.doubleClicked.connect(self.view_history)
        self.table_container.addWidget(self.t)

    def _selected_department(self):
        if not self.t:
            return None
        r = self.t.currentRow()
        if r < 0 or r >= len(self.departments_list):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد قسم أو عيادة من الجدول أولاً.")
            return None
        return self.departments_list[r]

    def add_department(self):
        dlg = DepartmentEditDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            try:
                with db.session_scope() as s:
                    catalog.create_department(s, self.user, **data)
                QMessageBox.information(self, "تم", "تم إضافة العيادة/القسم بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def edit_department(self):
        item = self._selected_department()
        if not item:
            return
        dept_id = item[0]
        with db.session_scope() as s:
            dept = s.get(Department, dept_id)
            if not dept:
                return
            dlg = DepartmentEditDialog(self, dept)
            if dlg.exec():
                data = dlg.get_data()
                try:
                    catalog.update_department(s, self.user, dept_id, **data)
                    QMessageBox.information(self, "تم", "تم تحديث بيانات العيادة/القسم بنجاح.")
                except Exception as e:
                    ar_error(self, e)
                    return
        self.refresh()

    def view_history(self):
        item = self._selected_department()
        if not item:
            return
        dlg = DepartmentHistoryDialog(self, item[0], item[1])
        dlg.exec()

    def toggle_active(self):
        item = self._selected_department()
        if not item:
            return
        dept_id, dept_name, _, _, _, _, is_active = item
        new_state = not is_active
        action_name = "تفعيل" if new_state else "تعطيل"

        reply = QMessageBox.question(
            self, "تأكيد", f"هل أنت متأكد من {action_name} «{dept_name}»؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    catalog.set_department_active(s, self.user, dept_id, new_state)
                QMessageBox.information(self, "تم", f"تم {action_name} العيادة/القسم بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def delete_department(self):
        item = self._selected_department()
        if not item:
            return
        dept_id, dept_name = item[0], item[1]

        reply = QMessageBox.warning(
            self, "تأكيد الحذف",
            f"هل أنت متأكد من حذف «{dept_name}» نهائيًا؟\nملاحظة: لا يمكن حذف القسم إذا كان له حركات صرف سابقة.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    catalog.delete_department(s, self.user, dept_id)
                QMessageBox.information(self, "تم", "تم حذف القسم بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)
