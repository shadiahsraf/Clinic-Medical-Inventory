"""Damaged and Unusable Supplies page (Arabic RTL, PySide6)."""
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
from ..services import catalog, inventory as inv
from .common import Page, kill, ar_error, table


class RecordDamageDialog(QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("تسجيل هالك / تالف / منتهي الصلاحية")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(650, 480)

        lay = QVBoxLayout(self)
        f = QFormLayout()

        # Item Selection
        self.item_combo = QComboBox()
        self.item_combo.currentIndexChanged.connect(self.on_item_changed)
        f.addRow("الصنف *:", self.item_combo)

        # Batch Selection
        self.batch_combo = QComboBox()
        self.batch_combo.currentIndexChanged.connect(self.on_batch_changed)
        f.addRow("الدفعة *:", self.batch_combo)

        self.batch_info_lbl = QLabel("الرصيد المتاح في الدفعة: 0 | سعر الوحدة: 0.00 جنيه")
        self.batch_info_lbl.setStyleSheet("font-weight:bold; color:#24585c;")
        f.addRow("بيانات الدفعة:", self.batch_info_lbl)

        # Quantity
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1000000)
        self.qty_spin.valueChanged.connect(self.update_cost_preview)
        f.addRow("الكمية التالفة / الهالكة *:", self.qty_spin)

        # Cost Preview
        self.cost_preview_lbl = QLabel("تكلفة الكمية التالفة: 0.00 جنيه")
        self.cost_preview_lbl.setStyleSheet("font-weight:bold; color:#c0392b; font-size:15px;")
        f.addRow("التكلفة المخزنية للكمية:", self.cost_preview_lbl)

        # Reason Type
        self.reason_type_combo = QComboBox()
        self.reason_type_combo.addItem("تالف (كسر / فساد / عيب تخزين)", "damaged")
        self.reason_type_combo.addItem("منتهي الصلاحية", "expired")
        self.reason_type_combo.addItem("مفقود / عجز مخزني", "lost")
        self.reason_type_combo.addItem("أخرى", "other")
        f.addRow("نوع السبب *:", self.reason_type_combo)

        # Reason text
        self.reason_text = QTextEdit()
        self.reason_text.setPlaceholderText("اكتب تفاصيل سبب الاستبعاد أو الهالك...")
        self.reason_text.setMaximumHeight(70)
        f.addRow("التفاصيل / المبرر:", self.reason_text)

        # Event date
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(date.today())
        f.addRow("تاريخ الواقعة:", self.date_edit)

        user_info = QLabel(f"المستخدم المسؤول: {user.display_name}")
        user_info.setStyleSheet("color:#666;")
        f.addRow("", user_info)

        lay.addLayout(f)

        buttons = QDialogButtonBox()
        self.ok_btn = buttons.addButton("تأكيد استبعاد الهالك", QDialogButtonBox.AcceptRole)
        self.cancel_btn = buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.confirm_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.batches = []
        self.load_items()

    def load_items(self):
        with db.session_scope() as s:
            items = catalog.search_items(s, active_only=True)
            for it in items:
                self.item_combo.addItem(f"{it.code} - {it.name}", it.id)

    def on_item_changed(self, idx):
        item_id = self.item_combo.currentData()
        self.batch_combo.clear()
        if not item_id:
            return
        with db.session_scope() as s:
            self.batches = inv.list_batches_for_damage(s, item_id)

        if not self.batches:
            self.batch_combo.addItem("لا توجد دفعات نشطة بها رصيد لهذا الصنف", None)
            self.batch_info_lbl.setText("لا يوجد رصيد متاح")
            self.ok_btn.setEnabled(False)
            return

        self.ok_btn.setEnabled(True)
        for b in self.batches:
            exp_str = f" | صلاحية: {b['expiry_date'].strftime('%Y-%m-%d')}" if b['expiry_date'] else ""
            self.batch_combo.addItem(
                f"دفعة #{b['id']} (المتبقي: {b['remaining_qty']} | الوحدة: {fmt_egp(b['unit_cost'])}{exp_str})",
                b
            )

    def on_batch_changed(self, idx):
        b = self.batch_combo.currentData()
        if b:
            exp_str = f" | تاريخ الصلاحية: {b['expiry_date'].strftime('%Y-%m-%d')}" if b['expiry_date'] else ""
            self.batch_info_lbl.setText(f"الرصيد المتاح: {b['remaining_qty']} | سعر الوحدة: {fmt_egp(b['unit_cost'])}{exp_str}")
            self.qty_spin.setMaximum(b["remaining_qty"])
            self.qty_spin.setValue(min(1, b["remaining_qty"]))
        else:
            self.batch_info_lbl.setText("لا يوجد رصيد متاح")
        self.update_cost_preview()

    def update_cost_preview(self):
        b = self.batch_combo.currentData()
        if b:
            qty = self.qty_spin.value()
            cost = qty * b["unit_cost"]
            self.cost_preview_lbl.setText(f"التكلفة المخزنية للكمية: {fmt_egp(cost)}")
        else:
            self.cost_preview_lbl.setText("التكلفة المخزنية للكمية: 0.00 جنيه")

    def confirm_and_accept(self):
        b = self.batch_combo.currentData()
        if not b:
            QMessageBox.warning(self, "تنبيه", "يرجى تحديد دفعة صحيحة.")
            return

        qty = self.qty_spin.value()
        cost = qty * b["unit_cost"]
        summary = (
            f"تأكيد استبعاد هالك:\n"
            f"• الصنف: {self.item_combo.currentText()}\n"
            f"• الدفعة: #{b['id']}\n"
            f"• الكمية المستبعدة: {qty}\n"
            f"• التكلفة الإجمالية: {fmt_egp(cost)}\n"
            f"• السبب: {self.reason_type_combo.currentText()}\n\n"
            f"هل أنت متأكد من خصم هذه الكمية نهائيًا من المخزون؟"
        )
        reply = QMessageBox.warning(self, "تأكيد استبعاد الهالك", summary, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.accept()

    def get_data(self):
        b = self.batch_combo.currentData()
        return {
            "batch_id": b["id"],
            "quantity": self.qty_spin.value(),
            "reason_type": self.reason_type_combo.currentData(),
            "reason": self.reason_text.toPlainText().strip() or None,
            "event_date": self.date_edit.date().toPython()
        }


class DamagePage(Page):
    def __init__(self, win):
        super().__init__(win, "الهالك والتالف")
        self.t = None
        self.records = []

        # Action bar
        bar = QHBoxLayout()
        add_btn = QPushButton("تسجيل هالك / تالف جديد")
        add_btn.clicked.connect(self.new_damage)
        bar.addStretch()
        bar.addWidget(add_btn)
        self.lay.addLayout(bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        kill(self.t)
        with db.session_scope() as s:
            self.records = inv.list_damage_records(s)

        type_ar = {"damaged": "تالف", "expired": "منتهي الصلاحية", "lost": "مفقود / عجز", "other": "أخرى"}
        headers = ["المعرف", "تاريخ الواقعة", "كود الصنف", "اسم الصنف", "رقم الدفعة", "الكمية", "نوع السبب", "التفاصيل", "التكلفة", "المسؤول", "المعتمد"]
        rows = []
        for r in self.records:
            rows.append([
                r["id"],
                r["event_date"].strftime("%Y-%m-%d"),
                r["item_code"],
                r["item_name"],
                f"#{r['batch_id']}",
                r["quantity"],
                type_ar.get(r["reason_type"], r["reason_type"]),
                r["reason"],
                fmt_egp(r["cost"]),
                r["reporter_name"],
                r["approver_name"] or "—"
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_container.addWidget(self.t)

    def new_damage(self):
        dlg = RecordDamageDialog(self, self.user)
        if dlg.exec():
            data = dlg.get_data()
            try:
                with db.session_scope() as s:
                    rec = inv.record_damage(s, self.user, **data)
                    cost_str = fmt_egp(rec.cost)
                QMessageBox.information(self, "تم", f"تم تسجيل الهالك بنجاح وتخفيض الرصيد المخزني.\nالتكلفة المخزنية: {cost_str}")
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)
