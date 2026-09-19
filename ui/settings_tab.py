# -*- coding: utf-8 -*-
import json
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


class SettingsTab(QWidget):
    """Вкладка настроек: статус авторизации + выбор учебного года"""

    auth_successful = Signal(object)
    academic_year_changed = Signal(int)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.auth = None
        self.current_academic_year_id = 14
        self.initUI()
        self.load_saved_settings()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # === СТАТУС АВТОРИЗАЦИИ ===
        status_group = QGroupBox("🔐 Статус авторизации")
        status_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 13pt;
                border: 2px solid #e0e0e0; border-radius: 10px;
                margin-top: 1ex; padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 10px 0 10px;
            }
        """)
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(15)

        status_widget = QWidget()
        status_row = QHBoxLayout(status_widget)
        status_row.setContentsMargins(0, 0, 0, 0)

        self.status_icon = QLabel()
        self.status_icon.setFixedSize(24, 24)
        status_row.addWidget(self.status_icon)

        self.status_text = QLabel("Ожидание авторизации")
        self.status_text.setStyleSheet("font-size: 12pt;")
        status_row.addWidget(self.status_text)

        status_row.addStretch()

        self.user_info_label = QLabel("")
        self.user_info_label.setStyleSheet("color: #666;")
        status_row.addWidget(self.user_info_label)

        status_layout.addWidget(status_widget)

        info_label = QLabel(
            "ℹ️ Авторизация выполняется в отдельном окне при запуске.\n"
            "Чтобы войти под другим пользователем — нажмите «Сменить пользователя»."
        )
        info_label.setStyleSheet(
            "color: #666; font-size: 9pt; background-color: #f5f5f5; "
            "padding: 8px; border-radius: 5px;"
        )
        info_label.setWordWrap(True)
        status_layout.addWidget(info_label)

        self.relogin_btn = QPushButton("🔄 Сменить пользователя")
        self.relogin_btn.setMinimumHeight(36)
        self.relogin_btn.clicked.connect(self.relogin)
        status_layout.addWidget(self.relogin_btn)

        main_layout.addWidget(status_group)

        # === УЧЕБНЫЙ ГОД ===
        year_group = QGroupBox("📅 Учебный год")
        year_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 13pt;
                border: 2px solid #e0e0e0; border-radius: 10px;
                margin-top: 1ex; padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 10px 0 10px;
            }
        """)
        year_layout = QVBoxLayout(year_group)

        year_row = QHBoxLayout()
        year_row.addWidget(QLabel("Выберите учебный год:"))

        self.year_combo = QComboBox()
        self.year_combo.setMinimumWidth(200)
        self.year_combo.setStyleSheet("""
            QComboBox {
                padding: 8px 12px;
                border: 1px solid #cccccc;
                border-radius: 6px;
                font-size: 11pt;
            }
            QComboBox:focus { border: 2px solid #2196F3; }
        """)

        current_year = datetime.now().year
        current_month = datetime.now().month
        if current_month >= 9:
            current_academic_start = current_year
        else:
            current_academic_start = current_year - 1

        for i in range(-1, 4):
            start_year = current_academic_start + i
            end_year = start_year + 1
            aid = 13 + (start_year - 2025)
            self.year_combo.addItem(f"{start_year}-{end_year}", aid)

        default_aid = 13 + (current_academic_start - 2025)
        default_index = self.year_combo.findData(default_aid)
        if default_index >= 0:
            self.year_combo.setCurrentIndex(default_index)

        self.year_combo.currentIndexChanged.connect(self.on_year_changed)
        year_row.addWidget(self.year_combo)
        year_row.addStretch()
        year_layout.addLayout(year_row)

        year_info = QLabel(
            "ℹ️ Выбранный учебный год применяется ко всем вкладкам:\n"
            "• Загрузка классов и групп\n"
            "• Проверка КТП\n"
            "• Скачивание журналов"
        )
        year_info.setStyleSheet(
            "color: #666; font-size: 9pt; background-color: #f5f5f5; "
            "padding: 8px; border-radius: 5px;"
        )
        year_info.setWordWrap(True)
        year_layout.addWidget(year_info)

        self.year_id_label = QLabel("")
        self.year_id_label.setStyleSheet("color: #999; font-size: 9pt;")
        year_layout.addWidget(self.year_id_label)

        main_layout.addWidget(year_group)
        main_layout.addStretch()

        self.update_year_display()

    # ================================================================
    #  АВТОРИЗАЦИЯ
    # ================================================================
    def set_auth(self, auth):
        """Установить объект авторизации (вызывается из MainWindow)."""
        self.auth = auth
        if auth:
            self.status_icon.setPixmap(
                self.style().standardPixmap(
                    QStyle.StandardPixmap.SP_DialogApplyButton
                ).scaled(24, 24)
            )
            self.status_text.setText("✅ Авторизован")
            self.status_text.setStyleSheet(
                "font-size: 12pt; color: #27ae60; font-weight: bold;"
            )
            self.user_info_label.setText(f"PID: {auth.pid}")
        else:
            self.status_icon.setPixmap(
                self.style().standardPixmap(
                    QStyle.StandardPixmap.SP_DialogCancelButton
                ).scaled(24, 24)
            )
            self.status_text.setText("❌ Не авторизован")
            self.status_text.setStyleSheet(
                "font-size: 12pt; color: #c0392b;"
            )
            self.user_info_label.setText("")

    def relogin(self):
        """Сбросить сессию и открыть окно входа заново."""
        reply = QMessageBox.question(
            self, "Смена пользователя",
            "Сбросить текущую сессию и войти заново?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Удаляем session.pkl
        from pathlib import Path
        session_file = Path.home() / ".ejd_checker" / "session.pkl"
        if session_file.exists():
            session_file.unlink()

        # Открываем окно входа заново
        from ui.auth_window import AuthWindow
        self.auth_window = AuthWindow()
        self.auth_window.show()

        # Закрываем главное окно
        if self.main_window:
            self.main_window.close()

    # ================================================================
    #  УЧЕБНЫЙ ГОД
    # ================================================================
    def update_year_display(self):
        aid = self.year_combo.currentData()
        year_text = self.year_combo.currentText()
        self.year_id_label.setText(f"ID учебного года (aid): {aid} | {year_text}")

    def on_year_changed(self, index):
        aid = self.year_combo.currentData()
        if aid is None:
            return
        self.current_academic_year_id = aid
        self.update_year_display()
        self.save_settings()
        self.academic_year_changed.emit(aid)
        if self.auth:
            self.auth.aid = str(aid)
            self.auth.curr_aid = str(aid)

    def get_settings_file(self):
        settings_dir = Path.home() / '.ejd_checker'
        settings_dir.mkdir(exist_ok=True)
        return settings_dir / 'settings.json'

    def save_settings(self):
        try:
            settings = {
                'academic_year_id': self.year_combo.currentData(),
            }
            with open(self.get_settings_file(), 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")

    def load_saved_settings(self):
        settings_file = self.get_settings_file()
        if not settings_file.exists():
            return
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            aid = settings.get('academic_year_id')
            if aid:
                index = self.year_combo.findData(aid)
                if index >= 0:
                    self.year_combo.setCurrentIndex(index)
                    self.current_academic_year_id = aid
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")