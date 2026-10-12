"""Common UI helpers, base classes, and dialogs for Arabic RTL PySide6 UI."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QMessageBox, QHeaderView, QAbstractItemView
)
from ..errors import AppError

STYLE = """
* { font-size: 14px; }
QMainWindow, QWidget#page { background: #f4f7f7; }
QWidget#sidebar { background: #24585c; }
QPushButton#nav { color: #e8f2f2; background: transparent; border: none; padding: 12px 16px; text-align: right; }
QPushButton#nav:hover { background: #2f6f73; } QPushButton#nav:checked { background: #1b4346; font-weight: bold; }
QLabel#title { font-size: 22px; font-weight: bold; color: #1b4346; }
QFrame#card { background: white; border: 1px solid #d9e3e3; border-radius: 8px; }
QPushButton { background: #2f6f73; color: white; border: none; border-radius: 6px; padding: 8px 18px; }
QPushButton:hover { background: #24585c; }
QPushButton:disabled { background: #a0b2b3; color: #e0e0e0; }
QPushButton#btn-danger { background: #c0392b; }
QPushButton#btn-danger:hover { background: #962d22; }
QPushButton#btn-secondary { background: #7f8c8d; }
QPushButton#btn-secondary:hover { background: #616a6b; }
QTableWidget { background: white; gridline-color: #e3eaea; alternate-background-color: #f7fafa; }
QHeaderView::section { background: #e4eeee; padding: 6px; border: none; font-weight: bold; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit { padding: 5px; border: 1px solid #c2d1d1; border-radius: 4px; background: white; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus { border: 1.5px solid #24585c; }
"""


def kill(w):
    """Detach immediately (deleteLater alone leaves the old widget painted until the event loop runs)."""
    if w is not None:
        w.hide()
        w.setParent(None)
        w.deleteLater()


def ar_error(parent, e: Exception):
    msg = e.message_ar if isinstance(e, AppError) else "حدث خطأ غير متوقع. تم حفظ بياناتك، ويرجى إبلاغ المسؤول."
    QMessageBox.warning(parent, "تنبيه", msg)


def table(headers, rows):
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setLayoutDirection(Qt.RightToLeft)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSortingEnabled(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem(str(v))
            it.setTextAlignment(Qt.AlignCenter)
            t.setItem(r, c, it)
    return t


class Page(QWidget):
    def __init__(self, win, title):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        self.user = win.user
        self.lay = QVBoxLayout(self)
        self.lay.setAlignment(Qt.AlignTop)
        h = QLabel(title)
        h.setObjectName("title")
        self.lay.addWidget(h)

    def refresh(self):
        pass

    def clear_below(self, keep=1):
        while self.lay.count() > keep:
            w = self.lay.takeAt(self.lay.count() - 1).widget()
            kill(w)
