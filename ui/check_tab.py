# -*- coding: utf-8 -*-
from collections import defaultdict
import os
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from ui.console import ConsoleWidget
from workers import CheckJournalsThread


# ============================================================
# Единый стиль для вкладок
# ============================================================
TAB_WIDGET_STYLE = """
    QWidget {
        font-size: 10pt;
        color: #1e293b;
    }
    QGroupBox {
        font-size: 11pt;
        font-weight: 700;
        color: #1d4ed8;
        border: 1px solid #93c5fd;
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
        color: #1e293b;
    }
    QLineEdit:focus {
        border: 1px solid #3b82f6;
    }
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
    QPushButton:hover {
        background: #e2e8f0;
    }
    QPushButton:pressed {
        background: #cbd5e1;
    }
    QPushButton:disabled {
        background: #f1f5f9;
        color: #94a3b8;
        border-color: #e2e8f0;
    }
    QRadioButton {
        color: #334155;
        spacing: 6px;
    }
    QRadioButton::indicator {
        width: 16px;
        height: 16px;
    }
    QCheckBox {
        color: #334155;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
    }
    QScrollArea {
        border: 1px solid #e2e8f0;
        background: #fafafa;
        border-radius: 6px;
    }
    QLabel {
        color: #334155;
    }
"""

PRIMARY_BTN_STYLE = """
    QPushButton {
        background-color: #1d4ed8;
        color: #ffffff;
        font-weight: 700;
        border: none;
        border-radius: 7px;
    }
    QPushButton:hover {
        background-color: #1e40af;
    }
    QPushButton:pressed {
        background-color: #1e3a8a;
    }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""

DANGER_BTN_STYLE = """
    QPushButton {
        background-color: #fff1f2;
        color: #be123c;
        border: 1px solid #fecdd3;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #ffe4e6;
    }
"""


class DateEditWithButton(QWidget):
    """Виджет для ввода даты с кнопкой календаря."""
    dateChanged = Signal(str)

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText(placeholder)
        self.date_edit.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.date_edit)

        self.calendar_btn = QPushButton("📅")
        self.calendar_btn.setFixedWidth(38)
        self.calendar_btn.setToolTip("Открыть календарь")
        self.calendar_btn.clicked.connect(self.show_calendar)
        layout.addWidget(self.calendar_btn)

        self.calendar_dialog = None

    def on_text_changed(self, text):
        self.dateChanged.emit(text)

    def show_calendar(self):
        self.calendar_dialog = QDialog(self)
        self.calendar_dialog.setWindowTitle("Выберите дату")
        self.calendar_dialog.setModal(True)
        self.calendar_dialog.setStyleSheet("""
            QDialog { background: #ffffff; }
            QCalendarWidget {
                background: #ffffff;
                color: #1e293b;
            }
            QCalendarWidget QToolButton {
                color: #1d4ed8;
                background: #eff6ff;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QCalendarWidget QToolButton:hover {
                background: #dbeafe;
            }
        """)
        layout = QVBoxLayout(self.calendar_dialog)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        try:
            if self.date_edit.text():
                date = QDate.fromString(self.date_edit.text(), "dd.MM.yyyy")
                if date.isValid():
                    self.calendar.setSelectedDate(date)
        except Exception:
            pass
        layout.addWidget(self.calendar)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.calendar_dialog.accept)
        button_box.rejected.connect(self.calendar_dialog.reject)
        layout.addWidget(button_box)
        if self.calendar_dialog.exec() == QDialog.DialogCode.Accepted:
            selected_date = self.calendar.selectedDate()
            self.date_edit.setText(selected_date.toString("dd.MM.yyyy"))

    def text(self):
        return self.date_edit.text()

    def setText(self, text):
        self.date_edit.setText(text)

    def setEnabled(self, enabled):
        self.date_edit.setEnabled(enabled)
        self.calendar_btn.setEnabled(enabled)


class CheckTab(QWidget):
    """Вкладка проверки журналов."""
    log_signal = Signal(str)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.journals_by_level = defaultdict(list)
        self.selected_folder = ""
        self.initUI()
        self.log_signal.connect(self.append_to_console)

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 14, 16, 14)

        # === Заголовок вкладки ===
        title = QLabel("🔍  Проверка журналов")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: 700; color: #0f172a; padding: 2px 0 6px 0;"
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "Выберите период, учебный план и журналы для автоматической проверки."
        )
        subtitle.setStyleSheet("color: #64748b; margin-bottom: 4px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # === Группа настроек ===
        settings_group = QGroupBox("Настройки проверки")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setVerticalSpacing(10)
        settings_layout.setHorizontalSpacing(12)

        # Режим проверки
        settings_layout.addWidget(
            QLabel("Режим проверки:"), 0, 0, Qt.AlignmentFlag.AlignTop
        )
        mode_widget = QWidget()
        mode_grid = QGridLayout(mode_widget)
        mode_grid.setContentsMargins(0, 0, 0, 0)
        mode_grid.setHorizontalSpacing(22)
        mode_grid.setVerticalSpacing(6)

        mode_grid.addWidget(
            QLabel("<b style='color:#1d4ed8'>Триместры (5-9)</b>"), 0, 0
        )
        mode_grid.addWidget(
            QLabel("<b style='color:#7c3aed'>Полугодия (10-11)</b>"), 0, 1
        )
        mode_grid.addWidget(
            QLabel("<b style='color:#059669'>Произвольный</b>"), 0, 2
        )

        self.rb_t1 = QRadioButton("Триместр 1 (сен-ноя)")
        self.rb_t2 = QRadioButton("Триместр 2 (дек-фев)")
        self.rb_t3 = QRadioButton("Триместр 3 (мар-май)")
        self.rb_t2.setChecked(True)
        mode_grid.addWidget(self.rb_t1, 1, 0)
        mode_grid.addWidget(self.rb_t2, 2, 0)
        mode_grid.addWidget(self.rb_t3, 3, 0)

        self.rb_p1 = QRadioButton("Полугодие 1 (сен-дек)")
        self.rb_p2 = QRadioButton("Полугодие 2 (янв-май)")
        mode_grid.addWidget(self.rb_p1, 1, 1)
        mode_grid.addWidget(self.rb_p2, 2, 1)

        self.rb_custom = QRadioButton("Указать даты вручную")
        mode_grid.addWidget(self.rb_custom, 1, 2)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_t1)
        self.mode_group.addButton(self.rb_t2)
        self.mode_group.addButton(self.rb_t3)
        self.mode_group.addButton(self.rb_p1)
        self.mode_group.addButton(self.rb_p2)
        self.mode_group.addButton(self.rb_custom)
        self.mode_group.buttonClicked.connect(self.on_mode_changed)

        settings_layout.addWidget(mode_widget, 0, 1)

        # Произвольный период
        date_widget = QWidget()
        date_layout = QHBoxLayout(date_widget)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(10)
        date_layout.addWidget(QLabel("с:"))
        self.start_date_edit = DateEditWithButton("01.01.2026")
        self.start_date_edit.setEnabled(False)
        date_layout.addWidget(self.start_date_edit)
        date_layout.addWidget(QLabel("по:"))
        self.end_date_edit = DateEditWithButton("31.05.2026")
        self.end_date_edit.setEnabled(False)
        date_layout.addWidget(self.end_date_edit)

        settings_layout.addWidget(QLabel("Произвольный период:"), 1, 0)
        settings_layout.addWidget(date_widget, 1, 1)

        # Учебный план
        settings_layout.addWidget(QLabel("Файл учебного плана:"), 2, 0)
        curriculum_widget = QWidget()
        curriculum_layout = QHBoxLayout(curriculum_widget)
        curriculum_layout.setContentsMargins(0, 0, 0, 0)
        self.curriculum_edit = QLineEdit()
        self.curriculum_edit.setText("Сводная_таблица_УП_5-11_классы.xlsx")
        curriculum_layout.addWidget(self.curriculum_edit)
        self.curriculum_browse_btn = QPushButton("Обзор…")
        self.curriculum_browse_btn.clicked.connect(self.browse_curriculum_file)
        curriculum_layout.addWidget(self.curriculum_browse_btn)
        settings_layout.addWidget(curriculum_widget, 2, 1)

        # Папка с журналами
        settings_layout.addWidget(QLabel("Папка с журналами:"), 3, 0)
        journals_folder_widget = QWidget()
        journals_folder_layout = QHBoxLayout(journals_folder_widget)
        journals_folder_layout.setContentsMargins(0, 0, 0, 0)
        self.journals_folder_edit = QLineEdit()
        self.journals_folder_edit.setPlaceholderText("Выберите папку с журналами")
        self.journals_folder_edit.textChanged.connect(self.on_folder_changed)
        journals_folder_layout.addWidget(self.journals_folder_edit)
        self.journals_folder_browse_btn = QPushButton("Обзор…")
        self.journals_folder_browse_btn.clicked.connect(self.browse_journals_folder)
        journals_folder_layout.addWidget(self.journals_folder_browse_btn)
        settings_layout.addWidget(journals_folder_widget, 3, 1)

        layout.addWidget(settings_group)

        # === Журналы для проверки ===
        self.journals_groupbox = QGroupBox("📚  Журналы для проверки")
        self.journals_groupbox.setEnabled(False)
        self.journals_groupbox.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: 700;
                color: #059669;
                border: 1px solid #6ee7b7;
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
        scroll.setMinimumHeight(230)
        self.journals_widget = QWidget()
        self.journals_layout = QVBoxLayout(self.journals_widget)
        self.journals_layout.setSpacing(6)
        scroll.setWidget(self.journals_widget)

        groupbox_layout = QVBoxLayout()
        groupbox_layout.setContentsMargins(0, 0, 0, 0)
        groupbox_layout.addWidget(scroll)
        self.journals_groupbox.setLayout(groupbox_layout)
        layout.addWidget(self.journals_groupbox)

        # === Глобальные кнопки выбора ===
        global_buttons_layout = QHBoxLayout()
        global_buttons_layout.addStretch()

        self.select_all_btn = QPushButton("✓  Выбрать все")
        self.select_all_btn.setEnabled(False)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background: #eff6ff;
                color: #1d4ed8;
                border: 1px solid #bfdbfe;
                font-weight: 600;
            }
            QPushButton:hover { background: #dbeafe; }
        """)
        self.select_all_btn.clicked.connect(self.select_all_journals)
        global_buttons_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("✗  Снять выделение")
        self.deselect_all_btn.setEnabled(False)
        self.deselect_all_btn.clicked.connect(self.deselect_all_journals)
        global_buttons_layout.addWidget(self.deselect_all_btn)

        layout.addLayout(global_buttons_layout)

        # === Папка для результатов ===
        output_group = QGroupBox("📂  Результаты")
        output_group.setStyleSheet("""
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
        output_layout = QHBoxLayout(output_group)
        output_layout.setContentsMargins(10, 6, 10, 10)
        output_layout.addWidget(QLabel("Папка для результатов:"))
        self.check_output_edit = QLineEdit()
        self.check_output_edit.setPlaceholderText(
            "Выберите папку для сохранения результатов проверки"
        )
        self.check_output_edit.textChanged.connect(self.update_start_button)
        output_layout.addWidget(self.check_output_edit, 1)
        self.check_output_browse_btn = QPushButton("Обзор…")
        self.check_output_browse_btn.clicked.connect(self.browse_check_output_folder)
        output_layout.addWidget(self.check_output_browse_btn)
        layout.addWidget(output_group)

        # === Главная кнопка запуска ===
        self.start_check_btn = QPushButton("🚀  Запустить проверку выбранных журналов")
        self.start_check_btn.setMinimumHeight(46)
        self.start_check_btn.setEnabled(False)
        self.start_check_btn.setStyleSheet(PRIMARY_BTN_STYLE + """
            QPushButton { font-size: 12pt; }
        """)
        self.start_check_btn.clicked.connect(self.start_check)
        layout.addWidget(self.start_check_btn)

        # === Журнал (консоль) ===
        self.console = ConsoleWidget()
        if hasattr(self.console, 'setStyleSheet'):
            self.console.setStyleSheet("""
                QPlainTextEdit, QTextEdit {
                    font-family: Consolas, "Courier New", monospace;
                    font-size: 9.5pt;
                    background-color: #0f172a;
                    color: #e2e8f0;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 4px;
                }
            """)
        layout.addWidget(self.console, 1)

        self.setStyleSheet(TAB_WIDGET_STYLE)

    # ================================================================
    # Обработчики
    # ================================================================
    def on_mode_changed(self):
        is_custom = self.rb_custom.isChecked()
        self.start_date_edit.setEnabled(is_custom)
        self.end_date_edit.setEnabled(is_custom)

    def browse_curriculum_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл учебного плана", "", "Excel files (*.xlsx)"
        )
        if file_path:
            self.curriculum_edit.setText(file_path)

    def browse_journals_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с журналами")
        if folder:
            self.journals_folder_edit.setText(folder)
            self.scan_journals_folder(folder)

    def browse_check_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для результатов")
        if folder:
            self.check_output_edit.setText(folder)
            self.update_start_button()

    def on_folder_changed(self, text):
        if os.path.exists(text):
            self.scan_journals_folder(text)
            self.update_start_button()

    def scan_journals_folder(self, folder_path):
        self.journals_by_level.clear()
        for i in reversed(range(self.journals_layout.count())):
            widget = self.journals_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        found_any = False
        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isdir(item_path) and item.isdigit():
                    level = int(item)
                    if 1 <= level <= 11:
                        level_files = []
                        for filename in os.listdir(item_path):
                            if filename.endswith('_журнал.xlsx') and not filename.startswith('~$'):
                                level_files.append({
                                    'path': os.path.join(item_path, filename),
                                    'name': filename,
                                    'level': level,
                                    'class_name': filename.split('_журнал')[0].replace('_', '-')
                                })
                        if level_files:
                            found_any = True
                            self.journals_by_level[level] = level_files
        except Exception as e:
            self.log_signal.emit(f"⚠️ Ошибка сканирования: {e}")

        if found_any:
            self.display_journals()
            self.log_signal.emit(
                f"📊 Найдено журналов: "
                f"{sum(len(v) for v in self.journals_by_level.values())}"
            )
            self.journals_groupbox.setEnabled(True)
            self.select_all_btn.setEnabled(True)
            self.deselect_all_btn.setEnabled(True)
        else:
            self.log_signal.emit("⚠️ Журналы не найдены")
            self.journals_groupbox.setEnabled(False)
            self.select_all_btn.setEnabled(False)
            self.deselect_all_btn.setEnabled(False)

        self.update_start_button()

    def display_journals(self):
        for i in reversed(range(self.journals_layout.count())):
            widget = self.journals_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        # Цвета параллелей: чередуем синий/фиолетовый/зелёный
        level_colors = {
            1: "#1d4ed8", 2: "#1d4ed8", 3: "#1d4ed8", 4: "#1d4ed8",
            5: "#7c3aed", 6: "#7c3aed", 7: "#7c3aed", 8: "#7c3aed", 9: "#7c3aed",
            10: "#059669", 11: "#059669",
        }

        for level in sorted(self.journals_by_level.keys()):
            color = level_colors.get(level, "#1d4ed8")
            level_label = QLabel(f"📌  Параллель {level}-х классов")
            level_label.setStyleSheet(
                f"font-size: 11pt; font-weight: 700; color: {color}; "
                f"padding: 8px 4px 2px 4px;"
            )
            self.journals_layout.addWidget(level_label)

            grid_widget = QWidget()
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setContentsMargins(16, 4, 10, 10)
            grid_layout.setHorizontalSpacing(14)
            grid_layout.setVerticalSpacing(6)

            journals = sorted(self.journals_by_level[level], key=lambda x: x['class_name'])
            cols = 4
            rows = (len(journals) + cols - 1) // cols
            for idx, journal in enumerate(journals):
                row = idx % rows
                col = idx // rows
                checkbox = QCheckBox(journal['class_name'])
                checkbox.journal = journal
                checkbox.stateChanged.connect(self.update_start_button)
                checkbox.setStyleSheet("""
                    QCheckBox { spacing: 7px; padding: 3px 4px; }
                    QCheckBox::indicator { width: 17px; height: 17px; }
                    QCheckBox:hover { color: #1d4ed8; }
                """)
                grid_layout.addWidget(checkbox, row, col)

            self.journals_layout.addWidget(grid_widget)

    def select_all_journals(self):
        for i in range(self.journals_layout.count()):
            widget = self.journals_layout.itemAt(i).widget()
            if widget and isinstance(widget, QWidget):
                for child in widget.children():
                    if isinstance(child, QGridLayout):
                        for j in range(child.count()):
                            item = child.itemAt(j)
                            if item and item.widget() and isinstance(item.widget(), QCheckBox):
                                item.widget().setChecked(True)
        self.update_start_button()

    def deselect_all_journals(self):
        for i in range(self.journals_layout.count()):
            widget = self.journals_layout.itemAt(i).widget()
            if widget and isinstance(widget, QWidget):
                for child in widget.children():
                    if isinstance(child, QGridLayout):
                        for j in range(child.count()):
                            item = child.itemAt(j)
                            if item and item.widget() and isinstance(item.widget(), QCheckBox):
                                item.widget().setChecked(False)
        self.update_start_button()

    def get_selected_journals(self):
        selected = []
        for i in range(self.journals_layout.count()):
            widget = self.journals_layout.itemAt(i).widget()
            if widget and isinstance(widget, QWidget):
                for child in widget.children():
                    if isinstance(child, QGridLayout):
                        for j in range(child.count()):
                            item = child.itemAt(j)
                            if item and item.widget() and isinstance(item.widget(), QCheckBox):
                                checkbox = item.widget()
                                if checkbox.isChecked() and hasattr(checkbox, 'journal'):
                                    selected.append(checkbox.journal)
        return selected

    def update_start_button(self):
        has_output_folder = bool(self.check_output_edit.text())
        has_selected = bool(self.get_selected_journals())
        has_journals = bool(self.journals_by_level)
        enabled = has_output_folder and has_selected and has_journals
        self.start_check_btn.setEnabled(enabled)

    def append_to_console(self, text):
        self.console.append_text(text)
        QApplication.processEvents()

    def get_selected_mode(self):
        if self.rb_t1.isChecked():
            return "Т1"
        elif self.rb_t2.isChecked():
            return "Т2"
        elif self.rb_t3.isChecked():
            return "Т3"
        elif self.rb_p1.isChecked():
            return "П1"
        elif self.rb_p2.isChecked():
            return "П2"
        elif self.rb_custom.isChecked():
            return "custom"
        else:
            return "Т2"

    def start_check(self):
        selected_journals = self.get_selected_journals()
        if not selected_journals:
            QMessageBox.warning(self, "Ошибка", "Выберите журналы для проверки!")
            return
        if not self.check_output_edit.text():
            QMessageBox.warning(self, "Ошибка", "Выберите папку для результатов!")
            return
        if not os.path.exists(self.curriculum_edit.text()):
            QMessageBox.warning(
                self, "Ошибка",
                f"Файл учебного плана не найден:\n{self.curriculum_edit.text()}"
            )
            return

        check_mode = self.get_selected_mode()
        start_date = None
        end_date = None
        period_display = ""

        if check_mode == "custom":
            start_date = self.start_date_edit.text().strip()
            end_date = self.end_date_edit.text().strip()
            if not start_date or not end_date:
                QMessageBox.warning(
                    self, "Ошибка",
                    "Для произвольного периода укажите даты начала и окончания!"
                )
                return
            try:
                from datetime import datetime
                datetime.strptime(start_date, "%d.%m.%Y")
                datetime.strptime(end_date, "%d.%m.%Y")
            except ValueError:
                QMessageBox.warning(
                    self, "Ошибка",
                    "Неверный формат даты! Используйте ДД.ММ.ГГГГ"
                )
                return
            period_display = f"{start_date} - {end_date}"
        else:
            period_names = {
                "Т1": "Триместр 1 (сен-ноя)",
                "Т2": "Триместр 2 (дек-фев)",
                "Т3": "Триместр 3 (мар-май)",
                "П1": "Полугодие 1 (сен-дек)",
                "П2": "Полугодие 2 (янв-май)",
            }
            period_display = period_names.get(check_mode, check_mode)

        self.start_check_btn.setEnabled(False)
        self.console.clear()
        self.console.append_text("🚀 Запуск проверки журналов...")
        self.console.append_text(f"📁 Папка с журналами: {self.journals_folder_edit.text()}")
        self.console.append_text(f"📁 Папка для результатов: {self.check_output_edit.text()}")
        self.console.append_text(f"📅 Период: {period_display}")
        self.console.append_text(f"📚 Файл учебного плана: {self.curriculum_edit.text()}")
        self.console.append_text(f"📊 Выбрано журналов: {len(selected_journals)}")

        by_level = defaultdict(list)
        for j in selected_journals:
            by_level[j['level']].append(j)
        for level in sorted(by_level.keys()):
            self.console.append_text(f"  • Параллель {level}: {len(by_level[level])} журналов")

        self.check_thread = CheckJournalsThread(
            selected_journals,
            self.check_output_edit.text(),
            self.curriculum_edit.text(),
            check_mode,
            start_date,
            end_date,
        )
        self.check_thread.log_message.connect(self.log_signal)
        self.check_thread.finished.connect(self.check_finished)
        self.check_thread.start()

    def check_finished(self, result):
        total_files, total_errors = result
        self.console.append_text(f"\n✅ Проверка завершена!")
        self.console.append_text(f"📊 Обработано файлов: {total_files}")
        self.console.append_text(f"⚠️ Найдено ошибок: {total_errors}")
        self.start_check_btn.setEnabled(True)