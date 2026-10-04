# -*- coding: utf-8 -*-
"""
Универсальный виджет консоли вывода в едином стиле приложения.
Тёмная тема с моноширинным шрифтом и цветным прогресс-баром.
"""
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QTextCursor, QFont, QColor
from PySide6.QtWidgets import (
    QTextEdit, QGroupBox, QVBoxLayout, QProgressBar,
    QApplication, QHBoxLayout, QPushButton, QLabel,
)


# ============================================================
# Перенаправление stdout
# ============================================================
class EmittingStream(QObject):
    """Класс для перенаправления stdout в консоль GUI."""
    text_written = Signal(str)

    def __init__(self):
        super().__init__()

    def write(self, text):
        if text and text.strip():
            self.text_written.emit(text)

    def flush(self):
        pass


# ============================================================
# Виджет консоли
# ============================================================
class ConsoleWidget(QGroupBox):
    """Виджет консоли вывода в едином стиле приложения."""

    def __init__(self, title="📋  Журнал работы", parent=None):
        super().__init__(title, parent)
        self.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: 700;
                color: #0369a1;
                border: 1px solid #7dd3fc;
                border-radius: 10px;
                margin-top: 12px;
                padding: 18px 14px 14px 14px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(8)

        # === Верхняя панель: индикатор + очистка ===
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)

        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet(
            "color: #059669; font-size: 10pt; font-weight: 700;"
        )
        self.status_indicator.setToolTip("Консоль активна")
        top_bar.addWidget(self.status_indicator)

        self.lines_count_label = QLabel("0 строк")
        self.lines_count_label.setStyleSheet(
            "color: #64748b; font-size: 9pt; font-weight: 500;"
        )
        top_bar.addWidget(self.lines_count_label)

        top_bar.addStretch()

        self.clear_btn = QPushButton("🗑  Очистить")
        self.clear_btn.setFixedHeight(26)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: #fff1f2;
                color: #be123c;
                border: 1px solid #fecdd3;
                border-radius: 5px;
                padding: 2px 10px;
                font-size: 9pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #ffe4e6;
            }
            QPushButton:pressed {
                background: #fecdd3;
            }
        """)
        self.clear_btn.clicked.connect(self.clear)
        top_bar.addWidget(self.clear_btn)

        layout.addLayout(top_bar)

        # === Текстовое поле ===
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 9))
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9.5pt;
                selection-background-color: #1e40af;
                selection-color: #ffffff;
            }
        """)
        layout.addWidget(self.text_edit, 1)

        # === Прогресс-бар ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #f8fafc;
                text-align: center;
                color: #1e293b;
                font-weight: 600;
                font-size: 9pt;
            }
            QProgressBar::chunk {
                background-color: #059669;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)

        self._line_count = 0

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------
    def append_text(self, text):
        """Добавляет строку в консоль."""
        self.text_edit.append(str(text))
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

        self._line_count += 1
        self.lines_count_label.setText(f"{self._line_count} строк")

        # Ограничиваем размер буфера
        doc = self.text_edit.document()
        if doc.blockCount() > 3000:
            cursor = doc.find(".*", QTextCursor.MoveOperation.Start)
            if not cursor.isNull():
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()

        QApplication.processEvents()

    def clear(self):
        """Очищает консоль."""
        self.text_edit.clear()
        self._line_count = 0
        self.lines_count_label.setText("0 строк")

    def show_progress(self, maximum=100):
        """Показывает прогресс-бар."""
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(0)

    def hide_progress(self):
        """Скрывает прогресс-бар."""
        self.progress_bar.setVisible(False)

    def set_progress(self, value):
        """Устанавливает значение прогресс-бара."""
        self.progress_bar.setValue(value)

    def set_status(self, status: str):
        """Устанавливает цветной индикатор статуса.
        status: 'ok' | 'busy' | 'error' | 'idle'
        """
        colors = {
            'ok': ('#059669', 'Консоль активна'),
            'busy': ('#d97706', 'Выполняется операция'),
            'error': ('#dc2626', 'Ошибка'),
            'idle': ('#94a3b8', 'Ожидание'),
        }
        color, tooltip = colors.get(status, colors['idle'])
        self.status_indicator.setStyleSheet(
            f"color: {color}; font-size: 10pt; font-weight: 700;"
        )
        self.status_indicator.setToolTip(tooltip)