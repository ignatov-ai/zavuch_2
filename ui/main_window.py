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
from ui.check_results_tab_5_9_online import CheckResultsTab5_9Online
from ui.missing_tab import MissingTab
from ui.settings_tab import SettingsTab
from ui.ktp_check_tab import KTPCheckTab
from ui.ktp_check_tab_main import KTPMainCheckTab
from ui.pdou_tab import PDOUTab


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    auth_updated = Signal(object)

    def __init__(self):
        super().__init__()
        self.auth = None
        self.auth_obj = None
        self.tab_widgets = []
        self._menu_visible = True
        self.initUI()

        # Перенаправление stdout
        self.stream = EmittingStream()
        self.stream.text_written.connect(self.append_to_console)
        sys.stdout = self.stream

    def initUI(self):
        self.setWindowTitle("Скачивание и проверка журналов из ЭЖД")

        screen = QApplication.primaryScreen().geometry()
        width = int(screen.width() * 0.85)
        height = int(screen.height() * 0.9)
        self.setGeometry(50, 30, width, height)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ============================================================
        #  ЛЕВОЕ МЕНЮ (в контейнере, чтобы скрывать/показывать)
        # ============================================================
        self.menu_container = QWidget()
        menu_container_layout = QVBoxLayout(self.menu_container)
        menu_container_layout.setContentsMargins(0, 0, 0, 0)
        menu_container_layout.setSpacing(0)

        # Логотип / заголовок
        title_label = QLabel("📚  zavuch 2")
        title_label.setStyleSheet("""
            font-size: 14pt;
            font-weight: bold;
            color: #2563eb;
            padding: 15px 10px 10px 15px;
        """)
        menu_container_layout.addWidget(title_label)

        # Само меню
        self.menu_list = QListWidget()
        self.menu_list.setStyleSheet("""
            QListWidget {
                background-color: #f0f4f8;
                border: none;
                padding: 5px;
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
        menu_container_layout.addWidget(self.menu_list, 1)

        self.menu_container.setFixedWidth(280)
        self.menu_container.setStyleSheet("""
            QWidget {
                background-color: #f0f4f8;
                border-right: 1px solid #d0d7de;
            }
        """)

        # ============================================================
        #  КНОПКА СВОРАЧИВАНИЯ (всегда видна, вертикальная полоса)
        # ============================================================
        self.toggle_menu_btn = QPushButton("◀")
        self.toggle_menu_btn.setFixedWidth(22)
        self.toggle_menu_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.toggle_menu_btn.setToolTip("Свернуть меню")
        self.toggle_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_menu_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e7ef;
                border: none;
                border-right: 1px solid #cbd5e1;
                border-left: 1px solid #cbd5e1;
                font-size: 10pt;
                font-weight: bold;
                color: #475569;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #cbd5e1;
                color: #1e293b;
            }
            QPushButton:pressed {
                background-color: #94a3b8;
            }
        """)
        self.toggle_menu_btn.clicked.connect(self.toggle_menu)

        # ============================================================
        #  ПРАВАЯ ОБЛАСТЬ (QStackedWidget)
        # ============================================================
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

        # ============================================================
        #  СБОРКА MAIN_LAYOUT
        # ============================================================
        main_layout.addWidget(self.menu_container)
        main_layout.addWidget(self.toggle_menu_btn)
        main_layout.addWidget(right_container, 1)

        # ============================================================
        #  СОЗДАЁМ ВКЛАДКИ
        # ============================================================
        self.settings_tab = SettingsTab(self)
        if hasattr(self.settings_tab, 'auth_successful'):
            self.settings_tab.auth_successful.connect(self.on_global_auth)

        self.download_tab = DownloadTab(self)
        self.check_tab = CheckTab(self)
        self.notify_tab = NotifyTab(self)
        self.check_results_tab_5_9 = CheckResultsTab5_9(self)
        self.check_results_tab_10_11 = CheckResultsTab10_11(self)
        self.check_results_tab_5_9_online = CheckResultsTab5_9Online(self)
        self.missing_tab = MissingTab(self)
        self.ktp_main_check_tab = KTPMainCheckTab(self)
        self.ktp_check_tab = KTPCheckTab(self)
        self.pdou_tab = PDOUTab(self)

        # ============================================================
        #  ПОРЯДОК В МЕНЮ
        # ============================================================
        tabs = [
            ("📥  Скачивание журналов", self.download_tab),
            ("🔍  Проверка журналов", self.check_tab),
            ("🎯  Проверка итогов (5-9)", self.check_results_tab_5_9),
            ("🎯  Проверка итогов Online", self.check_results_tab_5_9_online),
            ("🎯  Проверка итогов (10-11)", self.check_results_tab_10_11),
            ("🔍  Проверка КТП (ОЧ+ФЧ)", self.ktp_main_check_tab),
            ("🔍  Проверка КТП (ВД)", self.ktp_check_tab),
            ("🎨  Кружки ПДОУ", self.pdou_tab),
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

        # ============================================================
        #  ПОДКЛЮЧАЕМ СИГНАЛ АВТОРИЗАЦИИ
        # ============================================================
        tabs_with_auth = [
            self.download_tab,
            self.check_tab,
            self.notify_tab,
            self.check_results_tab_5_9,
            self.check_results_tab_5_9_online,
            self.check_results_tab_10_11,
            self.missing_tab,
            self.ktp_main_check_tab,
            self.ktp_check_tab,
            self.pdou_tab,
        ]

        for tab in tabs_with_auth:
            if hasattr(tab, 'on_auth_updated'):
                self.auth_updated.connect(tab.on_auth_updated)

    # ================================================================
    #  СВОРАЧИВАНИЕ / РАЗВОРАЧИВАНИЕ МЕНЮ
    # ================================================================
    def toggle_menu(self):
        """Свернуть/развернуть боковое меню."""
        if self.menu_container.isVisible():
            self.menu_container.setVisible(False)
            self.toggle_menu_btn.setText("▶")
            self.toggle_menu_btn.setToolTip("Развернуть меню")
            self._menu_visible = False
        else:
            self.menu_container.setVisible(True)
            self.toggle_menu_btn.setText("◀")
            self.toggle_menu_btn.setToolTip("Свернуть меню")
            self._menu_visible = True

    # ================================================================
    #  ПЕРЕКЛЮЧЕНИЕ ВКЛАДОК
    # ================================================================
    def on_menu_changed(self, row):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    # ================================================================
    #  АВТОРИЗАЦИЯ
    # ================================================================
    def on_global_auth(self, auth_data):
        """Приём авторизации из AuthWindow."""
        if not auth_data:
            return

        self.auth = auth_data
        self.auth_obj = auth_data

        if hasattr(self.settings_tab, 'set_auth'):
            self.settings_tab.set_auth(auth_data)

        self.auth_updated.emit(auth_data)
        self.append_to_console("✅ Авторизация установлена. Все вкладки готовы.")

    def append_to_console(self, text):
        current_widget = self.stack.currentWidget()
        if hasattr(current_widget, 'console'):
            current_widget.console.append_text(text)

    def closeEvent(self, event):
        sys.stdout = sys.__stdout__
        event.accept()