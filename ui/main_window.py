# -*- coding: utf-8 -*-
import sys
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from ui.download_tab import DownloadTab
from ui.check_tab import CheckTab
from ui.notify_tab import NotifyTab
from ui.console import EmittingStream
from ui.check_results_tab_5_9 import CheckResultsTab5_9
from ui.check_results_tab_10_11 import CheckResultsTab10_11
from ui.missing_tab import MissingTab
from ui.settings_tab import SettingsTab
from ui.ktp_check_tab import KTPCheckTab
from ui.ktp_check_tab_main import KTPMainCheckTab


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    auth_updated = Signal(object)

    def __init__(self):
        super().__init__()
        self.auth = None
        self.auth_obj = None
        self.tab_widgets = []
        self.initUI()

        # Перенаправление stdout
        self.stream = EmittingStream()
        self.stream.text_written.connect(self.append_to_console)
        sys.stdout = self.stream

    def initUI(self):
        self.setWindowTitle("Скачивание и проверка журналов из ЭЖД")

        screen = QApplication.primaryScreen().geometry()
        width = int(screen.width() * 0.8)
        height = int(screen.height() * 0.85)
        self.setGeometry(100, 50, width, height)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === ЛЕВОЕ МЕНЮ ===
        self.menu_list = QListWidget()
        self.menu_list.setFixedWidth(280)
        self.menu_list.setStyleSheet("""
            QListWidget {
                background-color: #f0f4f8;
                border: none;
                border-right: 1px solid #d0d7de;
                padding: 10px 5px;
                outline: 0;
                font-size: 11pt;
            }
            QListWidget::item {
                padding: 12px 15px;
                border-radius: 8px;
                margin: 3px 5px;
                color: #1f2937;
            }
            QListWidget::item:hover {
                background-color: #e0e7ef;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
            }
        """)
        self.menu_list.currentRowChanged.connect(self.on_menu_changed)

        # === ПРАВАЯ ОБЛАСТЬ ===
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("""
            QStackedWidget {
                background-color: #ffffff;
                border: none;
            }
        """)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.stack)

        main_layout.addWidget(self.menu_list)
        main_layout.addWidget(right_container, 1)

        # === ВКЛАДКИ ===
        self.settings_tab = SettingsTab(self)
        if hasattr(self.settings_tab, 'auth_successful'):
            self.settings_tab.auth_successful.connect(self.on_global_auth)

        self.download_tab = DownloadTab(self)
        self.check_tab = CheckTab(self)
        self.notify_tab = NotifyTab(self)
        self.check_results_tab_5_9 = CheckResultsTab5_9(self)
        self.check_results_tab_10_11 = CheckResultsTab10_11(self)
        self.missing_tab = MissingTab(self)
        self.ktp_main_check_tab = KTPMainCheckTab(self)
        self.ktp_check_tab = KTPCheckTab(self)

        tabs = [
            ("📥  Скачивание журналов", self.download_tab),
            ("🔍  Проверка журналов", self.check_tab),
            ("🎯  Проверка итогов (5-9)", self.check_results_tab_5_9),
            ("🎯  Проверка итогов (10-11)", self.check_results_tab_10_11),
            ("🔍  Проверка КТП (ОЧ+ФЧ)", self.ktp_main_check_tab),
            ("🔍  Проверка КТП (ВД)", self.ktp_check_tab),
            ("📊  Пропуски занятий", self.missing_tab),
            ("📨  Уведомления родителям", self.notify_tab),
            ("⚙️  Настройки", self.settings_tab),
        ]

        self.tab_widgets = []
        for title, widget in tabs:
            self.menu_list.addItem(title)
            self.stack.addWidget(widget)
            has_console = hasattr(widget, 'console')
            self.tab_widgets.append((widget, has_console))

        self.menu_list.setCurrentRow(0)

        # === ПОДПИСКА НА АВТОРИЗАЦИЮ ===
        tabs_with_auth = [
            self.download_tab,
            self.check_tab,
            self.notify_tab,
            self.check_results_tab_5_9,
            self.check_results_tab_10_11,
            self.missing_tab,
            self.ktp_main_check_tab,
            self.ktp_check_tab,
        ]

        for tab in tabs_with_auth:
            if hasattr(tab, 'on_auth_updated'):
                self.auth_updated.connect(tab.on_auth_updated)

    def on_menu_changed(self, row):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    # ------------------------------------------------------------------
    def on_global_auth(self, auth_data):
        """Приём авторизации из AuthWindow."""
        if not auth_data:
            return

        self.auth = auth_data
        self.auth_obj = auth_data

        # Устанавливаем в SettingsTab
        if hasattr(self.settings_tab, 'set_auth'):
            self.settings_tab.set_auth(auth_data)

        # Пробрасываем во все вкладки
        self.auth_updated.emit(auth_data)
        self.append_to_console("✅ Авторизация установлена. Все вкладки готовы.")

    def append_to_console(self, text):
        current_widget = self.stack.currentWidget()
        if hasattr(current_widget, 'console'):
            current_widget.console.append_text(text)

    def closeEvent(self, event):
        sys.stdout = sys.__stdout__
        event.accept()