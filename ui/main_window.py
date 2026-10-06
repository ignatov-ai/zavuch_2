# -*- coding: utf-8 -*-
"""
Главное окно приложения. Поддерживает два режима:
• ЭЖД-режим — все вкладки.
• ПДОУ-режим — только ПДОУ-вкладки + «Настройки».
"""
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
from ui.check_journals_online_tab import CheckJournalsOnlineTab  # NEW
from ui.missing_tab import MissingTab
from ui.settings_tab import SettingsTab
from ui.ktp_check_tab import KTPCheckTab
from ui.ktp_check_tab_main import KTPMainCheckTab
from ui.pdou_tab import PDOUTab
from ui.pdou_requests_tab import PDOURequestsTab


class MainWindow(QMainWindow):
    """Главное окно приложения. Поддерживает ЭЖД- и ПДОУ-режимы."""
    auth_updated = Signal(object)

    def __init__(self):
        super().__init__()
        self.auth = None
        self.auth_obj = None
        self.mode = None
        self.tab_widgets = []
        self._menu_visible = True
        self.initUI()
        self.stream = EmittingStream()
        self.stream.text_written.connect(self.append_to_console)
        sys.stdout = self.stream

    def initUI(self):
        self.setWindowTitle("zavuch 2")
        self._apply_mode_title()

        screen = QApplication.primaryScreen().geometry()
        width = int(screen.width() * 0.85)
        height = int(screen.height() * 0.8)
        self.setGeometry(50, 30, width, height)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === ЛЕВОЕ МЕНЮ ===
        self.menu_container = QWidget()
        menu_container_layout = QVBoxLayout(self.menu_container)
        menu_container_layout.setContentsMargins(0, 0, 0, 0)
        menu_container_layout.setSpacing(0)

        self.title_label = QLabel("📚  zavuch 2")
        self.title_label.setStyleSheet("""
            font-size: 15pt;
            font-weight: 700;
            color: #1d4ed8;
            padding: 18px 10px 14px 18px;
            background: #ffffff;
            border-bottom: 1px solid #e2e8f0;
        """)
        menu_container_layout.addWidget(self.title_label)

        self.menu_list = QListWidget()
        self.menu_list.setStyleSheet("""
            QListWidget {
                background-color: #f8fafc;
                border: none;
                padding: 8px;
                outline: 0;
                font-size: 10.5pt;
                color: #1e293b;
            }
            QListWidget::item {
                padding: 11px 14px;
                border-radius: 7px;
                margin: 2px 4px;
                color: #334155;
            }
            QListWidget::item:hover {
                background-color: #eff6ff;
                color: #1d4ed8;
            }
            QListWidget::item:selected {
                background-color: #1d4ed8;
                color: #ffffff;
                font-weight: 600;
            }
        """)
        self.menu_list.currentRowChanged.connect(self.on_menu_changed)
        menu_container_layout.addWidget(self.menu_list, 1)

        self.menu_container.setFixedWidth(280)
        self.menu_container.setStyleSheet("""
            QWidget#menuContainer {
                background-color: #f8fafc;
                border-right: 1px solid #e2e8f0;
            }
        """)
        self.menu_container.setObjectName("menuContainer")

        # === КНОПКА СВОРАЧИВАНИЯ ===
        self.toggle_menu_btn = QPushButton("◀")
        self.toggle_menu_btn.setFixedWidth(22)
        self.toggle_menu_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.toggle_menu_btn.setToolTip("Свернуть меню")
        self.toggle_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_menu_btn.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                border: none;
                border-right: 1px solid #e2e8f0;
                border-left: 1px solid #e2e8f0;
                font-size: 10pt;
                font-weight: 700;
                color: #64748b;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
                color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #cbd5e1;
            }
        """)
        self.toggle_menu_btn.clicked.connect(self.toggle_menu)

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
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.stack)

        main_layout.addWidget(self.menu_container)
        main_layout.addWidget(self.toggle_menu_btn)
        main_layout.addWidget(right_container, 1)

        # === ВКЛАДКИ ===
        self.settings_tab = SettingsTab(self)
        if hasattr(self.settings_tab, 'auth_successful'):
            self.settings_tab.auth_successful.connect(self.on_global_auth)

        self.download_tab = DownloadTab(self)
        self.check_tab = CheckTab(self)
        self.check_journals_online_tab = CheckJournalsOnlineTab(self)  # NEW
        self.notify_tab = NotifyTab(self)
        self.check_results_tab_5_9 = CheckResultsTab5_9(self)
        self.check_results_tab_10_11 = CheckResultsTab10_11(self)
        self.check_results_tab_5_9_online = CheckResultsTab5_9Online(self)
        self.missing_tab = MissingTab(self)
        self.ktp_main_check_tab = KTPMainCheckTab(self)
        self.ktp_check_tab = KTPCheckTab(self)
        self.pdou_tab = PDOUTab(self)
        self.pdou_requests_tab = PDOURequestsTab(self)

        self._all_tabs = [
            ("📥  Скачивание журналов", self.download_tab, "ejd"),
            ("🔍  Проверка журналов", self.check_tab, "ejd"),
            ("🔍  Проверка журналов Online",
             self.check_journals_online_tab, "ejd"),  # NEW
            ("🎯  Проверка итогов (5-9)", self.check_results_tab_5_9, "ejd"),
            ("🎯  Проверка итогов Online",
             self.check_results_tab_5_9_online, "ejd"),
            ("🎯  Проверка итогов (10-11)",
             self.check_results_tab_10_11, "ejd"),
            ("🔍  Проверка КТП (ОЧ+ФЧ)", self.ktp_main_check_tab, "ejd"),
            ("🔍  Проверка КТП (ВД)", self.ktp_check_tab, "ejd"),
            ("🎨  Кружки ПДОУ", self.pdou_tab, "pdou"),
            ("📋  Заявления ПДОУ", self.pdou_requests_tab, "pdou"),
            ("📊  Пропуски занятий", self.missing_tab, "ejd"),
            ("📨  Уведомления родителям", self.notify_tab, "ejd"),
            ("⚙️  Настройки", self.settings_tab, "ejd"),
        ]

        tabs_with_auth = [
            self.download_tab,
            self.check_tab,
            self.check_journals_online_tab,  # NEW
            self.notify_tab,
            self.check_results_tab_5_9,
            self.check_results_tab_5_9_online,
            self.check_results_tab_10_11,
            self.missing_tab,
            self.ktp_main_check_tab,
            self.ktp_check_tab,
            self.pdou_tab,
            self.pdou_requests_tab,
        ]
        for tab in tabs_with_auth:
            if hasattr(tab, 'on_auth_updated'):
                self.auth_updated.connect(tab.on_auth_updated)

        # === Подключение сигнала смены учебного года ===
        if hasattr(self.settings_tab, 'academic_year_changed'):
            self.settings_tab.academic_year_changed.connect(
                self._on_academic_year_changed
            )

        # === Подключение сигнала изменения настроек (для Online-вкладки) ===
        if hasattr(self.settings_tab, 'settings_changed'):
            self.settings_tab.settings_changed.connect(
                self._on_settings_changed
            )

        self._build_tabs_for_mode("ejd")

    def _build_tabs_for_mode(self, mode: str):
        self.menu_list.blockSignals(True)
        self.menu_list.clear()
        while self.stack.count() > 0:
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
        self.menu_list.blockSignals(False)
        self.tab_widgets = []

        if mode == "pdou":
            selected = [e for e in self._all_tabs if e[2] == "pdou"]
            settings_entry = next(
                (e for e in self._all_tabs if e[1] is self.settings_tab),
                None,
            )
            if settings_entry:
                selected.append(settings_entry)
        else:
            selected = list(self._all_tabs)

        for title, widget, _tag in selected:
            self.menu_list.addItem(title)
            self.stack.addWidget(widget)
            has_console = hasattr(widget, 'console')
            self.tab_widgets.append((widget, has_console))

        if self.menu_list.count() > 0:
            self.menu_list.setCurrentRow(0)

    def _apply_mode_title(self):
        if self.mode == "pdou":
            self.setWindowTitle("zavuch 2 — ПДОУ (кружки и заявления)")
            if hasattr(self, "title_label"):
                self.title_label.setText("🎨  zavuch 2 · ПДОУ")
                self.title_label.setStyleSheet("""
                    font-size: 15pt;
                    font-weight: 700;
                    color: #7c3aed;
                    padding: 18px 10px 14px 18px;
                    background: #ffffff;
                    border-bottom: 1px solid #e2e8f0;
                """)
        elif self.mode == "ejd":
            self.setWindowTitle("zavuch 2 — ЭЖД МЭШ")
            if hasattr(self, "title_label"):
                self.title_label.setText("📚  zavuch 2 · ЭЖД")
                self.title_label.setStyleSheet("""
                    font-size: 15pt;
                    font-weight: 700;
                    color: #1d4ed8;
                    padding: 18px 10px 14px 18px;
                    background: #ffffff;
                    border-bottom: 1px solid #e2e8f0;
                """)
        else:
            self.setWindowTitle("zavuch 2")
            if hasattr(self, "title_label"):
                self.title_label.setText("📚  zavuch 2")

    def toggle_menu(self):
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

    def on_menu_changed(self, row):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def on_global_auth(self, auth_data):
        if not auth_data:
            return
        if isinstance(auth_data, dict) and auth_data.get("saved"):
            self.mode = "pdou"
            self.auth = None
            self.auth_obj = None
            user_name = auth_data.get("user_name", "") or "неизвестен"
            roles = auth_data.get("roles", []) or []
            roles_text = ", ".join(roles) if roles else "нет ролей"
            self._build_tabs_for_mode("pdou")
            self._apply_mode_title()
            self.append_to_console(
                f"✅ Режим ПДОУ. Пользователь: {user_name}.\n"
                f"   Роли ЕСЗ: {roles_text}\n"
                f"   Доступны вкладки «🎨 Кружки ПДОУ» и «📋 Заявления ПДОУ» "
                f"(+ «⚙️ Настройки»)."
            )
            return

        self.mode = "ejd"
        self.auth = auth_data
        self.auth_obj = auth_data
        if hasattr(self.settings_tab, 'set_auth'):
            self.settings_tab.set_auth(auth_data)
        self._build_tabs_for_mode("ejd")
        self._apply_mode_title()
        self.auth_updated.emit(auth_data)
        self.append_to_console(
            "✅ ЭЖД-режим. Авторизация установлена. Все вкладки готовы."
        )

    def _on_academic_year_changed(self, aid):
        """Прокидывает смену учебного года во все вкладки."""
        for widget, _ in self.tab_widgets:
            if hasattr(widget, "on_academic_year_updated"):
                try:
                    widget.on_academic_year_updated(aid)
                except Exception as e:
                    print(f"[MainWindow] on_academic_year_updated: {e}")

    def _on_settings_changed(self, settings: dict):
        """Прокидывает обновление настроек (УП, пороги) во вкладки."""
        for widget, _ in self.tab_widgets:
            if hasattr(widget, "reload_settings"):
                try:
                    widget.reload_settings()
                except Exception as e:
                    print(f"[MainWindow] reload_settings: {e}")

    def append_to_console(self, text):
        current_widget = self.stack.currentWidget()
        if not hasattr(current_widget, "console"):
            return
        console = current_widget.console
        if hasattr(console, "append_text"):
            console.append_text(text)
            return
        if hasattr(console, "appendPlainText"):
            console.appendPlainText(str(text))
            sb = console.verticalScrollBar()
            sb.setValue(sb.maximum())
            return
        if hasattr(console, "append"):
            console.append(str(text))
            return

    def closeEvent(self, event):
        sys.stdout = sys.__stdout__
        event.accept()