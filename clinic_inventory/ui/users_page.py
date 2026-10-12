"""Users and Permissions management page (Arabic RTL, PySide6)."""
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame
)
from .. import db
from ..models import User, Role
from ..permissions import ROLE_ADMIN, ROLE_KEEPER, ROLE_ISSUER, PERMISSIONS
from ..services import auth
from .common import Page, kill, ar_error, table


class AddUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة مستخدم جديد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(450, 320)

        f = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.role_combo = QComboBox()

        f.addRow("الاسم الكامل *:", self.name_edit)
        f.addRow("اسم المستخدم (تسجيل الدخول) *:", self.username_edit)
        f.addRow("كلمة المرور (6 أحرف على الأقل) *:", self.pass_edit)
        f.addRow("الدور / الصلاحيات *:", self.role_combo)

        with db.session_scope() as s:
            roles = auth.list_roles(s)
            for r in roles:
                self.role_combo.addItem(r.name, r.name)

        buttons = QDialogButtonBox()
        buttons.addButton("إنشاء المستخدم", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def get_data(self):
        return {
            "display_name": self.name_edit.text().strip(),
            "username": self.username_edit.text().strip(),
            "password": self.pass_edit.text(),
            "role_name": self.role_combo.currentText()
        }


class ChangePasswordDialog(QDialog):
    def __init__(self, parent, target_user_name):
        super().__init__(parent)
        self.setWindowTitle(f"تغيير كلمة المرور للمستخدم: {target_user_name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(420, 220)

        f = QFormLayout(self)
        self.p1 = QLineEdit()
        self.p1.setEchoMode(QLineEdit.Password)
        self.p2 = QLineEdit()
        self.p2.setEchoMode(QLineEdit.Password)

        f.addRow("كلمة المرور الجديدة *:", self.p1)
        f.addRow("تأكيد كلمة المرور *:", self.p2)

        buttons = QDialogButtonBox()
        buttons.addButton("حفظ كلمة المرور", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.confirm_and_accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def confirm_and_accept(self):
        p1 = self.p1.text()
        p2 = self.p2.text()
        if len(p1) < 6:
            QMessageBox.warning(self, "خطأ", "يجب ألا تقل كلمة المرور عن 6 أحرف.")
            return
        if p1 != p2:
            QMessageBox.warning(self, "خطأ", "كلمتا المرور غير متطابقتين.")
            return
        self.accept()

    def get_password(self):
        return self.p1.text()


class EditRoleDialog(QDialog):
    def __init__(self, parent, user_display_name, current_role_name):
        super().__init__(parent)
        self.setWindowTitle(f"تعديل دور المستخدم: {user_display_name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(400, 200)

        f = QFormLayout(self)
        self.role_combo = QComboBox()
        with db.session_scope() as s:
            for r in auth.list_roles(s):
                self.role_combo.addItem(r.name, r.name)

        idx = self.role_combo.findText(current_role_name)
        if idx >= 0:
            self.role_combo.setCurrentIndex(idx)

        f.addRow("الدور الجديد:", self.role_combo)

        buttons = QDialogButtonBox()
        buttons.addButton("حفظ", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def get_role_name(self):
        return self.role_combo.currentText()


class UserAuditDialog(QDialog):
    def __init__(self, parent, user_id, user_name):
        super().__init__(parent)
        self.setWindowTitle(f"سجل المراجعة والعمليات الحساسة للمستخدم: {user_name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(850, 480)

        lay = QVBoxLayout(self)
        with db.session_scope() as s:
            logs = auth.get_user_audit_trail(s, user_id)

        action_ar = {
            "create_user": "إنشاء مستخدم",
            "set_user_active": "تغيير حالة التفعيل",
            "change_password": "تغيير كلمة المرور",
            "update_user_role": "تغيير الدور والصلاحيات",
            "change_permissions": "تعديل صلاحيات الدور"
        }

        headers = ["المعرف", "التاريخ والوقت", "نوع العملية", "الكيان", "معرف الكيان", "القيمة السابقة", "القيمة الجديدة"]
        rows = []
        for l in logs:
            rows.append([
                l.id,
                l.ts.strftime("%Y-%m-%d %H:%M:%S"),
                action_ar.get(l.action, l.action),
                l.entity_type,
                l.entity_id or "",
                l.old_value or "",
                l.new_value or ""
            ])

        t = table(headers, rows)
        lay.addWidget(t, 1)

        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn, 0, Qt.AlignCenter)


class UsersPage(Page):
    def __init__(self, win):
        super().__init__(win, "المستخدمون والصلاحيات")
        self.t = None
        self.users = []

        # Action bar
        bar = QHBoxLayout()
        add_btn = QPushButton("إضافة مستخدم جديد")
        add_btn.clicked.connect(self.add_user)

        self.pass_btn = QPushButton("تغيير كلمة المرور")
        self.pass_btn.clicked.connect(self.change_password)

        self.role_btn = QPushButton("تغيير الدور / الصلاحيات")
        self.role_btn.clicked.connect(self.change_role)

        self.toggle_active_btn = QPushButton("تعطيل / تفعيل الحساب")
        self.toggle_active_btn.clicked.connect(self.toggle_active)

        self.audit_btn = QPushButton("عرض سجل المراجعة")
        self.audit_btn.clicked.connect(self.view_audit)

        for b in (add_btn, self.pass_btn, self.role_btn, self.toggle_active_btn, self.audit_btn):
            bar.addWidget(b)
        bar.addStretch()
        self.lay.addLayout(bar)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        kill(self.t)
        with db.session_scope() as s:
            user_objs = auth.list_users(s)
            self.users = [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "role_name": u.role.name,
                    "active": u.active,
                    "created_at": u.created_at
                }
                for u in user_objs
            ]

        headers = ["المعرف", "اسم المستخدم", "الاسم الكامل", "الدور", "الحالة", "تاريخ الإنشاء"]
        rows = []
        for u in self.users:
            rows.append([
                u["id"],
                u["username"],
                u["display_name"],
                u["role_name"],
                "نشط" if u["active"] else "معطل",
                u["created_at"].strftime("%Y-%m-%d %H:%M")
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_container.addWidget(self.t)

    def _selected_user(self):
        if not self.t:
            return None
        r = self.t.currentRow()
        if r < 0 or r >= len(self.users):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد مستخدم من الجدول أولاً.")
            return None
        return self.users[r]

    def add_user(self):
        dlg = AddUserDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            try:
                with db.session_scope() as s:
                    auth.create_user(s, self.user, **data)
                QMessageBox.information(self, "تم", f"تم إنشاء المستخدم «{data['username']}» بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def change_password(self):
        u = self._selected_user()
        if not u:
            return
        dlg = ChangePasswordDialog(self, u["display_name"])
        if dlg.exec():
            new_pass = dlg.get_password()
            try:
                with db.session_scope() as s:
                    auth.change_password(s, self.user, u["id"], new_pass)
                QMessageBox.information(self, "تم", "تم تغيير كلمة المرور بنجاح وحفظها مشفرة بشكل آمن.")
            except Exception as e:
                ar_error(self, e)

    def change_role(self):
        u = self._selected_user()
        if not u:
            return
        dlg = EditRoleDialog(self, u["display_name"], u["role_name"])
        if dlg.exec():
            new_role = dlg.get_role_name()
            try:
                with db.session_scope() as s:
                    auth.update_user_role(s, self.user, u["id"], new_role)
                QMessageBox.information(self, "تم", "تم تحديث دور وصلاحيات المستخدم بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def toggle_active(self):
        u = self._selected_user()
        if not u:
            return
        new_active = not u["active"]
        act_name = "تفعيل" if new_active else "تعطيل"

        reply = QMessageBox.question(
            self, "تأكيد", f"هل أنت متأكد من {act_name} حساب «{u['display_name']}»؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with db.session_scope() as s:
                    auth.set_user_active(s, self.user, u["id"], new_active)
                QMessageBox.information(self, "تم", f"تم {act_name} الحساب بنجاح.")
                self.refresh()
            except Exception as e:
                ar_error(self, e)

    def view_audit(self):
        u = self._selected_user()
        if not u:
            return
        dlg = UserAuditDialog(self, u["id"], u["display_name"])
        dlg.exec()
