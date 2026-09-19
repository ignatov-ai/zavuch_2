#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа в приложение.
Сначала открывается окно авторизации. После успеха — главное окно с вкладками.
"""
import sys
import os

# Фикс для Qt плагинов на Windows
if sys.platform == 'win32':
    possible_paths = [
        os.path.join(sys.prefix, 'Lib', 'site-packages', 'PySide6', 'plugins'),
        os.path.join(sys.prefix, 'Lib', 'site-packages', 'PySide6', 'Qt', 'plugins'),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = path
            break

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.auth_window import AuthWindow


# Современная цветовая схема
COLORS = {
    'primary': '#2563eb',
    'primary_hover': '#1d4ed8',
    'success': '#059669',
    'warning': '#d97706',
    'danger': '#dc2626',
    'background': '#f8fafc',
    'surface': '#ffffff',
    'border': '#e2e8f0',
    'text_primary': '#0f172a',
    'text_secondary': '#475569',
    'text_disabled': '#94a3b8',
    'console_bg': '#1e293b',
    'console_fg': '#e2e8f0',
}

STYLE = f"""
QMainWindow, QDialog {{
    background-color: {COLORS['background']};
}}

QWidget {{
    font-family: 'Segoe UI', 'Roboto', sans-serif;
    color: {COLORS['text_primary']};
}}

QGroupBox {{
    font-size: 13pt;
    font-weight: 600;
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    margin-top: 1.5ex;
    padding-top: 15px;
    background-color: {COLORS['surface']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 10px 0 10px;
    color: {COLORS['primary']};
}}

QPushButton {{
    background-color: {COLORS['primary']};
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 8px;
    font-weight: 500;
    font-size: 11pt;
}}

QPushButton:hover {{
    background-color: {COLORS['primary_hover']};
}}

QPushButton:pressed {{
    background-color: {COLORS['primary']};
    opacity: 0.9;
}}

QPushButton:disabled {{
    background-color: {COLORS['border']};
    color: {COLORS['text_disabled']};
}}

QLineEdit, QComboBox, QSpinBox, QDateEdit {{
    padding: 8px 12px;
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    background-color: {COLORS['surface']};
    font-size: 10pt;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{
    border: 2px solid {COLORS['primary']};
    padding: 7px 11px;
}}

QCheckBox {{
    spacing: 8px;
    font-size: 10pt;
}}

QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border: 2px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['surface']};
}}

QCheckBox::indicator:hover {{
    border-color: {COLORS['primary']};
}}

QCheckBox::indicator:checked {{
    background-color: {COLORS['primary']};
    border-color: {COLORS['primary']};
}}

QProgressBar {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    text-align: center;
    height: 24px;
    background-color: {COLORS['surface']};
    font-size: 10pt;
}}

QProgressBar::chunk {{
    background-color: {COLORS['primary']};
    border-radius: 7px;
}}

QTextEdit, QPlainTextEdit {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    background-color: {COLORS['console_bg']};
    color: {COLORS['console_fg']};
    font-family: 'Consolas', 'Monaco', 'Fira Code', monospace;
    font-size: 10pt;
    padding: 10px;
}}

QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    background-color: {COLORS['surface']};
    padding: 15px;
}}

QTabBar::tab {{
    background-color: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    padding: 10px 20px;
    margin-right: 5px;
    font-weight: 500;
    font-size: 11pt;
    color: {COLORS['text_secondary']};
}}

QTabBar::tab:selected {{
    color: {COLORS['primary']};
    border-bottom: 3px solid {COLORS['primary']};
}}

QTabBar::tab:hover {{
    color: {COLORS['primary']};
}}

QScrollBar:vertical {{
    border: none;
    background-color: {COLORS['border']};
    width: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['text_disabled']};
    border-radius: 6px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['text_secondary']};
}}

QFrame {{
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    background-color: {COLORS['surface']};
}}

QToolTip {{
    background-color: {COLORS['console_bg']};
    color: {COLORS['console_fg']};
    border: none;
    border-radius: 6px;
    padding: 8px;
    font-size: 9pt;
}}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)

    font = QFont('Segoe UI', 10)
    app.setFont(font)

    # Открываем окно авторизации
    auth_window = AuthWindow()
    auth_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()