# -*- coding: utf-8 -*-
import sys
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtWidgets import QTextEdit, QGroupBox, QVBoxLayout, QProgressBar, QApplication


class EmittingStream(QObject):
    """Класс для перенаправления stdout в консоль GUI"""
    text_written = Signal(str)

    def __init__(self):
        super().__init__()

    def write(self, text):
        if text.strip():
            self.text_written.emit(text)

    def flush(self):
        pass


class ConsoleWidget(QGroupBox):
    """Виджет консоли вывода"""

    def __init__(self, title="Консоль", parent=None):
        super().__init__(title, parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 6px;
                margin-top: 5px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 15, 5, 5)
        layout.setSpacing(5)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 9))
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333333;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
            }
        """)

        layout.addWidget(self.text_edit)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress_bar)

    def append_text(self, text):
        self.text_edit.append(text)
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)
        QApplication.processEvents()

    def clear(self):
        self.text_edit.clear()

    def show_progress(self, maximum=100):
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(0)

    def hide_progress(self):
        self.progress_bar.setVisible(False)

    def set_progress(self, value):
        self.progress_bar.setValue(value)