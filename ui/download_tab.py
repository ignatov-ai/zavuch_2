# -*- coding: utf-8 -*-
"""
Вкладка скачивания журналов.
Авторизация приходит из MainWindow через сигнал auth_updated.
"""
from collections import defaultdict
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from ui.console import ConsoleWidget
from workers import ClassesThread, DownloadThread


class DownloadTab(QWidget):
    """Вкладка скачивания журналов. Авторизация — снаружи."""

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

    # ------------------------------------------------------------------
    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # --- Кнопка получения классов ---
        top_btn_layout = QHBoxLayout()
        top_btn_layout.addStretch()

        self.get_classes_btn = QPushButton("📋 Получить список классов")
        self.get_classes_btn.setEnabled(False)
        self.get_classes_btn.setMinimumHeight(32)
        self.get_classes_btn.setMaximumWidth(220)
        self.get_classes_btn.clicked.connect(self.get_classes)
        top_btn_layout.addWidget(self.get_classes_btn)
        top_btn_layout.addStretch()

        main_layout.addLayout(top_btn_layout)

        # --- Область классов ---
        self.classes_groupbox = QGroupBox("Доступные классы")
        self.classes_groupbox.setEnabled(False)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(220)

        self.classes_widget = QWidget()
        self.classes_layout = QVBoxLayout(self.classes_widget)
        self.classes_layout.setSpacing(10)
        self.classes_layout.setContentsMargins(10, 10, 10, 10)
        self.classes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.classes_widget)

        gb_layout = QVBoxLayout(self.classes_groupbox)
        gb_layout.addWidget(scroll)
        main_layout.addWidget(self.classes_groupbox, 1)

        # --- Папка сохранения ---
        folder_panel = QFrame()
        folder_panel.setFrameStyle(QFrame.Shape.StyledPanel)
        folder_panel.setStyleSheet("""
            QFrame { border: 1px solid #cccccc; border-radius: 6px;
                background-color: #ffffff; padding: 5px; }
        """)
        folder_layout = QHBoxLayout(folder_panel)
        folder_layout.setContentsMargins(10, 8, 10, 8)

        folder_layout.addWidget(QLabel("📁"), 0, Qt.AlignmentFlag.AlignCenter)

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Папка для сохранения не выбрана")
        folder_layout.addWidget(self.folder_edit, 1)

        self.select_folder_btn = QPushButton("Выбрать папку")
        self.select_folder_btn.setEnabled(False)
        self.select_folder_btn.setMinimumWidth(120)
        self.select_folder_btn.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.select_folder_btn, 0, Qt.AlignmentFlag.AlignRight)

        main_layout.addWidget(folder_panel)

        # --- Кнопка скачивания ---
        dl_layout = QHBoxLayout()
        dl_layout.addStretch()

        self.download_btn = QPushButton("⬇️ Скачать выбранные классы")
        self.download_btn.setEnabled(False)
        self.download_btn.setMinimumHeight(36)
        self.download_btn.setMaximumWidth(250)
        self.download_btn.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white;
                font-weight: bold; border-radius: 5px; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        self.download_btn.clicked.connect(self.download_classes)
        dl_layout.addWidget(self.download_btn)
        dl_layout.addStretch()

        main_layout.addLayout(dl_layout)

        # --- Консоль ---
        self.console = ConsoleWidget()
        self.console.setMaximumHeight(180)
        main_layout.addWidget(self.console)

    # ------------------------------------------------------------------
    #  АВТОРИЗАЦИЯ ИЗ MAINWINDOW
    # ------------------------------------------------------------------
    def on_auth_updated(self, auth):
        """Слот для сигнала MainWindow.auth_updated."""
        self.auth = auth
        if auth:
            from collector import MarksDataCollector
            self.collector = MarksDataCollector(self.auth)

            self.get_classes_btn.setEnabled(True)
            self.select_folder_btn.setEnabled(True)
            self.append_to_console("✅ Авторизация получена. Можно получать классы.")
        else:
            self.get_classes_btn.setEnabled(False)
            self.select_folder_btn.setEnabled(False)

    # ------------------------------------------------------------------
    #  КЛАССЫ
    # ------------------------------------------------------------------
    def get_classes(self):
        if not self.auth:
            QMessageBox.warning(self, "Ошибка",
                                "Нет активной сессии.\n"
                                "Перезапустите приложение и войдите заново.")
            return

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
            QMessageBox.warning(self, "Ошибка", "Не удалось получить список классов.")
            return

        self.classes_list = classes
        self.display_classes()
        self.classes_groupbox.setEnabled(True)

    def display_classes(self):
        for i in reversed(range(self.classes_layout.count())):
            w = self.classes_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

        self.class_checkboxes = []

        classes_by_level = defaultdict(list)
        for class_info in self.classes_list:
            classes_by_level[class_info["level"]].append(class_info)

        for level in sorted(classes_by_level.keys()):
            header = QWidget()
            hl = QHBoxLayout(header)
            hl.setContentsMargins(5, 5, 5, 2)

            lbl = QLabel(f"Параллель {level}-х классов")
            lbl.setStyleSheet("font-weight: bold; color: #2c3e50;")
            hl.addWidget(lbl)
            hl.addStretch()

            sel_btn = QPushButton("Выбрать все")
            sel_btn.setMaximumWidth(100)
            sel_btn.setMinimumHeight(25)
            sel_btn.clicked.connect(lambda _, l=level: self.select_all_in_level(l, True))
            hl.addWidget(sel_btn)

            desel_btn = QPushButton("Снять все")
            desel_btn.setMaximumWidth(100)
            desel_btn.setMinimumHeight(25)
            desel_btn.clicked.connect(lambda _, l=level: self.select_all_in_level(l, False))
            hl.addWidget(desel_btn)

            self.classes_layout.addWidget(header)

            grid_w = QWidget()
            grid = QGridLayout(grid_w)
            grid.setContentsMargins(20, 5, 5, 10)
            grid.setHorizontalSpacing(30)
            grid.setVerticalSpacing(8)

            sorted_classes = sorted(classes_by_level[level], key=lambda x: x["name"])
            cols = 3
            for idx, ci in enumerate(sorted_classes):
                row = idx // cols
                col = idx % cols
                cb = QCheckBox(f"{ci['name']} ({ci['student_count']})")
                cb.class_id = ci["id"]
                cb.class_name = ci["name"]
                cb.class_level = level
                cb.stateChanged.connect(self._update_download_button)
                self.class_checkboxes.append(cb)
                grid.addWidget(cb, row, col)

            self.classes_layout.addWidget(grid_w)

        self.classes_layout.addStretch()
        self._update_download_button()

    def select_all_in_level(self, level, select):
        for cb in self.class_checkboxes:
            if cb.class_level == level:
                cb.setChecked(select)

    # ------------------------------------------------------------------
    #  ПАПКА / КНОПКА
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    #  СКАЧИВАНИЕ
    # ------------------------------------------------------------------
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

        total_selected = sum(len(v) for v in selected_by_level.values())
        if total_selected == 0:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один класс!")
            return

        self.get_classes_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(False)
        self.download_btn.setEnabled(False)

        self.console.show_progress(total_selected)

        self.download_thread = DownloadThread(self.auth, dict(selected_by_level), self.selected_folder)
        self.download_thread.progress_update.connect(self.update_download_progress)
        self.download_thread.log_message.connect(self.log_signal)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.start()

    def update_download_progress(self, value):
        self.console.set_progress(value)

    def download_finished(self, result):
        self.get_classes_btn.setEnabled(True)
        self.select_folder_btn.setEnabled(True)
        self._update_download_button()
        self.console.hide_progress()

    def append_to_console(self, text):
        self.console.append_text(text)
        QApplication.processEvents()