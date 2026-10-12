"""Arabic RTL desktop shell (PySide6). UI only calls services; no business rules here."""
import os, sys, uuid
from datetime import date
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QLineEdit, QComboBox, QSpinBox,
    QDialog, QFormLayout, QMessageBox, QDialogButtonBox, QSystemTrayIcon, QFileDialog, QHeaderView,
    QAbstractItemView, QGridLayout, QFrame, QDoubleSpinBox, QScrollArea)
from sqlalchemy import select
from .. import bootstrap, db
from ..errors import AppError
from ..models import Item, Department, Supplier, IncomingDoc, IssueDoc, User
from ..money import fmt_egp, to_e4
from ..services import auth, catalog, inventory as inv, alerts, reports, exports
from ..services.common import available_qty

from .departments_page import DepartmentsPage
from .suppliers_page import SuppliersPage
from .donations_page import DonationsPage
from .returns_page import ReturnsPage
from .damage_page import DamagePage
from .stocktake_page import StocktakePage
from .movement_history_page import MovementHistoryPage
from .users_page import UsersPage
from .backup_page import BackupPage
from .settings_page import SettingsPage

APP_TITLE = "نظام إدارة مخزن المستلزمات الطبية"
STYLE = """
* { font-size: 14px; }
QMainWindow, QWidget#page { background: #f4f7f7; }
QWidget#sidebar { background: #24585c; }
QPushButton#nav { color: #e8f2f2; background: transparent; border: none; padding: 7px 12px; text-align: right; font-size: 13px; }
QPushButton#nav:hover { background: #2f6f73; } QPushButton#nav:checked { background: #1b4346; font-weight: bold; }
QLabel#title { font-size: 22px; font-weight: bold; color: #1b4346; }
QFrame#card { background: white; border: 1px solid #d9e3e3; border-radius: 8px; }
QPushButton { background: #2f6f73; color: white; border: none; border-radius: 6px; padding: 8px 18px; }
QPushButton:hover { background: #24585c; }
QTableWidget { background: white; gridline-color: #e3eaea; alternate-background-color: #f7fafa; }
QHeaderView::section { background: #e4eeee; padding: 6px; border: none; font-weight: bold; }
"""


def kill(w):
    """Detach immediately (deleteLater alone leaves the old widget painted until the event loop runs)."""
    if w is not None:
        w.hide(); w.setParent(None); w.deleteLater()


def ar_error(parent, e: Exception):
    msg = e.message_ar if isinstance(e, AppError) else "حدث خطأ غير متوقع. تم حفظ بياناتك، ويرجى إبلاغ المسؤول."
    QMessageBox.warning(parent, "تنبيه", msg)


def table(headers, rows):
    t = QTableWidget(len(rows), len(headers)); t.setHorizontalHeaderLabels(headers)
    t.setLayoutDirection(Qt.RightToLeft); t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.setSortingEnabled(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem(str(v)); it.setTextAlignment(Qt.AlignCenter); t.setItem(r, c, it)
    return t


class Login(QDialog):
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP_TITLE); self.user = None
        self.setLayoutDirection(Qt.RightToLeft)
        f = QFormLayout(self); self.u = QLineEdit(); self.p = QLineEdit(); self.p.setEchoMode(QLineEdit.Password)
        f.addRow("اسم المستخدم", self.u); f.addRow("كلمة المرور", self.p)
        b = QDialogButtonBox(); ok = b.addButton("دخول", QDialogButtonBox.AcceptRole)
        b.addButton("إلغاء", QDialogButtonBox.RejectRole); f.addRow(b)
        b.accepted.connect(self.go); b.rejected.connect(self.reject)

    def go(self):
        try:
            with db.session_scope() as s:
                u = auth.login(s, self.u.text(), self.p.text()); s.expunge(u); self.user = u
            self.accept()
        except Exception as e:
            ar_error(self, e)


class FirstRun(QDialog):
    """Create the first administrator when the database is empty."""
    def __init__(self):
        super().__init__(); self.setWindowTitle("إعداد أول مستخدم"); self.setLayoutDirection(Qt.RightToLeft)
        f = QFormLayout(self); self.n = QLineEdit(); self.u = QLineEdit(); self.p = QLineEdit()
        self.p.setEchoMode(QLineEdit.Password)
        f.addRow("الاسم الكامل", self.n); f.addRow("اسم المستخدم", self.u); f.addRow("كلمة المرور (6 أحرف على الأقل)", self.p)
        b = QDialogButtonBox(); b.addButton("إنشاء", QDialogButtonBox.AcceptRole); f.addRow(b); b.accepted.connect(self.go)

    def go(self):
        try:
            with db.session_scope() as s:
                auth.create_user(s, None, self.u.text(), self.n.text(), self.p.text(), "مدير النظام")
            self.accept()
        except Exception as e:
            ar_error(self, e)


class Page(QWidget):
    def __init__(self, win, title):
        super().__init__(); self.setObjectName("page"); self.win = win; self.user = win.user
        self.lay = QVBoxLayout(self); self.lay.setAlignment(Qt.AlignTop); h = QLabel(title); h.setObjectName("title"); self.lay.addWidget(h)

    def refresh(self): pass
    def clear_below(self, keep=1):
        while self.lay.count() > keep:
            w = self.lay.takeAt(self.lay.count() - 1).widget()
            kill(w)


class DashboardPage(Page):
    def __init__(self, win):
        super().__init__(win, "لوحة التحكم"); self.grid = QGridLayout(); self.lay.addLayout(self.grid); self.lay.addStretch()

    def refresh(self):
        with db.session_scope() as s:
            d = reports.dashboard(s)
        cards = [("إجمالي عدد الأصناف", d["total_items"]), ("الأصناف المتاحة", d["available"]),
                 ("مخزون منخفض", d["low"]), ("نفد المخزون", d["out"]), ("قريبة من انتهاء الصلاحية", d["near_expiry"]),
                 ("إجمالي قيمة المخزون", fmt_egp(d["inventory_value"])),
                 ("مشتريات الشهر", fmt_egp(d["purchases_month"])),
                 ("تبرعات عينية (تقديرية) هذا الشهر", fmt_egp(d["donations_month"])),
                 ("تكلفة المصروف هذا الشهر", fmt_egp(d["issue_cost_month"])),
                 ("الكميات الواردة هذا الشهر", d["incoming_qty_month"]),
                 ("الكميات المنصرفة هذا الشهر", d["issued_qty_month"])]
        while self.grid.count():
            kill(self.grid.takeAt(0).widget())
        for i, (k, v) in enumerate(cards):
            c = QFrame(); c.setObjectName("card"); l = QVBoxLayout(c)
            a = QLabel(k); b = QLabel(str(v)); b.setStyleSheet("font-size:22px;font-weight:bold;color:#24585c")
            l.addWidget(a); l.addWidget(b); self.grid.addWidget(c, i // 3, i % 3)


class ItemsPage(Page):
    def __init__(self, win):
        super().__init__(win, "إدارة الأصناف")
        bar = QHBoxLayout(); self.q = QLineEdit(); self.q.setPlaceholderText("بحث بالكود أو الاسم أو الباركود (يدوي أو عبر الماسح الضوئي)")
        self.q.textChanged.connect(self.refresh); add = QPushButton("إضافة صنف"); add.clicked.connect(self.add)
        btn_single_bc = QPushButton("طباعة ملصق باركود"); btn_single_bc.clicked.connect(self.print_single_barcode)
        btn_sheet_bc = QPushButton("طباعة صفحة ملصقات A4"); btn_sheet_bc.clicked.connect(self.print_sheet_barcodes)
        bar.addWidget(self.q, 2); bar.addWidget(add); bar.addWidget(btn_single_bc); bar.addWidget(btn_sheet_bc)
        self.lay.addLayout(bar); self.t = None; self.items_list = []

    def refresh(self):
        kill(self.t)
        with db.session_scope() as s:
            items = catalog.search_items(s, self.q.text())
            self.items_list = [{"id": i.id, "code": i.code, "name": i.name, "barcode": i.barcode} for i in items]
            rows = [[i.code, i.name, i.category.name if i.category else "", i.unit.name, available_qty(s, i.id), i.min_stock, i.barcode or "—"]
                    for i in items]
        self.t = table(["الكود", "الصنف", "التصنيف", "الوحدة", "الرصيد المتاح", "الحد الأدنى", "الباركود"], rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lay.addWidget(self.t, 1)

    def print_single_barcode(self):
        r = self.t.currentRow() if self.t else -1
        if r < 0 or r >= len(self.items_list):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد صنف من الجدول أولاً.")
            return
        it = self.items_list[r]
        path, _ = QFileDialog.getSaveFileName(self, "حفظ ملصق الباركود", f"barcode_{it['code']}.pdf", "*.pdf")
        if path:
            from ..services import barcodes
            try:
                barcodes.generate_single_label_pdf(path, it)
                QMessageBox.information(self, "تم", f"تم إنشاء ملصق الباركود بنجاح في:\n{path}")
            except Exception as e:
                ar_error(self, e)

    def print_sheet_barcodes(self):
        if not self.items_list:
            QMessageBox.information(self, "تنبيه", "لا توجد أصناف للطباعة.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ صفحة ملصقات الباركود A4", "barcodes_sheet.pdf", "*.pdf")
        if path:
            from ..services import barcodes
            try:
                barcodes.generate_sheet_labels_pdf(path, self.items_list, copies_per_item=2)
                QMessageBox.information(self, "تم", f"تم إنشاء صفحة ملصقات الباركود بنجاح في:\n{path}")
            except Exception as e:
                ar_error(self, e)

    def add(self):
        d = QDialog(self); d.setLayoutDirection(Qt.RightToLeft); d.setWindowTitle("إضافة صنف"); f = QFormLayout(d)
        n, u, c, bc = QLineEdit(), QLineEdit("علبة"), QLineEdit(), QLineEdit(); m = QSpinBox(); m.setMaximum(10**6)
        for k, w in [("اسم الصنف", n), ("الوحدة", u), ("التصنيف", c), ("الباركود (اختياري)", bc), ("الحد الأدنى للمخزون", m)]:
            f.addRow(k, w)
        b = QDialogButtonBox(); b.addButton("حفظ", QDialogButtonBox.AcceptRole); b.addButton("إلغاء", QDialogButtonBox.RejectRole)
        f.addRow(b); b.accepted.connect(d.accept); b.rejected.connect(d.reject)
        if d.exec():
            try:
                with db.session_scope() as s:
                    catalog.create_item(s, self.user, n.text(), u.text(), c.text() or None, m.value(), bc.text())
                self.refresh()
            except Exception as e:
                ar_error(self, e)


class IncomingPage(Page):
    def __init__(self, win):
        super().__init__(win, "الوارد إلى المخزن")
        f = QFormLayout(); self.src = QComboBox(); self.src.addItems(["شراء", "تبرع عيني"])
        self.sup = QComboBox(); self.item = QComboBox(); self.qty = QSpinBox(); self.qty.setRange(1, 10**6)
        self.cost = QDoubleSpinBox(); self.cost.setDecimals(4); self.cost.setMaximum(10**7)
        self.paid = QDoubleSpinBox(); self.paid.setDecimals(2); self.paid.setMaximum(10**9)
        self.donor = QLineEdit(); self.ref = QLineEdit(); self.exp = QLineEdit(); self.exp.setPlaceholderText("YYYY-MM-DD (اختياري)")
        for k, w in [("نوع الوارد", self.src), ("المورد", self.sup), ("اسم المتبرع", self.donor), ("رقم الفاتورة/المرجع", self.ref),
                     ("الصنف", self.item), ("الكمية", self.qty), ("سعر الوحدة / القيمة التقديرية", self.cost),
                     ("المبلغ المدفوع فعليًا", self.paid), ("تاريخ الصلاحية", self.exp)]:
            f.addRow(k, w)
        self.lay.addLayout(f); b = QPushButton("تأكيد الوارد"); b.clicked.connect(self.save); self.lay.addWidget(b); self.lay.addStretch()

    def refresh(self):
        with db.session_scope() as s:
            self.sup.clear(); self.item.clear()
            for x in s.scalars(select(Supplier).where(Supplier.active)): self.sup.addItem(x.name, x.id)
            for x in catalog.search_items(s): self.item.addItem(f"{x.code} - {x.name}", x.id)

    def save(self):
        try:
            purchase = self.src.currentIndex() == 0
            exp = date.fromisoformat(self.exp.text()) if self.exp.text().strip() else None
            with db.session_scope() as s:
                doc = inv.create_incoming(s, self.user, "purchase" if purchase else "donation", date.today(),
                    [dict(item_id=self.item.currentData(), quantity=self.qty.value(),
                          unit_cost=to_e4(str(self.cost.value())), expiry_date=exp)],
                    supplier_id=self.sup.currentData() if purchase else None,
                    donor_name=None if purchase else self.donor.text(), reference=self.ref.text())
                inv.confirm_incoming(s, self.user, doc.id, paid_now=to_e4(str(self.paid.value())) if purchase else 0)
                num = doc.number
            QMessageBox.information(self, "تم", f"تم تأكيد الوارد رقم {num}")
            self.win.after_stock_change()
        except ValueError:
            QMessageBox.warning(self, "تنبيه", "صيغة التاريخ غير صحيحة.")
        except Exception as e:
            ar_error(self, e)


class IssuePage(Page):
    def __init__(self, win):
        super().__init__(win, "صرف المستلزمات")
        f = QFormLayout(); self.dept = QComboBox(); self.rec = QLineEdit(); self.note = QLineEdit()
        f.addRow("العيادة / القسم", self.dept); f.addRow("المستلم (اختياري)", self.rec); f.addRow("ملاحظات", self.note)
        self.lay.addLayout(f)
        bar = QHBoxLayout(); self.item = QComboBox(); self.item.setEditable(True); self.qty = QSpinBox(); self.qty.setRange(1, 10**6)
        add = QPushButton("إضافة للسند"); add.clicked.connect(self.add_line); bar.addWidget(self.item, 3); bar.addWidget(self.qty); bar.addWidget(add)
        self.lay.addLayout(bar); self.lines = []; self.t = None; self.key = uuid.uuid4().hex
        self.confirm = QPushButton("تأكيد الصرف"); self.confirm.clicked.connect(self.save); self.lay.addWidget(self.confirm)

    def refresh(self):
        with db.session_scope() as s:
            self.dept.clear(); self.item.clear()
            for d in s.scalars(select(Department).where(Department.active)): self.dept.addItem(d.name, d.id)
            for x in catalog.search_items(s): self.item.addItem(f"{x.code} - {x.name}  (المتاح: {available_qty(s, x.id)})", x.id)
        self.show_lines()

    def show_lines(self):
        kill(self.t)
        self.t = table(["الصنف", "الكمية"], [[n, q] for _, n, q in self.lines]); self.lay.insertWidget(self.lay.count() - 1, self.t, 1)

    def add_line(self):
        if self.item.currentData() is None: return
        self.lines.append((self.item.currentData(), self.item.currentText().split("  (")[0], self.qty.value())); self.show_lines()

    def save(self):
        self.confirm.setEnabled(False)            # block double clicks; idempotency key protects retries
        try:
            with db.session_scope() as s:
                doc = inv.create_issue(s, self.user, self.dept.currentData(),
                    [dict(item_id=i, quantity=q) for i, _, q in self.lines], self.rec.text() or None,
                    notes=self.note.text() or None, idempotency_key=self.key)
                num, cost, doc_id = doc.number, doc.total_cost, doc.id
            ans = QMessageBox.question(
                self, "تم الصرف بنجاح",
                f"تم الصرف بنجاح.\nرقم السند: {num}\nالتكلفة: {fmt_egp(cost)}\n\nهل ترغب في تصدير وطباعة سند الصرف PDF الآن؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if ans == QMessageBox.Yes:
                self.print_voucher(doc_id, num)
            self.lines = []; self.key = uuid.uuid4().hex; self.win.after_stock_change()
        except Exception as e:
            ar_error(self, e)
        finally:
            self.confirm.setEnabled(True)

    def print_voucher(self, doc_id, num):
        from ..services import reports, exports
        path, _ = QFileDialog.getSaveFileName(self, "حفظ سند الصرف كملف PDF", f"voucher_{num}.pdf", "*.pdf")
        if path:
            try:
                with db.session_scope() as s:
                    voucher = reports.get_issue_voucher_data(s, doc_id)
                exports.export_issue_voucher_pdf(path, voucher)
                QMessageBox.information(self, "تم بنجاح", f"تم حفظ سند الصرف بنجاح إلى:\n{path}")
            except Exception as e:
                ar_error(self, e)


class AlertsPage(Page):
    def __init__(self, win):
        super().__init__(win, "التنبيهات"); self.t = None
        self.f = QComboBox(); self.f.addItems(["الكل", "جديد", "تمت المعاينة", "تم الحل"]); self.f.currentIndexChanged.connect(self.refresh)
        self.lay.addWidget(self.f); b = QPushButton("تحديد المحدد كمُعاين"); b.clicked.connect(self.ack); self.lay.addWidget(b)

    def refresh(self):
        kill(self.t)
        st = [None, "new", "acknowledged", "resolved"][self.f.currentIndex()]
        lab = {"new": "جديد", "acknowledged": "تمت المعاينة", "resolved": "تم الحل", "low": "مخزون منخفض", "out": "نفد المخزون"}
        with db.session_scope() as s:
            al = alerts.list_alerts(s, status=st)
            self.ids = [a.id for a in al]
            rows = [[lab[a.kind], a.item.name, a.item.code, a.qty_at_creation, a.min_at_creation,
                     a.created_at.strftime("%Y-%m-%d %H:%M"), lab[a.status]] for a in al]
        self.t = table(["النوع", "الصنف", "الكود", "الرصيد", "الحد الأدنى", "وقت التنبيه", "الحالة"], rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows); self.lay.addWidget(self.t, 1)

    def ack(self):
        r = self.t.currentRow()
        if r < 0: return
        try:
            with db.session_scope() as s: alerts.acknowledge(s, self.user, self.ids[r])
            self.win.poll(); self.refresh()
        except Exception as e: ar_error(self, e)


class ReportsPage(Page):
    REPORTS = ["أرصدة المخزون", "أرصدة الدفعات", "الملخص المالي (الشهر الحالي)", "أرصدة الموردين", "استهلاك العيادات والأقسام (الشهر الحالي)"]

    def __init__(self, win):
        super().__init__(win, "التقارير"); self.t = None; self.data = None
        bar = QHBoxLayout(); self.c = QComboBox(); self.c.addItems(self.REPORTS)
        go = QPushButton("عرض"); go.clicked.connect(self.run); x = QPushButton("تصدير Excel"); x.clicked.connect(lambda: self.out("xlsx"))
        p = QPushButton("تصدير PDF / طباعة"); p.clicked.connect(lambda: self.out("pdf"))
        for w in (self.c, go, x, p): bar.addWidget(w)
        self.lay.addLayout(bar)

    def run(self):
        today = date.today(); m1 = today.replace(day=1); i = self.c.currentIndex()
        with db.session_scope() as s:
            self.data = [reports.stock_balances(s), reports.batch_balances(s), reports.financial_summary(s, m1, today),
                         reports.supplier_balances(s), reports.department_consumption(s, m1, today)][i]
        kill(self.t)
        self.t = table(self.data[1], self.data[2]); self.lay.addWidget(self.t, 1)

    def out(self, kind):
        if not self.data: self.run()
        path, _ = QFileDialog.getSaveFileName(self, "حفظ التقرير", f"report.{kind}", f"*.{kind}")
        if path:
            try:
                (exports.export_excel if kind == "xlsx" else exports.export_pdf)(path, *self.data[:1], self.data[1], self.data[2])
                QMessageBox.information(self, "تم", "تم حفظ التقرير.")
            except Exception as e: ar_error(self, e)


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__(); self.user = user; self.setWindowTitle(APP_TITLE); self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1280, 780)
        root = QWidget(); self.setCentralWidget(root); h = QHBoxLayout(root); h.setContentsMargins(0, 0, 0, 0)
        side = QWidget(); side.setObjectName("sidebar"); side.setFixedWidth(230)
        sl = QVBoxLayout(side); sl.setContentsMargins(6, 10, 6, 10); sl.setSpacing(4)
        self.stack = QStackedWidget(); self.pages = []; self.navs = []
        defs = [
            ("لوحة التحكم", DashboardPage),
            ("إدارة الأصناف", ItemsPage),
            ("الوارد إلى المخزن", IncomingPage),
            ("صرف المستلزمات", IssuePage),
            ("إدارة العيادات والأقسام", DepartmentsPage),
            ("إدارة الموردين", SuppliersPage),
            ("إدارة التبرعات", DonationsPage),
            ("المرتجعات", ReturnsPage),
            ("الهالك والتالف", DamagePage),
            ("الجرد والتسويات", StocktakePage),
            ("سجل حركة المخزون", MovementHistoryPage),
            ("التقارير", ReportsPage),
            ("التنبيهات", AlertsPage),
            ("المستخدمون والصلاحيات", UsersPage),
            ("النسخ الاحتياطي والاستعادة", BackupPage),
            ("الإعدادات", SettingsPage),
        ]
        for i, (n, cls) in enumerate(defs):
            b = QPushButton(n); b.setObjectName("nav"); b.setCheckable(True); b.clicked.connect(lambda _, k=i: self.go(k))
            sl.addWidget(b); self.navs.append((b, n)); p = cls(self); self.pages.append(p); self.stack.addWidget(p)
        sl.addStretch()
        who = QLabel(f"المستخدم: {user.display_name}")
        who.setStyleSheet("color:#cfe3e3;padding:8px;font-size:12px;border-top:1px solid #2f6f73;")
        sl.addWidget(who)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(245)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #24585c; border: none; }")
        scroll.setWidget(side)

        h.addWidget(scroll); h.addWidget(self.stack, 1)
        self.tray = QSystemTrayIcon(self); self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_MessageBoxInformation))
        self.tray.setToolTip(APP_TITLE); self.tray.show()
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(30_000)   # light: one indexed query / 30 s
        self.go(0); self.poll()

    def go(self, i):
        for k, (b, _) in enumerate(self.navs): b.setChecked(k == i)
        self.stack.setCurrentIndex(i); self.pages[i].refresh()

    def after_stock_change(self):
        self.poll(); self.pages[self.stack.currentIndex()].refresh()

    def poll(self):
        """Re-evaluate alerts, show each new unresolved condition ONCE as a native toast, update badge."""
        try:
            with db.session_scope() as s:
                alerts.scan_all(s)
                pend = alerts.pending_desktop_notifications(s)
                msgs = [alerts.notification_text_ar(a) for a in pend]
                alerts.mark_notified(s, [a.id for a in pend]); n = alerts.badge_count(s)
        except Exception:
            return
        for title, body in msgs:
            if QSystemTrayIcon.supportsMessages():
                self.tray.showMessage(title, body, QSystemTrayIcon.Warning, 10_000)
        for b, name in self.navs:
            if "التنبيهات" in name:
                b.setText(f"{name}  ({n})" if n else name)
                break

    def closeEvent(self, e):
        self.timer.stop(); super().closeEvent(e)


def main():
    app = QApplication(sys.argv); app.setLayoutDirection(Qt.RightToLeft); app.setStyleSheet(STYLE)
    fdir = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
    for f in os.listdir(fdir): QFontDatabase.addApplicationFont(os.path.join(fdir, f))
    app.setFont(QFont("Tajawal", 11))
    bootstrap.init_database(os.environ.get("CLINIC_DB"))
    with db.session_scope() as s:
        empty = s.scalar(select(User.id).limit(1)) is None
    if empty and not FirstRun().exec(): return
    lg = Login()
    if not lg.exec(): return
    w = MainWindow(lg.user); w.show(); sys.exit(app.exec())
