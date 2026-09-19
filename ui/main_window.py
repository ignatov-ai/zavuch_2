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


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    auth_updated = Signal(object)

    def __init__(self):
        super().__init__()
        self.auth = None
        self.auth_obj = None
        self.initUI()

        # Перенаправление stdout
        self.stream = EmittingStream()
        self.stream.text_written.connect(self.append_to_console)
        sys.stdout = self.stream

    def initUI(self):
        self.setWindowTitle("Скачивание и проверка журналов из ЭЖД")

        screen = QApplication.primaryScreen().geometry()
        width = int(screen.width() * 0.9)
        height = int(screen.height() * 0.85)
        self.setGeometry(50, 50, width, height)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # === ВКЛАДКА НАСТРОЕК ===
        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.settings_tab, "⚙️ Настройки")

        if hasattr(self.settings_tab, 'auth_successful'):
            self.settings_tab.auth_successful.connect(self.on_global_auth)

        # === ОСТАЛЬНЫЕ ВКЛАДКИ ===
        self.download_tab = DownloadTab(self)
        self.tabs.addTab(self.download_tab, "📥 Скачивание журналов")

        self.check_tab = CheckTab(self)
        self.tabs.addTab(self.check_tab, "🔍 Проверка журналов")

        self.notify_tab = NotifyTab(self)
        self.tabs.addTab(self.notify_tab, "📨 Уведомления родителям")

        self.check_results_tab_5_9 = CheckResultsTab5_9(self)
        self.tabs.addTab(self.check_results_tab_5_9, "🎯 Проверка итогов (5-9)")

        self.check_results_tab_10_11 = CheckResultsTab10_11(self)
        self.tabs.addTab(self.check_results_tab_10_11, "🎯 Проверка итогов (10-11)")

        self.missing_tab = MissingTab(self)
        self.tabs.addTab(self.missing_tab, "📊 Пропуски занятий")

        self.ktp_check_tab = KTPCheckTab(self)
        self.tabs.addTab(self.ktp_check_tab, "🔍 Проверка КТП")

        # === ПОДКЛЮЧАЕМ СИГНАЛ АВТОРИЗАЦИИ ===
        tabs_with_auth = [
            self.download_tab,
            self.check_tab,
            self.notify_tab,
            self.check_results_tab_5_9,
            self.check_results_tab_10_11,
            self.missing_tab,
            self.ktp_check_tab,
        ]
        for tab in tabs_with_auth:
            if hasattr(tab, 'on_auth_updated'):
                self.auth_updated.connect(tab.on_auth_updated)

    # ------------------------------------------------------------------
    def on_global_auth(self, auth_data):
        """Приём авторизации из окна входа (или из SettingsTab)."""
        if not auth_data:
            return

        self.auth = auth_data
        self.auth_obj = auth_data

        # Передаём во все вкладки
        self.auth_updated.emit(auth_data)
        self.append_to_console("✅ Авторизация установлена. Все вкладки готовы.")

    # ------------------------------------------------------------------
    def append_to_console(self, text):
        current_tab = self.tabs.currentWidget()
        if hasattr(current_tab, 'console'):
            current_tab.console.append_text(text)

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        sys.stdout = sys.__stdout__
        event.accept()