"""Returns management page (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QSpinBox, QDateEdit
)
from .. import db
from ..money import fmt_egp
from ..services import inventory as inv
from .common import Page, kill, ar_error, table


class NewReturnDialog(QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("تسجيل مرتجع جديد من عيادة / قسم")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(750, 520)

        lay = QVBoxLayout(self)

        # Step 1: Select Issue Document
        f = QFormLayout()
        self.issue_combo = QComboBox()
        self.issue_combo.currentIndexChanged.connect(self.on_issue_selected)
        f.addRow("سند الصرف الأصلي *:", self.issue_combo)

        self.dept_lbl = QLabel("—")
        f.addRow("القسم / العيادة:", self.dept_lbl)

        # Step 2: Select Line
        self.line_combo = QComboBox()
        self.line_combo.currentIndexChanged.connect(self.on_line_selected)
        f.addRow("الصنف المرتجع *:", self.line_combo)

        self.eligible_lbl = QLabel("الكمية المتاحة للإرجاع: 0")
        self.eligible_lbl.setStyleSheet("font-weight:bold; color:#24585c;")
        f.addRow("الحد الأقصى للإرجاع:", self.eligible_lbl)

        # Step 3: Enter Qty & Condition
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1000000)
        f.addRow("كمية المرتجع *:", self.qty_spin)

        self.cond_combo = QComboBox()
        self.cond_combo.addItem("صالح للاستخدام (يعود للمخزون بالدفعة الأصلية)", "reusable")
        self.cond_combo.addItem("تالف / غير صالح (لا يعود للمخزون)", "damaged")
        f.addRow("حالة الصنف *:", self.cond_combo)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(date.today())
        f.addRow("تاريخ الإرجاع:", self.date_edit)

        self.reason_edit = QTextEdit()
        self.reason_edit.setPlaceholderText("سبب الإرجاع أو ملاحظات...")
        self.reason_edit.setMaximumHeight(70)
        f.addRow("السبب / الملاحظات:", self.reason_edit)

        user_info = QLabel(f"المستخدم المسجل: {user.display_name}")
        user_info.setStyleSheet("color:#666;")
        f.addRow("", user_info)

        lay.addLayout(f)

        buttons = QDialogButtonBox()
        self.ok_btn = buttons.addButton("تأكيد تسجيل المرتجع", QDialogButtonBox.AcceptRole)
        self.cancel_btn = buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.confirm_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.issue_docs = []
        self.load_issues()

    def load_issues(self):
        with db.session_scope() as s:
            self.issue_docs = inv.get_issue_docs_for_return(s)

        self.issue_combo.clear()
        if not self.issue_docs:
            self.issue_combo.addItem("لا توجد سندات صرف بها كميات قابلة للإرجاع", None)
            self.ok_btn.setEnabled(False)
            return

        for doc in self.issue_docs:
            self.issue_combo.addItem(f"{doc['number']} — {doc['department_name']} ({doc['issued_at'].strftime('%Y-%m-%d')})", doc["doc_id"])

    def on_issue_selected(self, idx):
        if idx < 0 or idx >= len(self.issue_docs):
            self.line_combo.clear()
            self.dept_lbl.setText("—")
            return
        doc = self.issue_docs[idx]
        self.dept_lbl.setText(f"{doc['department_name']} (المستلم: {doc['recipient']})")
        self.line_combo.clear()
        for line in doc["lines"]:
            self.line_combo.addItem(
                f"{line['item_code']} - {line['item_name']} (متاح: {line['eligible_qty']} من {line['issued_qty']})",
                line
            )

    def on_line_selected(self, idx):
        line = self.line_combo.currentData()
        if line:
            self.eligible_lbl.setText(f"الكمية المتاحة للإرجاع: {line['eligible_qty']} {line['unit_name']}")
            self.qty_spin.setMaximum(line["eligible_qty"])
            self.qty_spin.setValue(min(1, line["eligible_qty"]))
        else:
            self.eligible_lbl.setText("الكمية المتاحة للإرجاع: 0")

    def confirm_and_accept(self):
        line = self.line_combo.currentData()
        if not line:
            QMessageBox.warning(self, "تنبيه", "يرجى تحديد صنف من السند.")
            return

        qty = self.qty_spin.value()
        if qty > line["eligible_qty"]:
            QMessageBox.warning(self, "خطأ", f"لا يمكن إرجاع كمية أكبر من المتاح ({line['eligible_qty']}).")
            return

        cond_text = self.cond_combo.currentText()
        summary = (
            f"ملخص المرتجع:\n"
            f"• السند الأصلي: {self.issue_combo.currentText()}\n"
            f"• الصنف: {line['item_name']}\n"
            f"• الكمية المرتجعة: {qty} {line['unit_name']}\n"
            f"• الحالة: {cond_text}\n"
            f"• التاريخ: {self.date_edit.date().toString('yyyy-MM-dd')}\n\n"
            f"هل تريد تأكيد تسجيل المرتجع؟"
        )
        reply = QMessageBox.question(self, "تأكيد تسجيل المرتجع", summary, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.accept()

    def get_data(self):
        line = self.line_combo.currentData()
        return {
            "issue_line_id": line["line_id"],
            "quantity": self.qty_spin.value(),
            "condition": self.cond_combo.currentData(),
            "reason": self.reason_edit.toPlainText().strip() or None,
            "return_date": self.date_edit.date().toPython()
        }


class ReturnsPage(Page):
    def __init__(self, win):
        super().__init__(win, "المرتجعات")
        self.t = None
        self.returns_list = []

        # Top Bar
        bar = QHBoxLayout()
        self.status_combo = QComboBox()
        self.status_combo.addItems(["الكل", "معلق (بانتظار الاعتماد)", "معتمد", "مرفوض"])
        self.status_combo.currentIndexChanged.connect(self.refresh)

        add_btn = QPushButton("تسجيل مرتجع جديد")
        add_btn.clicked.connect(self.new_return)

        bar.addWidget(QLabel("تصفية حسب الحالة:"))
        bar.addWidget(self.status_combo)
        bar.addStretch()
        bar.addWidget(add_btn)
        self.lay.addLayout(bar)

        # Actions Bar
        actions_bar = QHBoxLayout()
        self.approve_btn = QPushButton("اعتماد المرتجع")
        self.approve_btn.clicked.connect(lambda: self.process_approval(True))

        self.reject_btn = QPushButton("رفض المرتجع")
        self.reject_btn.setObjectName("btn-danger")
        self.reject_btn.clicked.connect(lambda: self.process_approval(False))

        actions_bar.addWidget(self.approve_btn)
        actions_bar.addWidget(self.reject_btn)
        actions_bar.addStretch()
        self.lay.addLayout(actions_bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        kill(self.t)
        idx = self.status_combo.currentIndex()
        status_filter = [None, "pending", "approved", "rejected"][idx]

        with db.session_scope() as s:
            self.returns_list = inv.list_returns(s, status=status_filter)

        status_ar = {"pending": "معلق", "approved": "معتمد", "rejected": "مرفوض"}
        cond_ar = {"reusable": "صالح للاستخدام", "damaged": "تالف / هالك"}

        headers = ["رقم المرتجع", "التاريخ", "العيادة / القسم", "الكود", "الصنف", "الكمية", "الحالة الفنية", "قيمة المرتجع", "الحالة", "المسؤول", "المعتمد"]
        rows = []
        for r in self.returns_list:
            cost_str = fmt_egp(r["cost"]) if r["cost"] else "—"
            rows.append([
                r["number"],
                r["return_date"].strftime("%Y-%m-%d"),
                r["dept_name"],
                r["item_code"],
                r["item_name"],
                r["quantity"],
                cond_ar.get(r["condition"], r["condition"]),
                cost_str,
                status_ar.get(r["status"], r["status"]),
                r["creator_name"],
                r["approver_name"]
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_container.addWidget(self.t)

    def _selected_return(self):
        if not self.t:
            return None
        r = self.t.currentRow()
        if r < 0 or r >= len(self.returns_list):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد مرتجع من الجدول أولاً.")
            return None
        return self.returns_list[r]

    def new_return(self):
        dlg = NewReturnDialog(self, self.user)
        if dlg.exec():
            data = dlg.get_data()
            try:
                with db.session_scope() as s:
                    ret = inv.record_return(s, self.user, **data)
                    num = ret.number
                QMessageBox.information(self, "تم", f"تم تسجيل المرتجع رقم {num} بنجاح وهو بانتظار الاعتماد.")
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)

    def process_approval(self, approve: bool):
        item = self._selected_return()
        if not item:
            return
        ret_id = item["id"]
        if item["status"] != "pending":
            QMessageBox.warning(self, "تنبيه", "تمت معالجة هذا المرتجع مسبقًا.")
            return

        action_name = "اعتماد" if approve else "رفض"
        reply = QMessageBox.question(
            self, "تأكيد", f"هل أنت متأكد من {action_name} المرتجع رقم {item['number']}؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    inv.approve_return(s, self.user, ret_id, approve=approve)
                QMessageBox.information(self, "تم", f"تم {action_name} المرتجع بنجاح.")
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)
