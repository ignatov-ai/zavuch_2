# -*- coding: utf-8 -*-
import os
from collections import defaultdict
from datetime import datetime
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


# ============================================================
# Единый стиль
# ============================================================
TAB_STYLE = """
    QWidget {
        font-size: 10pt;
        color: #1e293b;
    }
    QGroupBox {
        font-size: 11pt;
        font-weight: 700;
        color: #7c3aed;
        border: 1px solid #c4b5fd;
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
    QLineEdit:focus { border: 1px solid #7c3aed; }
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
    QPushButton:disabled {
        background: #f1f5f9;
        color: #94a3b8;
        border-color: #e2e8f0;
    }
    QCheckBox { color: #334155; spacing: 6px; }
    QCheckBox::indicator { width: 16px; height: 16px; }
    QComboBox {
        min-height: 28px;
        padding: 2px 8px;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        background: #ffffff;
    }
    QTableWidget {
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        gridline-color: #e2e8f0;
        alternate-background-color: #f8fafc;
    }
    QTableWidget::item { padding: 3px 6px; }
    QHeaderView::section {
        background: #f1f5f9;
        color: #1e293b;
        padding: 5px;
        border: none;
        border-right: 1px solid #e2e8f0;
        border-bottom: 1px solid #e2e8f0;
        font-weight: 600;
    }
    QScrollArea {
        border: 1px solid #e2e8f0;
        background: #fafafa;
        border-radius: 6px;
    }
"""

PRIMARY_BTN = """
    QPushButton {
        background-color: #7c3aed;
        color: #ffffff;
        font-weight: 700;
        border: none;
        border-radius: 7px;
    }
    QPushButton:hover { background-color: #6d28d9; }
    QPushButton:pressed { background-color: #5b21b6; }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""

SUCCESS_BTN = """
    QPushButton {
        background-color: #059669;
        color: #ffffff;
        font-weight: 600;
        border: none;
        border-radius: 6px;
    }
    QPushButton:hover { background-color: #047857; }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""


class CheckResultsTab5_9(QWidget):
    """Вкладка проверки выставления итоговых отметок для 5-9 классов (триместры)."""
    log_signal = Signal(str)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.selected_folder = ""
        self.class_checkboxes = []
        self.all_results = []
        self.last_export_path = None
        self._is_loading = False
        self.initUI()
        self.log_signal.connect(self.append_to_status)

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 14, 16, 14)

        # Заголовок
        title = QLabel("🎯  Проверка итоговых отметок (5-9 классы)")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: 700; color: #0f172a; padding: 2px 0 4px 0;"
        )
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Проверка триместровых и годовой отметок по средним баллам. "
            "Выберите папку с журналами и нужные классы."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #64748b; margin-bottom: 4px;")
        main_layout.addWidget(subtitle)

        # === Группа настроек ===
        settings_group = QGroupBox("Настройки проверки")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setVerticalSpacing(10)
        settings_layout.setHorizontalSpacing(12)

        # Папка с журналами
        settings_layout.addWidget(QLabel("Папка с журналами:"), 0, 0)
        journals_widget = QWidget()
        journals_layout = QHBoxLayout(journals_widget)
        journals_layout.setContentsMargins(0, 0, 0, 0)
        journals_layout.setSpacing(6)
        self.journals_folder_edit = QLineEdit()
        self.journals_folder_edit.setPlaceholderText("Выберите папку с журналами")
        self.journals_folder_edit.textChanged.connect(self.on_folder_changed)
        journals_layout.addWidget(self.journals_folder_edit, 1)
        self.journals_folder_browse_btn = QPushButton("Обзор…")
        self.journals_folder_browse_btn.setFixedWidth(80)
        self.journals_folder_browse_btn.clicked.connect(self.browse_journals_folder)
        journals_layout.addWidget(self.journals_folder_browse_btn)
        settings_layout.addWidget(journals_widget, 0, 1)

        # Список классов
        settings_layout.addWidget(QLabel("Классы для проверки:"), 1, 0, Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(110)
        scroll.setMaximumHeight(140)
        self.classes_widget = QWidget()
        self.classes_layout = QHBoxLayout(self.classes_widget)
        self.classes_layout.setSpacing(12)
        self.classes_layout.setContentsMargins(12, 8, 12, 8)
        self.classes_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.classes_widget)
        settings_layout.addWidget(scroll, 1, 1)

        # Кнопки выбора классов
        class_buttons_widget = QWidget()
        class_buttons_layout = QHBoxLayout(class_buttons_widget)
        class_buttons_layout.setContentsMargins(0, 0, 0, 0)
        class_buttons_layout.setSpacing(8)
        self.select_all_classes_btn = QPushButton("✓  Выбрать все")
        self.select_all_classes_btn.setStyleSheet("""
            QPushButton {
                background: #f5f3ff; color: #7c3aed;
                border: 1px solid #ddd6fe; font-weight: 600;
            }
            QPushButton:hover { background: #ede9fe; }
        """)
        self.select_all_classes_btn.clicked.connect(self.select_all_classes)
        class_buttons_layout.addWidget(self.select_all_classes_btn)

        self.deselect_all_classes_btn = QPushButton("✗  Снять все")
        self.deselect_all_classes_btn.clicked.connect(self.deselect_all_classes)
        class_buttons_layout.addWidget(self.deselect_all_classes_btn)

        class_buttons_layout.addStretch()
        settings_layout.addWidget(class_buttons_widget, 2, 1)

        # Кнопка проверки
        self.check_btn = QPushButton("🔍  Проверить итоговые отметки (5-9 классы)")
        self.check_btn.setEnabled(False)
        self.check_btn.setMinimumHeight(42)
        self.check_btn.setStyleSheet(PRIMARY_BTN + "QPushButton { font-size: 11pt; }")
        self.check_btn.clicked.connect(self.check_results)
        settings_layout.addWidget(self.check_btn, 3, 0, 1, 2)

        # Кнопка экспорта
        export_widget = QWidget()
        export_layout = QHBoxLayout(export_widget)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(10)
        self.export_excel_btn = QPushButton("📊  Экспорт в Excel")
        self.export_excel_btn.setEnabled(False)
        self.export_excel_btn.setStyleSheet(SUCCESS_BTN)
        self.export_excel_btn.clicked.connect(self.export_to_excel)
        export_layout.addWidget(self.export_excel_btn)
        export_layout.addStretch()
        settings_layout.addWidget(export_widget, 4, 0, 1, 2)

        main_layout.addWidget(settings_group)

        # === Панель фильтров ===
        filter_group = QGroupBox("🔎  Фильтры")
        filter_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt; font-weight: 700;
                color: #0369a1; border: 1px solid #7dd3fc;
                border-radius: 10px; margin-top: 12px;
                padding: 18px 14px 14px 14px; background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        filter_layout = QHBoxLayout(filter_group)
        filter_layout.setSpacing(10)
        filter_layout.setContentsMargins(10, 6, 10, 10)

        filter_layout.addWidget(QLabel("Класс:"))
        self.filter_class = QLineEdit()
        self.filter_class.setPlaceholderText("Название")
        self.filter_class.setFixedWidth(110)
        self.filter_class.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_class)

        filter_layout.addWidget(QLabel("Ученик:"))
        self.filter_student = QLineEdit()
        self.filter_student.setPlaceholderText("ФИО")
        self.filter_student.setFixedWidth(150)
        self.filter_student.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_student)

        filter_layout.addWidget(QLabel("Предмет:"))
        self.filter_subject = QLineEdit()
        self.filter_subject.setPlaceholderText("Предмет")
        self.filter_subject.setFixedWidth(150)
        self.filter_subject.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_subject)

        filter_layout.addWidget(QLabel("Статус:"))
        self.filter_status = QComboBox()
        self.filter_status.addItems([
            "Все статусы", "✅ СОВПАДАЕТ", "❌ НЕ СОВПАДАЕТ",
            "⚠️ НЕТ ГПА", "⚠️ ДОЛГ (А/З)", "⚠️ НПА", "⚠️ НЕТ ДАННЫХ",
        ])
        self.filter_status.setFixedWidth(160)
        self.filter_status.currentTextChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_status)

        self.clear_filters_btn = QPushButton("Очистить")
        self.clear_filters_btn.setStyleSheet("""
            QPushButton {
                background: #fff1f2; color: #be123c;
                border: 1px solid #fecdd3; font-weight: 600;
            }
            QPushButton:hover { background: #ffe4e6; }
        """)
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        filter_layout.addWidget(self.clear_filters_btn)
        filter_layout.addStretch()

        main_layout.addWidget(filter_group)

        # === Таблица результатов ===
        self.results_table = QTableWidget()
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(False)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.results_table.horizontalHeader().setStretchLastSection(True)
        main_layout.addWidget(self.results_table, 1)

        # === Статусная строка ===
        self.status_label = QLabel("Готов к работе")
        self.status_label.setStyleSheet("""
            color: #1e40af; background: #eff6ff;
            border-radius: 6px; padding: 7px 10px;
            font-weight: 600;
        """)
        main_layout.addWidget(self.status_label)

        self.setStyleSheet(TAB_STYLE)

    # ================================================================
    # Служебные методы
    # ================================================================
    def append_to_status(self, text):
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.setText(str(text)[:200])
            QApplication.processEvents()

    def browse_journals_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с журналами")
        if folder:
            self.journals_folder_edit.setText(folder)
            self.scan_journals_folder(folder)

    def on_folder_changed(self, text):
        if os.path.exists(text) and not self._is_loading:
            self.scan_journals_folder(text)

    def scan_journals_folder(self, folder_path):
        if self._is_loading:
            return
        self.class_checkboxes.clear()
        while self.classes_layout.count() > 0:
            item = self.classes_layout.takeAt(0)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        found_any = False
        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isdir(item_path) and item.isdigit():
                    level = int(item)
                    if 5 <= level <= 9:
                        for filename in os.listdir(item_path):
                            if filename.endswith('_журнал.xlsx') and not filename.startswith('~$'):
                                class_name = filename.split('_журнал')[0].replace('_', '-')
                                journal = {
                                    'path': os.path.join(item_path, filename),
                                    'name': filename,
                                    'level': level,
                                    'class_name': class_name,
                                }
                                cb = QCheckBox(f"{journal['class_name']} ({level})")
                                cb.setProperty('journal_data', journal)
                                cb.stateChanged.connect(self.update_check_button)
                                self.class_checkboxes.append(cb)
                                self.classes_layout.addWidget(cb)
                                found_any = True
        except Exception as e:
            self.append_to_status(f"Ошибка сканирования: {str(e)}")

        if found_any:
            self.classes_layout.addStretch()
            self.append_to_status(f"Найдено классов: {len(self.class_checkboxes)}")
            self.check_btn.setEnabled(True)
        else:
            self.append_to_status("Журналы 5-9 классов не найдены")
            self.check_btn.setEnabled(False)

    def select_all_classes(self):
        for cb in self.class_checkboxes:
            cb.setChecked(True)

    def deselect_all_classes(self):
        for cb in self.class_checkboxes:
            cb.setChecked(False)

    def get_selected_classes(self):
        selected = []
        for cb in self.class_checkboxes:
            if cb.isChecked():
                journal_data = cb.property('journal_data')
                if journal_data:
                    selected.append(journal_data)
        return selected

    def update_check_button(self):
        has_selected = len(self.get_selected_classes()) > 0
        self.check_btn.setEnabled(has_selected)

    # ================================================================
    # Запуск проверки
    # ================================================================
    def check_results(self):
        if self._is_loading:
            return
        selected_classes = self.get_selected_classes()
        if not selected_classes:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один класс!")
            return

        self._is_loading = True
        self.check_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.results_table.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(0)
        self.all_results = []

        if self.journals_folder_edit.text():
            results_folder = os.path.join(
                self.journals_folder_edit.text(), "Результаты проверки"
            )
        else:
            results_folder = os.path.join(
                os.path.expanduser("~"), "Результаты проверки"
            )
        os.makedirs(results_folder, exist_ok=True)

        self.append_to_status("Проверка запущена...")
        QApplication.processEvents()
        QTimer.singleShot(50, lambda: self._run_check(selected_classes, results_folder))

    def _run_check(self, selected_classes, results_folder):
        try:
            total = len(selected_classes)
            for i, journal_data in enumerate(selected_classes):
                class_name = journal_data['class_name']
                self.append_to_status(f"Проверка {class_name} ({i + 1}/{total})...")
                QApplication.processEvents()
                self._check_journal(journal_data['path'], class_name)
            self.display_all_results()
            self.clear_filters()
            if self.all_results:
                self._auto_save_report(results_folder)
        except Exception as e:
            self.append_to_status(f"Ошибка проверки: {str(e)}")
        finally:
            self._is_loading = False
            self.check_btn.setEnabled(True)
            if self.all_results:
                self.export_excel_btn.setEnabled(True)

    # ================================================================
    # Проверка журнала
    # ================================================================
    def _check_journal(self, journal_path, class_name):
        wb = None
        try:
            if not os.path.exists(journal_path):
                return
            wb = load_workbook(journal_path, data_only=True)
            for sheet_name in wb.sheetnames:
                try:
                    sheet = wb[sheet_name]
                    subject_name = "Неизвестно"
                    if sheet.cell(row=1, column=1).value:
                        subject_cell = str(sheet.cell(row=1, column=1).value)
                        if "Предмет:" in subject_cell:
                            subject_name = subject_cell.replace("Предмет:", "").strip()

                    t1_col = t2_col = t3_col = year_col = gpa_col = None
                    for col in range(3, min(sheet.max_column + 1, 500)):
                        type_val = sheet.cell(row=6, column=col).value
                        if type_val == 'итог':
                            period_val = sheet.cell(row=4, column=col).value
                            if period_val == 'Т1':
                                t1_col = col
                            elif period_val == 'Т2':
                                t2_col = col
                            elif period_val == 'Т3':
                                t3_col = col
                            elif period_val == 'Год':
                                year_col = col
                            elif period_val == 'ГПА':
                                gpa_col = col

                    if not all([t1_col, t2_col, t3_col, year_col]):
                        continue

                    periods = self._find_period_boundaries(sheet)
                    start_row = 7
                    students_count = 0
                    while sheet.cell(row=start_row + students_count, column=2).value:
                        students_count += 1
                        if students_count > 200:
                            break

                    for row in range(start_row, start_row + students_count):
                        student_name = sheet.cell(row=row, column=2).value
                        if not student_name:
                            continue
                        student_name = str(student_name).strip()
                        t1_val = sheet.cell(row=row, column=t1_col).value
                        t2_val = sheet.cell(row=row, column=t2_col).value
                        t3_val = sheet.cell(row=row, column=t3_col).value
                        gpa_val = sheet.cell(row=row, column=gpa_col).value if gpa_col else None
                        year_val = sheet.cell(row=row, column=year_col).value
                        if not year_val:
                            continue

                        t1_avg = self._calculate_period_average(
                            sheet, row, periods['Т1'][0], periods['Т1'][1]
                        ) if 'Т1' in periods else None
                        t2_avg = self._calculate_period_average(
                            sheet, row, periods['Т2'][0], periods['Т2'][1]
                        ) if 'Т2' in periods else None
                        t3_avg = self._calculate_period_average(
                            sheet, row, periods['Т3'][0], periods['Т3'][1]
                        ) if 'Т3' in periods else None

                        result = self._process_result(
                            class_name, student_name, subject_name,
                            t1_val, t2_val, t3_val, gpa_val, year_val,
                            t1_avg, t2_avg, t3_avg,
                        )
                        if result:
                            self.all_results.append(result)
                except Exception:
                    continue
        except Exception as e:
            self.append_to_status(f"Ошибка в {class_name}: {str(e)}")
        finally:
            if wb:
                try:
                    wb.close()
                except Exception:
                    pass

    def _find_period_boundaries(self, sheet):
        periods = {}
        current_period = None
        current_start = None
        for col in range(3, min(sheet.max_column + 1, 500)):
            try:
                type_val = sheet.cell(row=6, column=col).value
                if type_val == 'итог':
                    if current_period and current_start is not None:
                        periods[current_period] = (current_start, col - 1)
                        current_period = None
                        current_start = None
                    continue
                month_val = sheet.cell(row=4, column=col).value
                if month_val is None:
                    continue
                if type_val and ('оц' in str(type_val).lower() or 'урок' in str(type_val).lower()):
                    try:
                        month = int(month_val)
                        if 9 <= month <= 11:
                            new_period = 'Т1'
                        elif month == 12 or 1 <= month <= 2:
                            new_period = 'Т2'
                        elif 3 <= month <= 5:
                            new_period = 'Т3'
                        else:
                            continue
                        if current_period is None:
                            current_period = new_period
                            current_start = col
                        elif current_period != new_period:
                            if (current_period == 'Т1' and new_period == 'Т2' and month == 12) or \
                               (current_period == 'Т2' and new_period == 'Т3' and month == 3):
                                periods[current_period] = (current_start, col - 1)
                                current_period = new_period
                                current_start = col
                    except Exception:
                        pass
            except Exception:
                continue
        if current_period and current_start is not None:
            periods[current_period] = (current_start, min(sheet.max_column, 499))
        return periods

    def _calculate_period_average(self, sheet, student_row, start_col, end_col):
        marks = []
        for col in range(start_col, end_col + 1):
            try:
                header_value = sheet.cell(row=6, column=col).value
                if header_value:
                    header_str = str(header_value).lower().strip()
                    if 'оц' in header_str or 'урок' in header_str:
                        cell_value = sheet.cell(row=student_row, column=col).value
                        if cell_value:
                            marks.extend(self._parse_mark_cell(cell_value))
            except Exception:
                continue
        if marks:
            return round(sum(marks) / len(marks), 2)
        return None

    def _parse_mark_cell(self, cell_value):
        if not cell_value:
            return []
        cell_str = str(cell_value).strip()
        marks = []
        for part in cell_str.split(','):
            part = part.strip()
            if part in ['н', 'б', '']:
                continue
            if '(' in part and ')' in part:
                try:
                    mark_part = part.split('(')[0].strip()
                    coeff_part = part.split('(')[1].split(')')[0].strip()
                    coeff_clean = ''.join(c for c in coeff_part if c.isdigit())
                    if mark_part in ['2', '3', '4', '5']:
                        mark_int = int(mark_part)
                        coeff = int(coeff_clean) if coeff_clean else 1
                        marks.extend([mark_int] * coeff)
                except Exception:
                    pass
            elif part in ['2', '3', '4', '5']:
                marks.append(int(part))
        return marks

    def _get_expected_period_mark(self, avg_float):
        if avg_float >= 4.6:
            return 5
        elif avg_float >= 3.6:
            return 4
        elif avg_float >= 2.6:
            return 3
        else:
            return 'А/З'

    def _get_expected_year_mark(self, avg_float):
        if avg_float >= 4.5:
            return 5
        elif avg_float >= 3.5:
            return 4
        elif avg_float >= 2.5:
            return 3
        else:
            return 2

    def _safe_to_int_mark(self, val):
        if val is None:
            return None
        if isinstance(val, str):
            val_clean = val.strip()
            if val_clean in ['А/З', 'НПА']:
                return val_clean
            if val_clean == '' or val_clean == '-':
                return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    def _process_result(self, class_name, student_name, subject_name,
                        t1_val, t2_val, t3_val, gpa_val, year_val,
                        t1_avg, t2_avg, t3_avg):
        t1 = self._safe_to_int_mark(t1_val)
        t2 = self._safe_to_int_mark(t2_val)
        t3 = self._safe_to_int_mark(t3_val)
        gpa = self._safe_to_int_mark(gpa_val)
        year = self._safe_to_int_mark(year_val)

        has_debt = False
        has_npa = False
        missing_gpa = False
        missing_period = False

        if t1 is None or t2 is None or t3 is None:
            missing_period = True
        if gpa is None:
            missing_gpa = True
        elif isinstance(gpa, str) and gpa == 'А/З':
            has_debt = True
        elif isinstance(gpa, str) and gpa == 'НПА':
            has_npa = True

        valid_values = [v for v in [t1, t2, t3, gpa] if isinstance(v, int)]

        if missing_period:
            status_text = '⚠️ НЕТ ДАННЫХ'
            status_type = 'missing_data'
            calculated = calculated_mark = '-'
        elif missing_gpa:
            status_text = '⚠️ НЕТ ГПА'
            status_type = 'missing_gpa'
            calculated = calculated_mark = '-'
        elif has_debt:
            status_text = '⚠️ ДОЛГ (А/З)'
            status_type = 'debt'
            calculated = calculated_mark = '-'
        elif has_npa:
            status_text = '⚠️ НПА'
            status_type = 'npa'
            calculated = calculated_mark = '-'
        elif len(valid_values) == 0:
            status_text = '⚠️ НЕТ ДАННЫХ'
            status_type = 'missing_data'
            calculated = calculated_mark = '-'
        else:
            calculated = round(sum(valid_values) / len(valid_values), 2)
            calculated_mark = self._get_expected_year_mark(calculated)
            if isinstance(year, int):
                if calculated_mark != year:
                    status_text = '❌ НЕ СОВПАДАЕТ'
                    status_type = 'mismatch'
                else:
                    status_text = '✅ СОВПАДАЕТ'
                    status_type = 'match'
            else:
                status_text = '⚠️ НЕТ ГОДОВОЙ'
                status_type = 'missing_data'
                calculated_mark = '-'

        return {
            'class': class_name,
            'student': student_name,
            'subject': subject_name,
            't1_avg': str(t1_avg) if t1_avg is not None else '-',
            't1': str(t1_val) if t1_val is not None else '-',
            't2_avg': str(t2_avg) if t2_avg is not None else '-',
            't2': str(t2_val) if t2_val is not None else '-',
            't3_avg': str(t3_avg) if t3_avg is not None else '-',
            't3': str(t3_val) if t3_val is not None else '-',
            'gpa': str(gpa_val) if gpa_val is not None else '-',
            'calculated': str(calculated) if calculated != '-' else '-',
            'calculated_mark': str(calculated_mark) if calculated_mark != '-' else '-',
            'actual_mark': str(year_val) if year_val is not None else '-',
            'status': status_text,
            'status_type': status_type,
        }

    # ================================================================
    # Авто-сохранение отчёта
    # ================================================================
    def _auto_save_report(self, results_folder):
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_path = os.path.join(
                results_folder, f"Отчет_проверки_итогов_5-9_{timestamp}.xlsx"
            )
            self._save_excel_to_path(file_path)
            self.last_export_path = file_path
            self.append_to_status(f"Отчет сохранен: {os.path.basename(file_path)}")
            self._show_save_notification(file_path)
        except Exception as e:
            self.append_to_status(f"Ошибка сохранения отчета: {str(e)}")

    def _show_save_notification(self, file_path):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Проверка завершена")
        msg_box.setText("Отчет успешно сохранен!")
        msg_box.setInformativeText(
            f"Файл: {os.path.basename(file_path)}\n"
            f"Всего записей: {len(self.all_results)}"
        )
        msg_box.setIcon(QMessageBox.Icon.Information)
        open_btn = msg_box.addButton(
            "📂 Открыть отчет", QMessageBox.ButtonRole.AcceptRole
        )
        msg_box.addButton("Закрыть", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(open_btn)
        msg_box.exec()
        if msg_box.clickedButton() == open_btn:
            try:
                if os.path.exists(file_path):
                    os.startfile(file_path)
            except Exception:
                pass

    def _save_excel_to_path(self, file_path):
        wb = Workbook()
        ws = wb.active
        ws.title = "Проверка итогов 5-9"
        headers = [
            'Класс', 'Ученик', 'Предмет',
            'ср. Т1', 'Т1', 'ср. Т2', 'Т2', 'ср. Т3', 'Т3',
            'ГПА', 'ср. балл', 'ГОД должно', 'ГОД выст.', 'Статус',
        ]
        ws.append(headers)

        header_font = Font(bold=True, color="FFFFFF", size=10)
        header_fill = PatternFill(
            start_color="7C3AED", end_color="7C3AED", fill_type="solid"
        )
        header_alignment = Alignment(
            horizontal='center', vertical='center', wrap_text=True
        )
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

        red_fill = PatternFill(
            start_color="FFB4B4", end_color="FFB4B4", fill_type="solid"
        )
        for result in self.all_results:
            row = [
                result.get('class', ''), result.get('student', ''),
                result.get('subject', ''),
                result.get('t1_avg', '-'), result.get('t1', '-'),
                result.get('t2_avg', '-'), result.get('t2', '-'),
                result.get('t3_avg', '-'), result.get('t3', '-'),
                result.get('gpa', '-'),
                result.get('calculated', '-'), result.get('calculated_mark', '-'),
                result.get('actual_mark', '-'), result.get('status', ''),
            ]
            ws.append(row)

        for row_idx in range(2, ws.max_row + 1):
            for mark_col, avg_col in [(5, 4), (7, 6), (9, 8)]:
                mark_cell = ws.cell(row=row_idx, column=mark_col)
                avg_cell = ws.cell(row=row_idx, column=avg_col)
                if (mark_cell.value and mark_cell.value != '-' and
                        avg_cell.value and avg_cell.value != '-'):
                    try:
                        mark = int(str(mark_cell.value).strip())
                        avg = float(str(avg_cell.value))
                        expected = self._get_expected_period_mark(avg)
                        if isinstance(expected, int) and expected != mark:
                            mark_cell.fill = red_fill
                    except Exception:
                        pass

            actual_cell = ws.cell(row=row_idx, column=13)
            expected_cell = ws.cell(row=row_idx, column=12)
            if (actual_cell.value and actual_cell.value != '-' and
                    expected_cell.value and expected_cell.value != '-'):
                try:
                    if int(str(expected_cell.value).strip()) != int(str(actual_cell.value).strip()):
                        actual_cell.fill = red_fill
                except Exception:
                    pass

        last_col_letter = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A1:{last_col_letter}{ws.max_row}"
        ws.freeze_panes = 'A2'

        col_widths = {'A': 8, 'B': 35, 'C': 28}
        for col_letter, width in col_widths.items():
            ws.column_dimensions[col_letter].width = width
        for col_idx in range(4, len(headers) + 1):
            col_letter = get_column_letter(col_idx)
            max_length = 0
            for row in range(1, ws.max_row + 1):
                cell = ws.cell(row=row, column=col_idx)
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max_length + 3, 16)

        data_alignment = Alignment(horizontal='center', vertical='center')
        for row in range(2, ws.max_row + 1):
            for col in range(1, len(headers) + 1):
                cell = ws.cell(row=row, column=col)
                cell.alignment = data_alignment
                if row % 2 == 0:
                    cell.fill = PatternFill(
                        start_color="F5F3FF", end_color="F5F3FF", fill_type="solid"
                    )
        wb.save(file_path)
        self.last_export_path = file_path

    # ================================================================
    # Фильтры
    # ================================================================
    def apply_filter(self):
        if not self.all_results or self._is_loading:
            return
        class_filter = self.filter_class.text().lower()
        student_filter = self.filter_student.text().lower()
        subject_filter = self.filter_subject.text().lower()
        status_filter = self.filter_status.currentText()

        filtered_results = []
        for result in self.all_results:
            if class_filter and class_filter not in str(result.get('class', '')).lower():
                continue
            if student_filter and student_filter not in str(result.get('student', '')).lower():
                continue
            if subject_filter and subject_filter not in str(result.get('subject', '')).lower():
                continue
            if status_filter != "Все статусы" and result.get('status', '') != status_filter:
                continue
            filtered_results.append(result)

        self._safe_update_table(filtered_results)
        self.append_to_status(
            f"Показано: {len(filtered_results)} из {len(self.all_results)} записей"
        )

    def clear_filters(self):
        self.filter_class.clear()
        self.filter_student.clear()
        self.filter_subject.clear()
        self.filter_status.setCurrentIndex(0)
        self.display_all_results()

    # ================================================================
    # Таблица
    # ================================================================
    def _safe_update_table(self, results):
        try:
            self.results_table.setUpdatesEnabled(False)
            self.results_table.setSortingEnabled(False)
            if not results:
                self.results_table.setRowCount(0)
                self.results_table.setColumnCount(0)
                return

            headers = [
                'Класс', 'Ученик', 'Предмет',
                'ср. Т1', 'Т1', 'ср. Т2', 'Т2', 'ср. Т3', 'Т3',
                'ГПА', 'ср. балл', 'ГОД должно', 'ГОД выст.', 'Статус',
            ]
            self.results_table.setColumnCount(len(headers))
            self.results_table.setHorizontalHeaderLabels(headers)
            self.results_table.setRowCount(len(results))

            red_bg = QColor(255, 180, 180)
            for i, result in enumerate(results):
                col = 0
                self._set_item(i, col, result.get('class', '')); col += 1
                self._set_item(i, col, result.get('student', '')); col += 1

                subject_display = str(result.get('subject', ''))
                if len(subject_display) > 28:
                    subject_display = subject_display[:25] + '...'
                item = QTableWidgetItem(subject_display)
                item.setToolTip(str(result.get('subject', '')))
                self.results_table.setItem(i, col, item); col += 1

                self._set_item(i, col, result.get('t1_avg', '-')); col += 1
                item = QTableWidgetItem(str(result.get('t1', '-')))
                self._check_period_mismatch(result, 't1', 't1_avg', item, red_bg)
                self.results_table.setItem(i, col, item); col += 1

                self._set_item(i, col, result.get('t2_avg', '-')); col += 1
                item = QTableWidgetItem(str(result.get('t2', '-')))
                self._check_period_mismatch(result, 't2', 't2_avg', item, red_bg)
                self.results_table.setItem(i, col, item); col += 1

                self._set_item(i, col, result.get('t3_avg', '-')); col += 1
                item = QTableWidgetItem(str(result.get('t3', '-')))
                self._check_period_mismatch(result, 't3', 't3_avg', item, red_bg)
                self.results_table.setItem(i, col, item); col += 1

                self._set_item(i, col, result.get('gpa', '-')); col += 1
                self._set_item(i, col, result.get('calculated', '-')); col += 1
                self._set_item(i, col, result.get('calculated_mark', '-')); col += 1

                item = QTableWidgetItem(str(result.get('actual_mark', '-')))
                self._check_year_mismatch(result, item, red_bg)
                self.results_table.setItem(i, col, item); col += 1

                status_item = QTableWidgetItem(str(result.get('status', '')))
                status_type = result.get('status_type', '')
                if status_type == 'match':
                    status_item.setBackground(QColor(209, 250, 229))   # green-100
                    status_item.setForeground(QColor(6, 95, 70))       # green-800
                elif status_type == 'mismatch':
                    status_item.setBackground(QColor(254, 202, 202))   # red-200
                    status_item.setForeground(QColor(153, 27, 27))     # red-800
                elif status_type == 'missing_gpa':
                    status_item.setBackground(QColor(254, 240, 138))   # yellow-200
                    status_item.setForeground(QColor(133, 77, 14))     # yellow-800
                elif status_type in ['debt', 'npa']:
                    status_item.setBackground(QColor(254, 215, 170))   # orange-200
                    status_item.setForeground(QColor(124, 45, 18))     # orange-800
                elif status_type == 'missing_data':
                    status_item.setBackground(QColor(226, 232, 240))   # slate-200
                    status_item.setForeground(QColor(30, 41, 59))      # slate-800
                self.results_table.setItem(i, col, status_item)

            self.results_table.resizeColumnsToContents()
            if self.results_table.columnCount() > 2:
                self.results_table.setColumnWidth(0, 70)
                self.results_table.setColumnWidth(1, 200)
                self.results_table.setColumnWidth(2, 200)
        finally:
            self.results_table.setUpdatesEnabled(True)

    def _check_period_mismatch(self, result, mark_key, avg_key, item, red_bg):
        mark_val = result.get(mark_key, '-')
        avg_val = result.get(avg_key, '-')
        if mark_val != '-' and avg_val != '-':
            try:
                mark = int(str(mark_val).strip())
                avg_float = float(str(avg_val))
                expected = self._get_expected_period_mark(avg_float)
                if isinstance(expected, int) and expected != mark:
                    item.setBackground(red_bg)
            except Exception:
                pass

    def _check_year_mismatch(self, result, item, red_bg):
        calc_mark_str = str(result.get('calculated_mark', '-'))
        actual_str = str(result.get('actual_mark', '-'))
        if calc_mark_str != '-' and actual_str != '-':
            try:
                if int(calc_mark_str) != int(actual_str):
                    item.setBackground(red_bg)
            except Exception:
                pass

    def _set_item(self, row, col, text):
        try:
            item = QTableWidgetItem(str(text))
            self.results_table.setItem(row, col, item)
        except Exception:
            pass

    def display_all_results(self):
        if self.all_results:
            self._safe_update_table(self.all_results)

    def export_to_excel(self):
        if not self.all_results:
            QMessageBox.warning(self, "Ошибка", "Нет данных для экспорта!")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчет",
            f"Отчет_проверки_итогов_5-9_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "Excel files (*.xlsx)",
        )
        if not file_path:
            return
        try:
            self._save_excel_to_path(file_path)
            self._show_save_notification(file_path)
        except Exception as e:
            self.append_to_status(f"Ошибка сохранения: {str(e)}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить отчет:\n{str(e)}"
            )