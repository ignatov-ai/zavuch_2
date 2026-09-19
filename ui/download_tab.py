# -*- coding: utf-8 -*-
from collections import defaultdict
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from ui.console import ConsoleWidget
from workers import ConnectionThread, LoginAuthThread, ClassesThread, DownloadThread


class DownloadTab(QWidget):
    """Вкладка скачивания журналов"""

    log_signal = Signal(str)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.auth = None
        self.collector = None
        self.classes_list = []
        self.selected_folder = ""
        self.class_checkboxes = []
        self.initUI()

        self.log_signal.connect(self.append_to_console)

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self._create_auth_panel(main_layout)
        self._create_classes_button(main_layout)
        self._create_classes_area(main_layout)
        self._create_folder_panel(main_layout)
        self._create_download_button(main_layout)
        self._create_console(main_layout)

    def _create_auth_panel(self, parent_layout):
        group_box = QGroupBox("Авторизация")
        group_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

        layout = QGridLayout(group_box)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(10)
        layout.setContentsMargins(10, 15, 10, 10)

        # Статус
        layout.addWidget(QLabel("Статус:"), 0, 0)

        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(5)

        self.connection_status_label = QLabel()
        self.connection_status_label.setFixedSize(16, 16)
        status_layout.addWidget(self.connection_status_label)

        self.connection_status_text = QLabel("Не подключено")
        self.connection_status_text.setStyleSheet("color: #666;")
        status_layout.addWidget(self.connection_status_text)
        status_layout.addStretch()

        layout.addWidget(status_widget, 0, 1, 1, 3)

        # Быстрая авторизация
        layout.addWidget(QLabel("Браузер:"), 1, 0)
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["Авто", "Firefox", "Chrome", "Edge"])
        self.browser_combo.setMaximumWidth(100)
        layout.addWidget(self.browser_combo, 1, 1)

        self.browser_auth_btn = QPushButton("🌐 Быстрый вход")
        self.browser_auth_btn.setMaximumWidth(120)
        self.browser_auth_btn.clicked.connect(self.browser_auth)
        layout.addWidget(self.browser_auth_btn, 1, 2)

        # Авторизация по логину
        layout.addWidget(QLabel("Логин:"), 2, 0)
        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Телефон/email/СНИЛС")
        self.login_edit.setMaximumWidth(150)
        layout.addWidget(self.login_edit, 2, 1)

        layout.addWidget(QLabel("Пароль:"), 2, 2)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setMaximumWidth(150)
        layout.addWidget(self.password_edit, 2, 3)

        self.login_auth_btn = QPushButton("🔐 Войти")
        self.login_auth_btn.setMaximumWidth(80)
        self.login_auth_btn.clicked.connect(self.login_auth)
        layout.addWidget(self.login_auth_btn, 2, 4)

        parent_layout.addWidget(group_box)

    def _set_status_icon(self, success=None, message=None):
        if success is None:
            self.connection_status_label.clear()
            self.connection_status_text.setText(message or "Подключение...")
            self.connection_status_text.setStyleSheet("color: #f39c12;")
        elif success:
            self.connection_status_label.setPixmap(
                self.style().standardPixmap(QStyle.StandardPixmap.SP_DialogApplyButton).scaled(16, 16)
            )
            self.connection_status_text.setText("Подключено")
            self.connection_status_text.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.connection_status_label.setPixmap(
                self.style().standardPixmap(QStyle.StandardPixmap.SP_DialogCancelButton).scaled(16, 16)
            )
            self.connection_status_text.setText("Ошибка")
            self.connection_status_text.setStyleSheet("color: #c0392b; font-weight: bold;")

    def browser_auth(self):
        browser_map = {0: 'auto', 1: 'firefox', 2: 'chrome', 3: 'edge'}
        browser = browser_map.get(self.browser_combo.currentIndex(), 'auto')

        self.browser_auth_btn.setEnabled(False)
        self.login_auth_btn.setEnabled(False)
        self._set_status_icon(None, "Подключение...")

        self.connection_thread = ConnectionThread(browser)
        self.connection_thread.finished.connect(self.connection_result)
        self.connection_thread.start()

    def login_auth(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text().strip()

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль!")
            return

        self.browser_auth_btn.setEnabled(False)
        self.login_auth_btn.setEnabled(False)
        self._set_status_icon(None, "Авторизация...")

        self.login_thread = LoginAuthThread(login, password)
        self.login_thread.finished.connect(self.connection_result)
        self.login_thread.start()

    def connection_result(self, success, auth):
        if success and auth:
            self.auth = auth
            self._set_status_icon(True)

            from collector import MarksDataCollector
            self.collector = MarksDataCollector(self.auth)

            self.get_classes_btn.setEnabled(True)
            self.select_folder_btn.setEnabled(True)
        else:
            self._set_status_icon(False)
            self.browser_auth_btn.setEnabled(True)
            self.login_auth_btn.setEnabled(True)

    def _create_classes_button(self, parent_layout):
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.get_classes_btn = QPushButton("📋 Получить список классов")
        self.get_classes_btn.setEnabled(False)
        self.get_classes_btn.setMinimumHeight(32)
        self.get_classes_btn.setMaximumWidth(200)
        self.get_classes_btn.clicked.connect(self.get_classes)

        button_layout.addWidget(self.get_classes_btn)
        button_layout.addStretch()

        parent_layout.addLayout(button_layout)

    def _create_classes_area(self, parent_layout):
        self.classes_groupbox = QGroupBox("Доступные классы")
        self.classes_groupbox.setEnabled(False)
        self.classes_groupbox.setStyleSheet("""
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                background-color: #fafafa;
            }
        """)

        self.classes_widget = QWidget()
        self.classes_layout = QVBoxLayout(self.classes_widget)
        self.classes_layout.setSpacing(10)
        self.classes_layout.setContentsMargins(10, 10, 10, 10)
        self.classes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.classes_widget)

        groupbox_layout = QVBoxLayout(self.classes_groupbox)
        groupbox_layout.addWidget(scroll)

        parent_layout.addWidget(self.classes_groupbox, 1)

    def _create_folder_panel(self, parent_layout):
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.StyledPanel)
        panel.setStyleSheet("""
            QFrame {
                border: 1px solid #cccccc;
                border-radius: 6px;
                background-color: #ffffff;
                padding: 5px;
            }
        """)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)

        layout.addWidget(QLabel("📁"), 0, Qt.AlignmentFlag.AlignCenter)

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Папка для сохранения не выбрана")
        layout.addWidget(self.folder_edit, 1)

        self.select_folder_btn = QPushButton("Выбрать папку")
        self.select_folder_btn.setEnabled(False)
        self.select_folder_btn.setMinimumWidth(120)
        self.select_folder_btn.clicked.connect(self.select_folder)
        layout.addWidget(self.select_folder_btn, 0, Qt.AlignmentFlag.AlignRight)

        parent_layout.addWidget(panel)

    def _create_download_button(self, parent_layout):
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.download_btn = QPushButton("⬇️ Скачать выбранные классы")
        self.download_btn.setEnabled(False)
        self.download_btn.setMinimumHeight(36)
        self.download_btn.setMaximumWidth(250)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.download_btn.clicked.connect(self.download_classes)

        button_layout.addWidget(self.download_btn)
        button_layout.addStretch()

        parent_layout.addLayout(button_layout)

    def _create_console(self, parent_layout):
        self.console = ConsoleWidget()
        self.console.setMaximumHeight(150)
        parent_layout.addWidget(self.console)

    def get_classes(self):
        self.get_classes_btn.setEnabled(False)
        self.get_classes_btn.setText("⏳ Загрузка...")

        self.class_checkboxes = []

        self.classes_thread = ClassesThread(self.auth)
        self.classes_thread.finished.connect(self.classes_received)
        self.classes_thread.start()

    def classes_received(self, classes):
        self.get_classes_btn.setEnabled(True)
        self.get_classes_btn.setText("📋 Получить список классов")

        if not classes:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить список классов")
            return

        self.classes_list = classes
        self.display_classes()
        self.classes_groupbox.setEnabled(True)

    def display_classes(self):
        for i in reversed(range(self.classes_layout.count())):
            widget = self.classes_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        self.class_checkboxes = []

        classes_by_level = defaultdict(list)
        for class_info in self.classes_list:
            level = class_info["level"]
            classes_by_level[level].append(class_info)

        for level in sorted(classes_by_level.keys()):
            header_widget = QWidget()
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(5, 5, 5, 2)

            level_label = QLabel(f"Параллель {level}-х классов")
            level_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
            header_layout.addWidget(level_label)

            header_layout.addStretch()

            select_btn = QPushButton("Выбрать все")
            select_btn.setMaximumWidth(100)
            select_btn.setMinimumHeight(25)
            select_btn.clicked.connect(lambda checked, l=level: self.select_all_in_level(l, True))
            header_layout.addWidget(select_btn)

            deselect_btn = QPushButton("Снять все")
            deselect_btn.setMaximumWidth(100)
            deselect_btn.setMinimumHeight(25)
            deselect_btn.clicked.connect(lambda checked, l=level: self.select_all_in_level(l, False))
            header_layout.addWidget(deselect_btn)

            self.classes_layout.addWidget(header_widget)

            grid_widget = QWidget()
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setContentsMargins(20, 5, 5, 10)
            grid_layout.setHorizontalSpacing(30)
            grid_layout.setVerticalSpacing(8)

            sorted_classes = sorted(classes_by_level[level], key=lambda x: x["name"])

            cols = 3
            for idx, class_info in enumerate(sorted_classes):
                row = idx // cols
                col = idx % cols

                checkbox = QCheckBox(f"{class_info['name']} ({class_info['student_count']})")
                checkbox.class_id = class_info["id"]
                checkbox.class_name = class_info["name"]
                checkbox.class_level = level
                checkbox.stateChanged.connect(self._update_download_button)

                self.class_checkboxes.append(checkbox)
                grid_layout.addWidget(checkbox, row, col)

            self.classes_layout.addWidget(grid_widget)

        self.classes_layout.addStretch()
        self._update_download_button()

    def select_all_in_level(self, level, select):
        for checkbox in self.class_checkboxes:
            if hasattr(checkbox, 'class_level') and checkbox.class_level == level:
                checkbox.setChecked(select)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if folder:
            self.selected_folder = folder
            self.folder_edit.setText(folder)
            self._update_download_button()

    def _update_download_button(self):
        has_folder = bool(self.selected_folder)
        has_selected = any(cb.isChecked() for cb in self.class_checkboxes)
        self.download_btn.setEnabled(has_folder and has_selected and self.auth is not None)

    def download_classes(self):
        if not self.selected_folder:
            QMessageBox.warning(self, "Ошибка", "Выберите папку для сохранения!")
            return

        selected_by_level = defaultdict(list)

        for checkbox in self.class_checkboxes:
            if checkbox.isChecked():
                selected_by_level[checkbox.class_level].append({
                    "id": checkbox.class_id,
                    "name": checkbox.class_name,
                    "level": checkbox.class_level
                })

        total_selected = sum(len(classes) for classes in selected_by_level.values())

        if total_selected == 0:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один класс!")
            return

        self.get_classes_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.browser_auth_btn.setEnabled(False)
        self.login_auth_btn.setEnabled(False)

        self.console.show_progress(total_selected)

        self.download_thread = DownloadThread(self.auth, dict(selected_by_level), self.selected_folder)
        self.download_thread.progress_update.connect(self.update_download_progress)
        self.download_thread.log_message.connect(self.log_signal)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.start()

    def update_download_progress(self, value):
        self.console.set_progress(value)

    def download_finished(self, result):
        classes_done, subjects_done = result

        self.get_classes_btn.setEnabled(True)
        self.select_folder_btn.setEnabled(True)
        self.browser_auth_btn.setEnabled(True)
        self.login_auth_btn.setEnabled(True)
        self._update_download_button()

        self.console.hide_progress()

    def append_to_console(self, text):
        self.console.append_text(text)
        QApplication.processEvents()