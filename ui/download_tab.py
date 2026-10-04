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


# ============================================================
# Единый стиль (голубой акцент — скачивание)
# ============================================================
TAB_STYLE = """
    QWidget {
        font-size: 10pt;
        color: #1e293b;
    }
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
    QLineEdit {
        min-height: 30px;
        padding: 2px 8px;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        background: #ffffff;
    }
    QLineEdit:focus { border: 1px solid #0ea5e9; }
    QLineEdit:disabled {
        background: #f1f5f9;
        color: #94a3b8;
    }
    QPushButton {
        min-height: 30px;
        padding: 4px 12px;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        background: #f8fafc;
        color: #1e293b;
        font-weight: 500;
    }
    QPushButton:hover { background: #e2e8f0; }
    QPushButton:pressed { background: #cbd5e1; }
    QPushButton:disabled {
        background: #f1f5f9;
        color: #94a3b8;
        border-color: #e2e8f0;
    }
    QCheckBox { color: #334155; spacing: 6px; }
    QCheckBox::indicator { width: 16px; height: 16px; }
    QScrollArea {
        border: 1px solid #e2e8f0;
        background: #fafafa;
        border-radius: 6px;
    }
    QLabel { color: #334155; }
"""

PRIMARY_BTN = """
    QPushButton {
        background-color: #0369a1;
        color: #ffffff;
        font-weight: 700;
        border: none;
        border-radius: 7px;
    }
    QPushButton:hover { background-color: #075985; }
    QPushButton:pressed { background-color: #0c4a6e; }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""


class DownloadTab(QWidget):
    """Вкладка скачивания журналов."""
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
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 14, 16, 14)

        # === Заголовок ===
        title = QLabel("📥  Скачивание журналов")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: 700; color: #0f172a; padding: 2px 0 6px 0;"
        )
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Загрузите список доступных классов и скачайте их журналы в Excel."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #64748b; margin-bottom: 4px;")
        main_layout.addWidget(subtitle)

        # === Кнопка получения классов ===
        top_btn_layout = QHBoxLayout()
        top_btn_layout.addStretch()
        self.get_classes_btn = QPushButton("📋  Получить список классов")
        self.get_classes_btn.setEnabled(False)
        self.get_classes_btn.setMinimumHeight(38)
        self.get_classes_btn.setMaximumWidth(260)
        self.get_classes_btn.setStyleSheet("""
            QPushButton {
                background: #e0f2fe;
                color: #0369a1;
                border: 1px solid #7dd3fc;
                font-weight: 600;
                font-size: 10.5pt;
            }
            QPushButton:hover { background: #bae6fd; }
            QPushButton:disabled {
                background: #f1f5f9;
                color: #94a3b8;
                border-color: #e2e8f0;
            }
        """)
        self.get_classes_btn.clicked.connect(self.get_classes)
        top_btn_layout.addWidget(self.get_classes_btn)
        top_btn_layout.addStretch()
        main_layout.addLayout(top_btn_layout)

        # === Область классов ===
        self.classes_groupbox = QGroupBox("🎓  Доступные классы")
        self.classes_groupbox.setEnabled(False)
        self.classes_groupbox.setStyleSheet("""
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

        # === Папка сохранения ===
        folder_panel = QFrame()
        folder_panel.setFrameStyle(QFrame.Shape.StyledPanel)
        folder_panel.setStyleSheet("""
            QFrame {
                border: 1px solid #7dd3fc;
                border-radius: 8px;
                background: #f0f9ff;
                padding: 6px;
            }
        """)
        folder_layout = QHBoxLayout(folder_panel)
        folder_layout.setContentsMargins(12, 8, 12, 8)
        folder_layout.setSpacing(10)

        icon_label = QLabel("📁")
        icon_label.setStyleSheet("font-size: 14pt;")
        folder_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Папка для сохранения не выбрана")
        self.folder_edit.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 1px solid #bae6fd;
                color: #0c4a6e;
                font-weight: 500;
            }
        """)
        folder_layout.addWidget(self.folder_edit, 1)

        self.select_folder_btn = QPushButton("Выбрать папку")
        self.select_folder_btn.setEnabled(False)
        self.select_folder_btn.setMinimumWidth(130)
        folder_layout.addWidget(
            self.select_folder_btn, 0, Qt.AlignmentFlag.AlignRight
        )
        self.select_folder_btn.clicked.connect(self.select_folder)

        main_layout.addWidget(folder_panel)

        # === Кнопка скачивания ===
        dl_layout = QHBoxLayout()
        dl_layout.addStretch()
        self.download_btn = QPushButton("⬇️  Скачать выбранные классы")
        self.download_btn.setEnabled(False)
        self.download_btn.setMinimumHeight(44)
        self.download_btn.setMaximumWidth(300)
        self.download_btn.setStyleSheet(
            PRIMARY_BTN + "QPushButton { font-size: 11.5pt; }"
        )
        self.download_btn.clicked.connect(self.download_classes)
        dl_layout.addWidget(self.download_btn)
        dl_layout.addStretch()
        main_layout.addLayout(dl_layout)

        # === Консоль ===
        self.console = ConsoleWidget()
        main_layout.addWidget(self.console)

        self.setStyleSheet(TAB_STYLE)

    # ------------------------------------------------------------------
    # Авторизация
    # ------------------------------------------------------------------
    def on_auth_updated(self, auth):
        """Слот для сигнала MainWindow.auth_updated."""
        self.auth = auth
        if auth:
            from collector import MarksDataCollector
            self.collector = MarksDataCollector(self.auth)
            self.get_classes_btn.setEnabled(True)
            self.select_folder_btn.setEnabled(True)
            self.append_to_console(
                "✅ Авторизация получена. Можно получать классы."
            )
        else:
            self.get_classes_btn.setEnabled(False)
            self.select_folder_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Классы
    # ------------------------------------------------------------------
    def get_classes(self):
        if not self.auth:
            QMessageBox.warning(
                self, "Ошибка",
                "Нет активной сессии.\nПерезапустите приложение и войдите заново."
            )
            return
        self.get_classes_btn.setEnabled(False)
        self.get_classes_btn.setText("⏳  Загрузка...")
        self.class_checkboxes = []
        self.classes_thread = ClassesThread(self.auth)
        self.classes_thread.finished.connect(self.classes_received)
        self.classes_thread.start()

    def classes_received(self, classes):
        self.get_classes_btn.setEnabled(True)
        self.get_classes_btn.setText("📋  Получить список классов")
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

        # Цвета параллелей
        level_colors = {
            1: "#1d4ed8", 2: "#1d4ed8", 3: "#1d4ed8", 4: "#1d4ed8",
            5: "#7c3aed", 6: "#7c3aed", 7: "#7c3aed", 8: "#7c3aed", 9: "#7c3aed",
            10: "#059669", 11: "#059669",
        }

        for level in sorted(classes_by_level.keys()):
            color = level_colors.get(level, "#0369a1")

            # Заголовок параллели + кнопки
            header = QWidget()
            hl = QHBoxLayout(header)
            hl.setContentsMargins(4, 4, 4, 2)
            lbl = QLabel(f"📌  Параллель {level}-х классов")
            lbl.setStyleSheet(
                f"font-size: 11pt; font-weight: 700; color: {color};"
            )
            hl.addWidget(lbl)
            hl.addStretch()

            sel_btn = QPushButton("✓  Выбрать все")
            sel_btn.setMaximumWidth(120)
            sel_btn.setMinimumHeight(26)
            sel_btn.setStyleSheet("""
                QPushButton {
                    background: #e0f2fe; color: #0369a1;
                    border: 1px solid #7dd3fc; font-weight: 600;
                    font-size: 9pt;
                }
                QPushButton:hover { background: #bae6fd; }
            """)
            sel_btn.clicked.connect(
                lambda _, l=level: self.select_all_in_level(l, True)
            )
            hl.addWidget(sel_btn)

            desel_btn = QPushButton("✗  Снять все")
            desel_btn.setMaximumWidth(120)
            desel_btn.setMinimumHeight(26)
            desel_btn.clicked.connect(
                lambda _, l=level: self.select_all_in_level(l, False)
            )
            hl.addWidget(desel_btn)

            self.classes_layout.addWidget(header)

            # Сетка чекбоксов
            grid_w = QWidget()
            grid = QGridLayout(grid_w)
            grid.setContentsMargins(20, 5, 5, 10)
            grid.setHorizontalSpacing(30)
            grid.setVerticalSpacing(8)

            sorted_classes = sorted(
                classes_by_level[level], key=lambda x: x["name"]
            )
            cols = 3
            for idx, ci in enumerate(sorted_classes):
                row = idx // cols
                col = idx % cols
                cb = QCheckBox(f"{ci['name']}  ({ci['student_count']} уч.)")
                cb.class_id = ci["id"]
                cb.class_name = ci["name"]
                cb.class_level = level
                cb.stateChanged.connect(self._update_download_button)
                cb.setStyleSheet("""
                    QCheckBox { spacing: 7px; padding: 3px 4px; }
                    QCheckBox::indicator { width: 17px; height: 17px; }
                    QCheckBox:hover { color: #0369a1; }
                """)
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
    # Папка / кнопка
    # ------------------------------------------------------------------
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку для сохранения"
        )
        if folder:
            self.selected_folder = folder
            self.folder_edit.setText(folder)
            self._update_download_button()

    def _update_download_button(self):
        has_folder = bool(self.selected_folder)
        has_selected = any(cb.isChecked() for cb in self.class_checkboxes)
        self.download_btn.setEnabled(
            has_folder and has_selected and self.auth is not None
        )

    # ------------------------------------------------------------------
    # Скачивание
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
                    "level": checkbox.class_level,
                })

        total_selected = sum(len(v) for v in selected_by_level.values())
        if total_selected == 0:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один класс!")
            return

        self.get_classes_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(False)
        self.download_btn.setEnabled(False)

        self.console.show_progress(total_selected)
        self.download_thread = DownloadThread(
            self.auth, dict(selected_by_level), self.selected_folder
        )
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