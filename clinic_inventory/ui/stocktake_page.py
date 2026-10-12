"""Stocktaking and Adjustments page (Arabic RTL, PySide6)."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
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


class NewStocktakeDialog(QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("بدء جلسة جرد مخزني جديدة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(480, 250)

        f = QFormLayout(self)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("ملاحظات الجرد (مثال: جرد دوري للربع الأخير)...")
        self.notes_edit.setMaximumHeight(80)

        info = QLabel("سيتم جرد جميع الأصناف النشطة في المخزن وحفظ أرصدتها الدفترية الحالية.")
        info.setStyleSheet("color:#24585c; font-weight:bold;")
        f.addRow(info)
        f.addRow("ملاحظات / وصف الجرد:", self.notes_edit)

        buttons = QDialogButtonBox()
        buttons.addButton("بدء الجرد", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def get_notes(self):
        return self.notes_edit.toPlainText().strip() or None


class StocktakeCountDialog(QDialog):
    def __init__(self, parent, user, session_id):
        super().__init__(parent)
        self.user = user
        self.session_id = session_id
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(980, 620)
        self.session_data = None

        self.lay = QVBoxLayout(self)

        # Header Info Frame
        self.header_frame = QFrame()
        self.header_frame.setObjectName("card")
        self.h_lay = QHBoxLayout(self.header_frame)
        self.title_lbl = QLabel("")
        self.title_lbl.setStyleSheet("font-size:16px; font-weight:bold; color:#1b4346;")
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-weight:bold;")
        self.h_lay.addWidget(self.title_lbl)
        self.h_lay.addStretch()
        self.h_lay.addWidget(self.status_lbl)
        self.lay.addWidget(self.header_frame)

        # Table of lines
        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)
        self.t = None

        # Bottom Action Bar
        self.act_lay = QHBoxLayout()
        self.save_counts_btn = QPushButton("حفظ الكميات والتفسيرات")
        self.save_counts_btn.clicked.connect(self.save_counts)

        self.submit_btn = QPushButton("تقديم الجرد للاعتماد")
        self.submit_btn.clicked.connect(self.submit_session)

        self.approve_btn = QPushButton("اعتماد وتطبيق تسويات الجرد")
        self.approve_btn.setStyleSheet("background:#1e7e34; color:white;")
        self.approve_btn.clicked.connect(self.approve_session)

        self.cancel_session_btn = QPushButton("إلغاء جلسة الجرد")
        self.cancel_session_btn.setObjectName("btn-danger")
        self.cancel_session_btn.clicked.connect(self.cancel_session)

        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.accept)

        self.act_lay.addWidget(self.save_counts_btn)
        self.act_lay.addWidget(self.submit_btn)
        self.act_lay.addWidget(self.approve_btn)
        self.act_lay.addWidget(self.cancel_session_btn)
        self.act_lay.addStretch()
        self.act_lay.addWidget(close_btn)
        self.lay.addLayout(self.act_lay)

        self.load_data()

    def load_data(self):
        kill(self.t)
        with db.session_scope() as s:
            self.session_data = inv.get_stocktake_details(s, self.session_id)

        st = self.session_data["status"]
        st_ar = {"open": "مفتوحة (قيد الجرد)", "submitted": "مقدمة للاعتماد", "approved": "معتمدة ومطبقة", "cancelled": "ملغاة"}
        self.title_lbl.setText(f"جلسة جرد رقم: {self.session_data['number']}")
        self.status_lbl.setText(f"الحالة: {st_ar.get(st, st)}")
        self.setWindowTitle(f"جلسة جرد رقم {self.session_data['number']}")

        is_open = (st == "open")
        is_submitted = (st == "submitted")

        self.save_counts_btn.setEnabled(is_open)
        self.submit_btn.setEnabled(is_open)
        self.approve_btn.setEnabled(is_submitted)
        self.cancel_session_btn.setEnabled(is_open or is_submitted)

        headers = ["الكود", "اسم الصنف", "الوحدة", "الرصيد الدفتري", "الرصيد الفعلي المعدود", "الفارق", "التفسير / مبرر الفرق", "الأثر المالي"]
        lines = self.session_data["lines"]

        self.t = QTableWidget(len(lines), len(headers))
        self.t.setHorizontalHeaderLabels(headers)
        self.t.setLayoutDirection(Qt.RightToLeft)
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.setAlternatingRowColors(True)

        for r, ln in enumerate(lines):
            # Non-editable items
            it_code = QTableWidgetItem(ln["item_code"]); it_code.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); it_code.setTextAlignment(Qt.AlignCenter)
            it_name = QTableWidgetItem(ln["item_name"]); it_name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); it_name.setTextAlignment(Qt.AlignCenter)
            it_unit = QTableWidgetItem(ln["unit_name"]); it_unit.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); it_unit.setTextAlignment(Qt.AlignCenter)
            it_book = QTableWidgetItem(str(ln["book_qty"])); it_book.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); it_book.setTextAlignment(Qt.AlignCenter)

            # Editable Count item
            counted_val = str(ln["counted_qty"]) if ln["counted_qty"] is not None else ""
            it_counted = QTableWidgetItem(counted_val)
            it_counted.setTextAlignment(Qt.AlignCenter)
            if not is_open:
                it_counted.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            # Diff item
            diff_str = ""
            if ln["diff"] is not None:
                diff_str = f"+{ln['diff']}" if ln["diff"] > 0 else str(ln["diff"])
            it_diff = QTableWidgetItem(diff_str)
            it_diff.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_diff.setTextAlignment(Qt.AlignCenter)
            if ln["diff"] is not None and ln["diff"] != 0:
                it_diff.setForeground(QBrush(QColor("#c0392b")))
                it_diff.setBackground(QBrush(QColor("#fde8e7")))

            # Explanation item
            it_expl = QTableWidgetItem(ln["explanation"] or "")
            if not is_open:
                it_expl.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            # Cost effect
            cost_str = fmt_egp(ln["cost_effect"]) if ln["cost_effect"] is not None else "—"
            it_cost = QTableWidgetItem(cost_str)
            it_cost.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_cost.setTextAlignment(Qt.AlignCenter)

            self.t.setItem(r, 0, it_code)
            self.t.setItem(r, 1, it_name)
            self.t.setItem(r, 2, it_unit)
            self.t.setItem(r, 3, it_book)
            self.t.setItem(r, 4, it_counted)
            self.t.setItem(r, 5, it_diff)
            self.t.setItem(r, 6, it_expl)
            self.t.setItem(r, 7, it_cost)

        self.table_container.addWidget(self.t)

    def save_counts(self):
        lines = self.session_data["lines"]
        try:
            with db.session_scope() as s:
                for r, ln in enumerate(lines):
                    cnt_text = self.t.item(r, 4).text().strip()
                    expl_text = self.t.item(r, 6).text().strip()
                    if cnt_text:
                        val = int(cnt_text)
                        inv.record_count(s, self.user, self.session_id, ln["item_id"], val, expl_text or None)
            QMessageBox.information(self, "تم", "تم حفظ الكميات والتفسيرات بنجاح.")
            self.load_data()
        except ValueError:
            QMessageBox.warning(self, "خطأ", "يرجى التأكد من إدخال أرقام صحيحة للكميات المعدودة.")
        except Exception as e:
            ar_error(self, e)

    def submit_session(self):
        # Save first
        self.save_counts()
        try:
            with db.session_scope() as s:
                inv.submit_stocktake(s, self.user, self.session_id)
            QMessageBox.information(self, "تم", "تم تقديم الجرد للاعتماد بنجاح.")
            self.load_data()
        except Exception as e:
            ar_error(self, e)

    def approve_session(self):
        reply = QMessageBox.question(
            self, "تأكيد الاعتماد",
            "سيؤدي اعتماد الجرد إلى تطبيق تسويات المخزون (خصم العجز بنظام FIFO وإضافة الزيادات بدفعات تسوية).\nهل أنت متأكد من المتابعة؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    inv.approve_stocktake(s, self.user, self.session_id)
                QMessageBox.information(self, "تم", "تم اعتماد الجرد وتطبيق التسويات المخزنية بنجاح.")
                self.load_data()
            except Exception as e:
                ar_error(self, e)

    def cancel_session(self):
        reply = QMessageBox.warning(
            self, "تأكيد الإلغاء",
            "هل أنت متأكد من إلغاء جلسة الجرد الحالية؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    inv.cancel_stocktake(s, self.user, self.session_id, reason="إلغاء يدوي")
                QMessageBox.information(self, "تم", "تم إلغاء جلسة الجرد.")
                self.load_data()
            except Exception as e:
                ar_error(self, e)


class StocktakePage(Page):
    def __init__(self, win):
        super().__init__(win, "الجرد والتسويات")
        self.t = None
        self.sessions = []

        # Action bar
        bar = QHBoxLayout()
        add_btn = QPushButton("بدء جلسة جرد جديدة")
        add_btn.clicked.connect(self.new_session)

        open_btn = QPushButton("فتح جلسة الجرد المحددة")
        open_btn.clicked.connect(self.open_selected)

        bar.addWidget(add_btn)
        bar.addWidget(open_btn)
        bar.addStretch()
        self.lay.addLayout(bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        kill(self.t)
        with db.session_scope() as s:
            self.sessions = inv.list_stocktake_sessions(s)

        st_ar = {"open": "مفتوحة (قيد الجرد)", "submitted": "مقدمة للاعتماد", "approved": "معتمدة", "cancelled": "ملغاة"}
        headers = ["المعرف", "رقم الجلسة", "تاريخ الإنشاء", "الحالة", "إجمالي الأصناف", "الأصناف المعدودة", "وجود فروق", "أنشأها", "المعتمد", "ملاحظات"]
        rows = []
        for ss in self.sessions:
            diff_str = "يوجد فروق" if ss["has_diff"] else "مطابق"
            rows.append([
                ss["id"],
                ss["number"],
                ss["created_at"].strftime("%Y-%m-%d %H:%M"),
                st_ar.get(ss["status"], ss["status"]),
                ss["total_items"],
                ss["counted_items"],
                diff_str,
                ss["creator_name"],
                ss["approver_name"] or "—",
                ss["notes"]
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.doubleClicked.connect(self.open_selected)
        self.table_container.addWidget(self.t)

    def _selected_session(self):
        if not self.t:
            return None
        r = self.t.currentRow()
        if r < 0 or r >= len(self.sessions):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد جلسة جرد من الجدول أولاً.")
            return None
        return self.sessions[r]

    def new_session(self):
        dlg = NewStocktakeDialog(self, self.user)
        if dlg.exec():
            notes = dlg.get_notes()
            try:
                with db.session_scope() as s:
                    ss = inv.start_stocktake(s, self.user, notes=notes)
                    sid = ss.id
                    num = ss.number
                QMessageBox.information(self, "تم", f"تم إنشاء جلسة الجرد رقم {num} بنجاح.")
                self.refresh()
                dlg_count = StocktakeCountDialog(self, self.user, sid)
                dlg_count.exec()
                self.win.after_stock_change()
            except Exception as e:
                ar_error(self, e)

    def open_selected(self):
        item = self._selected_session()
        if not item:
            return
        dlg = StocktakeCountDialog(self, self.user, item["id"])
        dlg.exec()
        self.win.after_stock_change()
