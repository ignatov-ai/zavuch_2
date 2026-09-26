# -*- coding: utf-8 -*-
import json
import shutil
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


# === НОВАЯ ПАПКА ===
DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
AUTH_DATA_FILE = DATA_DIR / "auth_data.json"


# ============================================================
#  Поток импорта файла сессии
# ============================================================
class ImportSessionWorker(QThread):
    """
    Копирует указанный session.pkl в ~/.zavuch2/ и пробует залогиниться.
    Если рядом лежит auth_data.json — копирует и его.
    """
    done = Signal(dict)   # {"ok": bool, "reason": str, "auth_obj": dn_Auth | None}

    def __init__(self, source_path: str, copy_adjacent_auth_data: bool = True):
        super().__init__()
        self.source_path = source_path
        self.copy_adjacent_auth_data = copy_adjacent_auth_data

    def run(self):
        result = {"ok": False, "reason": "", "auth_obj": None}

        try:
            src = Path(self.source_path)
            if not src.exists():
                result["reason"] = f"Файл не найден: {src}"
                self.done.emit(result)
                return

            # 1. Копируем в ~/.zavuch2/session.pkl
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(SESSION_FILE))
            except Exception as e:
                result["reason"] = f"Не удалось скопировать файл: {e}"
                self.done.emit(result)
                return

            # 2. Если рядом лежит auth_data.json — тоже копируем
            if self.copy_adjacent_auth_data:
                adjacent = src.parent / "auth_data.json"
                if adjacent.exists():
                    try:
                        shutil.copy2(str(adjacent), str(AUTH_DATA_FILE))
                    except Exception:
                        pass  # не критично

            # 3. Пробуем загрузиться
            from auth import dn_Auth
            auth = dn_Auth()
            if auth.load_session():
                result["ok"] = True
                result["auth_obj"] = auth
                result["reason"] = f"Сессия из {src.name} рабочая"
            else:
                result["reason"] = (
                    "Файл скопирован, но API не принял сессию.\n"
                    "Вероятно, токен устарел или привязан к другому устройству.\n\n"
                    "Можно попробовать войти через браузер."
                )
        except Exception as e:
            result["reason"] = f"Ошибка: {e}"

        self.done.emit(result)


# ============================================================
#  Вкладка настроек
# ============================================================
class SettingsTab(QWidget):
    """Вкладка настроек: статус авторизации + выбор учебного года + импорт сессии"""

    auth_successful = Signal(object)
    academic_year_changed = Signal(int)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.auth = None
        self.current_academic_year_id = 14
        self.import_worker = None
        self.initUI()
        self.load_saved_settings()
        self.refresh_session_info()

    # ------------------------------------------------------------------
    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ============================================================
        #  СТАТУС АВТОРИЗАЦИИ
        # ============================================================
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
        status_layout.setSpacing(12)

        # --- Статус ---
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

        # --- Инфо ---
        info_label = QLabel(
            "ℹ️ Авторизация выполняется в отдельном окне при запуске.\n"
            "Чтобы войти под другим пользователем — нажмите «Сменить пользователя».\n"
            "Чтобы подключить сессию с другого компьютера — «Импортировать файл сессии»."
        )
        info_label.setStyleSheet(
            "color: #666; font-size: 9pt; background-color: #f5f5f5; "
            "padding: 8px; border-radius: 5px;"
        )
        info_label.setWordWrap(True)
        status_layout.addWidget(info_label)

        # --- Кнопки ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.relogin_btn = QPushButton("🔄 Сменить пользователя")
        self.relogin_btn.setMinimumHeight(36)
        self.relogin_btn.clicked.connect(self.relogin)
        btn_row.addWidget(self.relogin_btn)

        self.import_session_btn = QPushButton("📁 Импортировать файл сессии…")
        self.import_session_btn.setMinimumHeight(36)
        self.import_session_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280; color: white; font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #4b5563; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """)
        self.import_session_btn.clicked.connect(self.import_session)
        btn_row.addWidget(self.import_session_btn)

        btn_row.addStretch()
        status_layout.addLayout(btn_row)

        # --- Инфо о текущем файле сессии ---
        self.session_info_label = QLabel("")
        self.session_info_label.setStyleSheet(
            "color: #4b5563; font-size: 9pt; font-family: Consolas, monospace; "
            "background-color: #f9fafb; padding: 6px; border-radius: 5px; "
            "border: 1px solid #e5e7eb;"
        )
        self.session_info_label.setWordWrap(True)
        status_layout.addWidget(self.session_info_label)

        main_layout.addWidget(status_group)

        # ============================================================
        #  УЧЕБНЫЙ ГОД
        # ============================================================
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
    #  АВТОРИЗАЦИЯ: статус
    # ================================================================
    def set_auth(self, auth):
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
            self.status_text.setStyleSheet("font-size: 12pt; color: #c0392b;")
            self.user_info_label.setText("")

    # ================================================================
    #  ИНФО О ТЕКУЩЕМ ФАЙЛЕ СЕССИИ
    # ================================================================
    def refresh_session_info(self):
        """Обновляет подпись с путём, датой и размером session.pkl."""
        if not SESSION_FILE.exists():
            self.session_info_label.setText(
                f"📄 Файл сессии не найден:\n{SESSION_FILE}"
            )
            return

        try:
            stat = SESSION_FILE.stat()
            size_bytes = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M:%S")

            if size_bytes < 1024:
                size_str = f"{size_bytes} Б"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} КБ"
            else:
                size_str = f"{size_bytes / 1024 / 1024:.2f} МБ"

            auth_data_note = ""
            if AUTH_DATA_FILE.exists():
                auth_data_note = "\n✓ Рядом есть auth_data.json (auth_token + profile_id)"
            else:
                auth_data_note = "\n⚠️ auth_data.json отсутствует — может не хватить auth_token"

            self.session_info_label.setText(
                f"📄 Текущий файл сессии:\n{SESSION_FILE}\n"
                f"Изменён: {mtime}\n"
                f"Размер: {size_str}"
                f"{auth_data_note}"
            )
        except Exception as e:
            self.session_info_label.setText(
                f"📄 Текущий файл сессии:\n{SESSION_FILE}\n"
                f"⚠️ Не удалось прочитать информацию: {e}"
            )

    # ================================================================
    #  ИМПОРТ ФАЙЛА СЕССИИ
    # ================================================================
    def import_session(self):
        """Диалог выбора session.pkl и его импорт в ~/.zavuch2/."""
        start_dir = str(Path.home())

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл сессии (session.pkl)",
            start_dir,
            "Pickle session files (*.pkl);;Все файлы (*.*)"
        )

        if not file_path:
            return

        src = Path(file_path)
        if not src.exists():
            QMessageBox.warning(
                self, "Файл не найден",
                f"Файл не существует:\n{src}"
            )
            return

        # Подтверждение, если есть текущая сессия
        if SESSION_FILE.exists():
            answer = QMessageBox.question(
                self, "Подтверждение",
                f"Текущая сессия уже существует:\n{SESSION_FILE}\n\n"
                f"Заменить её на выбранный файл?\n{src}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.import_session_btn.setEnabled(False)
        self.relogin_btn.setEnabled(False)
        self.session_info_label.setText("[i] Импортирую файл сессии...")

        self.import_worker = ImportSessionWorker(str(src))
        self.import_worker.done.connect(self._on_import_finished)
        self.import_worker.start()

    def _on_import_finished(self, result: dict):
        self.import_session_btn.setEnabled(True)
        self.relogin_btn.setEnabled(True)
        self.refresh_session_info()

        if result.get("ok"):
            new_auth = result.get("auth_obj")
            self.set_auth(new_auth)
            # Сообщаем всем вкладкам через MainWindow
            self.auth_successful.emit(new_auth)

            QMessageBox.information(
                self, "Сессия импортирована",
                f"{result.get('reason', 'OK')}\n\n"
                f"Новая сессия активна для всех вкладок."
            )
        else:
            QMessageBox.warning(
                self, "Импорт не удался",
                result.get("reason", "Неизвестная ошибка")
            )

    # ================================================================
    #  СМЕНА ПОЛЬЗОВАТЕЛЯ
    # ================================================================
    def relogin(self):
        reply = QMessageBox.question(
            self, "Смена пользователя",
            "Сбросить текущую сессию и войти заново?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Удаляем session.pkl и auth_data.json из ~/.zavuch2
        for fname in ("session.pkl", "auth_data.json"):
            f = DATA_DIR / fname
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass

        self.set_auth(None)

        from ui.auth_window import AuthWindow
        self.auth_window = AuthWindow()
        self.auth_window.show()

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
        return DATA_DIR / 'settings.json'

    def save_settings(self):
        try:
            settings = {'academic_year_id': self.year_combo.currentData()}
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