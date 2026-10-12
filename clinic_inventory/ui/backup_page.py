"""Backup and Restore page (Arabic RTL, PySide6)."""
import os
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QMessageBox,
    QDialogButtonBox, QTextEdit, QComboBox, QGroupBox, QAbstractItemView,
    QHeaderView, QFrame, QFileDialog, QCheckBox
)
from .. import db
from ..errors import AppError
from ..services import backup, settings
from .common import Page, kill, ar_error, table


class BackupPage(Page):
    def __init__(self, win):
        super().__init__(win, "النسخ الاحتياطي والاستعادة")
        self.t = None
        self.backups = []

        # Top Card: Backup Controls
        cfg_frame = QFrame()
        cfg_frame.setObjectName("card")
        cfg_lay = QVBoxLayout(cfg_frame)

        dest_lay = QHBoxLayout()
        dest_lay.addWidget(QLabel("مسار حفظ النسخ الاحتياطية:"))
        self.dest_edit = QLineEdit()
        self.browse_btn = QPushButton("تحديد مجلد...")
        self.browse_btn.clicked.connect(self.browse_dest)
        dest_lay.addWidget(self.dest_edit, 2)
        dest_lay.addWidget(self.browse_btn)
        cfg_lay.addLayout(dest_lay)

        auto_lay = QHBoxLayout()
        self.auto_check = QCheckBox("تفعيل النسخ الاحتياطي التلقائي الدوري")
        self.save_cfg_btn = QPushButton("حفظ إعدادات النسخ")
        self.save_cfg_btn.clicked.connect(self.save_backup_config)
        auto_lay.addWidget(self.auto_check)
        auto_lay.addStretch()
        auto_lay.addWidget(self.save_cfg_btn)
        cfg_lay.addLayout(auto_lay)

        self.lay.addWidget(cfg_frame)

        # Action bar
        act_bar = QHBoxLayout()
        self.create_btn = QPushButton("إنشاء نسخة احتياطية الآن (يدوي)")
        self.create_btn.clicked.connect(self.do_manual_backup)

        self.restore_btn = QPushButton("استعادة من نسخة محددة")
        self.restore_btn.setObjectName("btn-danger")
        self.restore_btn.clicked.connect(self.do_restore_selected)

        self.restore_file_btn = QPushButton("استعادة من ملف خارجي...")
        self.restore_file_btn.setObjectName("btn-danger")
        self.restore_file_btn.clicked.connect(self.do_restore_file)

        self.verify_btn = QPushButton("فحص سلامة النسخة")
        self.verify_btn.clicked.connect(self.do_verify_selected)

        act_bar.addWidget(self.create_btn)
        act_bar.addWidget(self.verify_btn)
        act_bar.addStretch()
        act_bar.addWidget(self.restore_btn)
        act_bar.addWidget(self.restore_file_btn)
        self.lay.addLayout(act_bar)

        # History Table Title
        hist_title = QLabel("سجل وتاريخ النسخ الاحتياطية:")
        hist_title.setStyleSheet("font-weight:bold; color:#1b4346; margin-top:10px;")
        self.lay.addWidget(hist_title)

        self.table_container = QVBoxLayout()
        self.lay.addLayout(self.table_container, 1)

    def refresh(self):
        with db.session_scope() as s:
            st = settings.get_all_settings(s)
            self.dest_edit.setText(st.get("backup_dest_dir", os.path.join(db.app_data_dir(), "backups")))
            self.auto_check.setChecked(st.get("backup_auto_enabled", "1") == "1")

            self.backups = backup.list_backups(s)

        kill(self.t)
        kind_ar = {"manual": "يدوية", "auto": "تلقائية", "safety": "أمان قبل الاستعادة"}
        status_ar = {"ok": "سليمة وصالحة", "failed": "فاشلة"}

        headers = ["المعرف", "التاريخ والوقت", "نوع النسخة", "الحالة", "الحجم (KB)", "مسار الملف", "المنشئ"]
        rows = []
        for b in self.backups:
            sz_kb = round(b["size_bytes"] / 1024, 1) if b["size_bytes"] else 0
            rows.append([
                b["id"],
                b["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                kind_ar.get(b["kind"], b["kind"]),
                status_ar.get(b["status"], b["status"]),
                f"{sz_kb} KB",
                b["path"],
                b["creator_name"]
            ])

        self.t = table(headers, rows)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_container.addWidget(self.t)

    def browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد النسخ الاحتياطية", self.dest_edit.text())
        if d:
            self.dest_edit.setText(d)

    def save_backup_config(self):
        dest = self.dest_edit.text().strip()
        if not dest:
            QMessageBox.warning(self, "خطأ", "يرجى تحديد مسار المجلد.")
            return
        os.makedirs(dest, exist_ok=True)
        try:
            with db.session_scope() as s:
                settings.save_settings(s, self.user, {
                    "backup_dest_dir": dest,
                    "backup_auto_enabled": "1" if self.auto_check.isChecked() else "0"
                })
            QMessageBox.information(self, "تم", "تم حفظ إعدادات النسخ الاحتياطي بنجاح.")
        except Exception as e:
            ar_error(self, e)

    def do_manual_backup(self):
        dest_dir = self.dest_edit.text().strip() or os.path.join(db.app_data_dir(), "backups")
        try:
            with db.session_scope() as s:
                p = backup.create_backup(s, self.user, db.default_db_path(), dest_dir, kind="manual")
            QMessageBox.information(self, "تم بنجاح", f"تم إنشاء النسخة الاحتياطية والتحقق من سلامتها بنجاح.\nالمسار:\n{p}")
            self.refresh()
        except Exception as e:
            ar_error(self, e)

    def _selected_backup(self):
        if not self.t:
            return None
        r = self.t.currentRow()
        if r < 0 or r >= len(self.backups):
            QMessageBox.information(self, "تنبيه", "يرجى تحديد نسخة احتياطية من الجدول أولاً.")
            return None
        return self.backups[r]

    def do_verify_selected(self):
        b = self._selected_backup()
        if not b:
            return
        path = b["path"]
        if not os.path.exists(path):
            QMessageBox.warning(self, "خطأ", f"ملف النسخة الاحتياطية غير موجود على القرص:\n{path}")
            return
        is_ok = backup.verify_backup(path)
        if is_ok:
            QMessageBox.information(self, "نتيجة الفحص", "النسخة الاحتياطية سليمة تمامًا ومطابقة لهيكل قاعدة البيانات.")
        else:
            QMessageBox.critical(self, "نتيجة الفحص", "النسخة الاحتياطية تالفة أو غير صالحة للاستعادة!")

    def do_restore_selected(self):
        b = self._selected_backup()
        if not b:
            return
        self._execute_restore(b["path"])

    def do_restore_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "اختر ملف النسخة الاحتياطية", "", "ملفات قواعد بيانات (*.db);;جميع الملفات (*.*)")
        if p:
            self._execute_restore(p)

    def _execute_restore(self, backup_file_path):
        if not os.path.exists(backup_file_path):
            QMessageBox.critical(self, "خطأ", f"الملف المحدد غير موجود:\n{backup_file_path}")
            return

        # 1. Validation
        if not backup.verify_backup(backup_file_path):
            QMessageBox.critical(self, "خطأ فادح", "فشل التحقق من سلامة ملف النسخة الاحتياطية. الملف تالف أو غير صالح ولن يتم تعديل أي بيانات.")
            return

        # 2. Strict Warning
        warn_msg = (
            "تحذير هام جدًا!\n\n"
            "استعادة النسخة الاحتياطية ستستبدل قاعدة البيانات الحالية بالكامل.\n"
            "سيقوم النظام تلقائيًا بإنشاء نسخة أمان احتياطية من البيانات الحالية قبل الاستبدال.\n\n"
            "هل أنت متأكد تمامًا من استعادة البيانات من هذا الملف؟"
        )
        reply = QMessageBox.warning(
            self, "تأكيد استعادة النسخة الاحتياطية", warn_msg,
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 3. Restore
        try:
            safety_dir = os.path.join(db.app_data_dir(), "safety_backups")
            safety_path = backup.restore_backup(
                self.user, backup_file_path, db.default_db_path(),
                safety_dir, db.get_engine().dispose
            )
            # Re-init engine
            db.init_engine(db.default_db_path())
            QMessageBox.information(
                self, "تمت الاستعادة بنجاح",
                f"تمت استعادة البيانات بنجاح.\nتم حفظ نسخة أمان من البيانات السابقة في:\n{safety_path}"
            )
            self.refresh()
            self.win.after_stock_change()
        except Exception as e:
            ar_error(self, e)
