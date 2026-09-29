# -*- coding: utf-8 -*-
"""
Вкладка «Кружки ПДОУ».
Загрузка списка групп ПДОУ через esz.mos.ru и отображение в таблице.
"""
import os
import sys
from datetime import datetime

from PySide6.QtWidgets import *
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QColor

from collector_pdou import PDOUCollector


class PDOULoadThread(QThread):
    """Поток для загрузки списка групп ПДОУ"""
    finished = Signal(list)
    error = Signal(str)
    log_message = Signal(str)

    def __init__(self, auth):
        super().__init__()
        self.auth = auth

    def run(self):
        try:
            collector = PDOUCollector(self.auth)
            collector.log_callback = lambda text: self.log_message.emit(text)
            groups = collector.get_all_groups()
            self.finished.emit(groups)
        except Exception as e:
            import traceback
            err = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            self.error.emit(err)
            self.finished.emit([])


class PDOUTab(QWidget):
    """Вкладка просмотра групп ПДОУ (кружки и секции)"""

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.auth = None
        self.all_groups = []
        self.filtered_groups = []
        self.initUI()

    # ================================================================
    #  АВТОРИЗАЦИЯ (снаружи)
    # ================================================================
    def on_auth_updated(self, auth):
        self.auth = auth
        if auth:
            self.load_btn.setEnabled(True)
        else:
            self.load_btn.setEnabled(False)

    # ================================================================
    #  UI
    # ================================================================
    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # === ПАНЕЛЬ УПРАВЛЕНИЯ ===
        control_group = QGroupBox("Управление")
        control_layout = QHBoxLayout(control_group)

        self.load_btn = QPushButton("📋 Загрузить список кружков/ПДОУ")
        self.load_btn.setEnabled(False)
        self.load_btn.setMinimumHeight(32)
        self.load_btn.clicked.connect(self.load_groups)
        control_layout.addWidget(self.load_btn)

        control_layout.addStretch()

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("font-weight: bold;")
        control_layout.addWidget(self.stats_label)

        main_layout.addWidget(control_group)

        # === ПРОГРЕСС-БАР ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #cccccc; border-radius: 4px;
                text-align: center; height: 24px; }
            QProgressBar::chunk { background-color: #4CAF50; border-radius: 4px; }
        """)
        main_layout.addWidget(self.progress_bar)

        # === ФИЛЬТРЫ ===
        filter_group = QGroupBox("Фильтры")
        filter_layout = QHBoxLayout(filter_group)

        filter_layout.addWidget(QLabel("Поиск:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Название группы / программа / педагог..."
        )
        self.search_edit.setMinimumWidth(280)
        self.search_edit.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.search_edit)

        filter_layout.addWidget(QLabel("Статус группы:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все", "all")
        self.status_filter.addItem("Активные", 1)
        self.status_filter.addItem("Завершённые", 2)
        self.status_filter.setMinimumWidth(140)
        self.status_filter.currentIndexChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.status_filter)

        self.clear_filters_btn = QPushButton("Очистить")
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        filter_layout.addWidget(self.clear_filters_btn)

        filter_layout.addStretch()
        main_layout.addWidget(filter_group)

        # === ТАБЛИЦА ===
        self.groups_table = QTableWidget()
        self.groups_table.setAlternatingRowColors(False)
        self.groups_table.setSortingEnabled(True)
        self.groups_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.groups_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.groups_table.horizontalHeader().setStretchLastSection(True)
        self.groups_table.setColumnCount(7)
        self.groups_table.setHorizontalHeaderLabels([
            "Код",
            "Название группы",
            "Педагог",
            "Программа",
            "Даты обучения",
            "Ёмкость",
            "Записано",
        ])
        self.groups_table.verticalHeader().setDefaultSectionSize(50)
        main_layout.addWidget(self.groups_table)

        # === ЭКСПОРТ ===
        export_layout = QHBoxLayout()
        export_layout.addStretch()
        self.export_btn = QPushButton("📊 Экспорт в Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_to_excel)
        export_layout.addWidget(self.export_btn)
        main_layout.addLayout(export_layout)

        # === КОНСОЛЬ ===
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(140)
        self.console.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 10px; "
            "background-color: #1e1e1e; color: #d4d4d4;"
        )
        main_layout.addWidget(self.console)

    def _log(self, text):
        self.console.appendPlainText(str(text))
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ================================================================
    #  ЗАГРУЗКА
    # ================================================================
    def load_groups(self):
        if not self.auth:
            QMessageBox.warning(
                self, "Ошибка",
                "Нет авторизации. Перезапустите приложение."
            )
            return

        self.load_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Загрузка групп ПДОУ...")
        self.groups_table.setRowCount(0)
        self.all_groups = []
        self.console.clear()

        self.load_thread = PDOULoadThread(self.auth)
        self.load_thread.finished.connect(self.on_load_finished)
        self.load_thread.error.connect(self.on_load_error)
        self.load_thread.log_message.connect(self._log)
        self.load_thread.start()

    def on_load_finished(self, groups):
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.load_btn.setEnabled(True)

        if not groups:
            QMessageBox.warning(
                self, "Внимание",
                "Не удалось получить список групп ПДОУ.\n"
                "Подробности в консоли ниже."
            )
            return

        self.all_groups = groups
        self.apply_filter()
        self.update_stats()
        self.export_btn.setEnabled(True)

        QMessageBox.information(
            self, "Готово",
            f"✅ Загружено групп: {len(groups)}"
        )

    def on_load_error(self, error):
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка загрузки", f"Ошибка:\n{error}")

    # ================================================================
    #  ФИЛЬТРЫ / СТАТИСТИКА
    # ================================================================
    def update_stats(self):
        total = len(self.all_groups)
        active = sum(
            1 for g in self.all_groups
            if g.get("serviceClassStatus") == 1
        )
        done = sum(
            1 for g in self.all_groups
            if g.get("serviceClassStatus") == 2
        )
        self.stats_label.setText(
            f"Всего: {total} | Активных: {active} | Завершённых: {done}"
        )

    def apply_filter(self):
        search_text = self.search_edit.text().lower().strip()
        status_filter = self.status_filter.currentData()

        filtered = []
        for g in self.all_groups:
            if search_text:
                haystack = " ".join([
                    str(g.get("name", "")),
                    str(g.get("serviceName", "")),
                    str(g.get("supervisorPerson", "")),
                    str(g.get("code", "")),
                ]).lower()
                if search_text not in haystack:
                    continue

            if status_filter != "all":
                if g.get("serviceClassStatus") != status_filter:
                    continue

            filtered.append(g)

        self.filtered_groups = filtered
        self.populate_table(filtered)

    def clear_filters(self):
        self.search_edit.clear()
        self.status_filter.setCurrentIndex(0)
        self.apply_filter()

    # ================================================================
    #  ТАБЛИЦА
    # ================================================================
    def populate_table(self, groups):
        self.groups_table.setSortingEnabled(False)
        self.groups_table.setUpdatesEnabled(False)
        self.groups_table.setRowCount(len(groups))

        green_bg = QColor(220, 255, 220)
        gray_bg = QColor(240, 240, 240)

        for i, g in enumerate(groups):
            status = g.get("serviceClassStatus")
            if status == 1:
                row_color = green_bg
            elif status == 2:
                row_color = gray_bg
            else:
                row_color = None

            def make_item(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
                it = QTableWidgetItem(str(text) if text is not None else "")
                it.setTextAlignment(align)
                if row_color:
                    it.setBackground(row_color)
                return it

            # 0: Код
            self.groups_table.setItem(i, 0, make_item(g.get("code", ""), Qt.AlignmentFlag.AlignCenter))

            # 1: Название группы
            name_item = make_item(g.get("name", "").strip())
            name_item.setToolTip(f"ID группы: {g.get('id')}")
            self.groups_table.setItem(i, 1, name_item)

            # 2: Педагог
            self.groups_table.setItem(i, 2, make_item(g.get("supervisorPerson", "")))

            # 3: Программа
            prog_item = make_item(g.get("serviceName", "").strip())
            prog_item.setToolTip(f"serviceId: {g.get('serviceId')}")
            self.groups_table.setItem(i, 3, prog_item)

            # 4: Даты обучения
            self.groups_table.setItem(i, 4, make_item(g.get("trainDates", ""), Qt.AlignmentFlag.AlignCenter))

            # 5: Ёмкость
            self.groups_table.setItem(i, 5, make_item(g.get("capacity", 0), Qt.AlignmentFlag.AlignCenter))

            # 6: Записано
            self.groups_table.setItem(i, 6, make_item(g.get("included", 0), Qt.AlignmentFlag.AlignCenter))

        self.groups_table.setUpdatesEnabled(True)
        self.groups_table.setSortingEnabled(True)

        # Ширины колонок
        self.groups_table.setColumnWidth(0, 90)
        self.groups_table.setColumnWidth(1, 280)
        self.groups_table.setColumnWidth(2, 220)
        self.groups_table.setColumnWidth(3, 320)
        self.groups_table.setColumnWidth(4, 190)
        self.groups_table.setColumnWidth(5, 90)
        self.groups_table.setColumnWidth(6, 90)

    # ================================================================
    #  ЭКСПОРТ
    # ================================================================
    def export_to_excel(self):
        if not self.filtered_groups:
            QMessageBox.warning(self, "Ошибка", "Нет данных для экспорта")
            return

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
        except ImportError:
            QMessageBox.warning(self, "Ошибка", "Модуль openpyxl не установлен")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Кружки_ПДОУ_{timestamp}.xlsx"

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", filename, "Excel files (*.xlsx)"
        )
        if not file_path:
            return

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Кружки ПДОУ"

            headers = [
                "Код", "Название группы", "Педагог", "Программа",
                "Даты обучения", "Ёмкость", "Записано", "Статус"
            ]
            ws.append(headers)

            header_font = Font(bold=True, color="FFFFFF", size=11)
            header_fill = PatternFill(
                start_color="2C3E50", end_color="2C3E50", fill_type="solid"
            )
            header_alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )

            for col in range(1, len(headers) + 1):
                c = ws.cell(row=1, column=col)
                c.font = header_font
                c.fill = header_fill
                c.alignment = header_alignment

            for g in self.filtered_groups:
                status_code = g.get("serviceClassStatus")
                if status_code == 1:
                    status_text = "Активна"
                elif status_code == 2:
                    status_text = "Завершена"
                else:
                    status_text = str(status_code or "")

                ws.append([
                    g.get("code", ""),
                    g.get("name", "").strip(),
                    g.get("supervisorPerson", ""),
                    g.get("serviceName", "").strip(),
                    g.get("trainDates", ""),
                    g.get("capacity", 0),
                    g.get("included", 0),
                    status_text,
                ])

            col_widths = {
                "A": 12, "B": 40, "C": 28, "D": 45,
                "E": 24, "F": 10, "G": 10, "H": 14,
            }
            for col_letter, width in col_widths.items():
                ws.column_dimensions[col_letter].width = width

            ws.auto_filter.ref = ws.dimensions
            ws.freeze_panes = "A2"

            wb.save(file_path)

            reply = QMessageBox.question(
                self, "Готово",
                f"Отчёт сохранён:\n{file_path}\n\nОткрыть файл?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                os.startfile(file_path)

        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка",
                f"Не удалось сохранить отчёт:\n{e}"
            )