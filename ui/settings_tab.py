# -*- coding: utf-8 -*-
"""
Вкладка «⚙️ Настройки».
- Статус авторизации
- Учебный год
- Экспорт / импорт сессий (ЭЖД и ПДОУ)
"""
import json
import zipfile
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QFileDialog, QMessageBox, QComboBox, QDialog,
    QDialogButtonBox, QCheckBox, QTextEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor


# ==== ПАПКА ====
DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)

# ==== ФАЙЛЫ ====
EJD_FILES = [
    "session.pkl",
    "auth_data.json",
    "credentials.json",
]
PDOU_FILES = [
    "pdou_token.json",
    "pdou_cookies.json",
]


class SessionExportDialog(QDialog):
    """
    Диалог экспорта. Показывает чекбоксы, что включать.
    """

    def __init__(self, parent=None, default_ejd=True, default_pdou=True):
        super().__init__(parent)
        self.setWindowTitle("Экспорт сессий")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        # Инфо
        info = QLabel(
            "Выберите, какие сессии включить в архив.\n"
            "Архив можно перенести на другой компьютер и импортировать.\n\n"
            "⚠️ Файлы содержат пароли и токены — храните архив "
            "в защищённом месте!"
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "color: #b91c1c; background-color: #fef2f2; "
            "padding: 8px; border-radius: 6px;"
        )
        layout.addWidget(info)

        # ЭЖД
        self.ejd_cb = QCheckBox("🔐 ЭЖД-сессия "
                                 "(session.pkl, auth_data.json, credentials.json)")
        self.ejd_cb.setChecked(default_ejd)
        layout.addWidget(self.ejd_cb)

        # ПДОУ
        self.pdou_cb = QCheckBox("🎨 ПДОУ-сессия "
                                  "(pdou_token.json, pdou_cookies.json)")
        self.pdou_cb.setChecked(default_pdou)
        layout.addWidget(self.pdou_cb)

        layout.addSpacing(8)

        # Кнопки
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selection(self):
        return self.ejd_cb.isChecked(), self.pdou_cb.isChecked()


class SessionImportDialog(QDialog):
    """
    Диалог импорта. Показывает, что есть в архиве, и что восстанавливать.
    """

    def __init__(self, parent=None, has_ejd=True, has_pdou=True):
        super().__init__(parent)
        self.setWindowTitle("Импорт сессий")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Выберите, что восстановить из архива.\n"
            "Существующие файлы будут перезаписаны."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(info)

        # ЭЖД
        self.ejd_cb = QCheckBox("🔐 Восстановить ЭЖД-сессию")
        self.ejd_cb.setChecked(has_ejd)
        self.ejd_cb.setEnabled(has_ejd)
        if not has_ejd:
            self.ejd_cb.setText("🔐 ЭЖД-сессия (нет в архиве)")
        layout.addWidget(self.ejd_cb)

        # ПДОУ
        self.pdou_cb = QCheckBox("🎨 Восстановить ПДОУ-сессию")
        self.pdou_cb.setChecked(has_pdou)
        self.pdou_cb.setEnabled(has_pdou)
        if not has_pdou:
            self.pdou_cb.setText("🎨 ПДОУ-сессия (нет в архиве)")
        layout.addWidget(self.pdou_cb)

        layout.addSpacing(8)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selection(self):
        return self.ejd_cb.isChecked(), self.pdou_cb.isChecked()


class SettingsTab(QWidget):
    """Вкладка настроек: статус авторизации + учебный год + экспорт сессий"""

    auth_successful = Signal(object)
    academic_year_changed = Signal(int)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.auth = None
        self.current_academic_year_id = 14
        self.initUI()
        self.load_saved_settings()
        self.refresh_session_status()

    # ================================================================
    #  UI
    # ================================================================
    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # === СТАТУС АВТОРИЗАЦИИ ===
        auth_group = QGroupBox("🔐 Статус авторизации")
        auth_group.setStyleSheet("""
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
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setSpacing(12)

        self.auth_status_label = QLabel("⏳ Ожидание авторизации")
        self.auth_status_label.setStyleSheet(
            "font-size: 11pt; color: #666; padding: 4px;"
        )
        auth_layout.addWidget(self.auth_status_label)

        info_label = QLabel(
            "ℹ️ Авторизация выполняется в отдельном окне при запуске.\n"
            "Смена пользователя — через кнопку ниже."
        )
        info_label.setStyleSheet(
            "color: #666; font-size: 9pt; background-color: #f5f5f5; "
            "padding: 8px; border-radius: 5px;"
        )
        info_label.setWordWrap(True)
        auth_layout.addWidget(info_label)

        self.relogin_btn = QPushButton("🔄 Сменить пользователя")
        self.relogin_btn.setMinimumHeight(36)
        self.relogin_btn.clicked.connect(self.relogin)
        auth_layout.addWidget(self.relogin_btn)

        main_layout.addWidget(auth_group)

        # === ЭКСПОРТ / ИМПОРТ СЕССИЙ ===
        export_group = QGroupBox("💾 Экспорт / Импорт сессий")
        export_group.setStyleSheet("""
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
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(10)

        hint = QLabel(
            "Перенос сессий на другой компьютер:\n"
            "1. Экспортируйте в .zip на этом компьютере.\n"
            "2. Скопируйте .zip на другой компьютер.\n"
            "3. Импортируйте там через кнопку ниже.\n\n"
            "⚠️ Архив содержит пароли и токены — храните его в защищённом месте."
        )
        hint.setStyleSheet(
            "color: #b45309; background-color: #fffbeb; "
            "padding: 8px; border-radius: 5px; font-size: 9pt;"
        )
        hint.setWordWrap(True)
        export_layout.addWidget(hint)

        # --- Кнопки экспорта ---
        exp_row = QHBoxLayout()
        exp_row.setSpacing(6)

        self.export_all_btn = QPushButton("📦 Экспорт всех сессий")
        self.export_all_btn.setMinimumHeight(34)
        self.export_all_btn.setStyleSheet("""
            QPushButton { background-color: #8b5cf6; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #7c3aed; }
        """)
        self.export_all_btn.clicked.connect(self.export_all_sessions)
        exp_row.addWidget(self.export_all_btn)

        self.export_ejd_btn = QPushButton("🔐 Только ЭЖД")
        self.export_ejd_btn.setMinimumHeight(34)
        self.export_ejd_btn.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.export_ejd_btn.clicked.connect(self.export_ejd_session)
        exp_row.addWidget(self.export_ejd_btn)

        self.export_pdou_btn = QPushButton("🎨 Только ПДОУ")
        self.export_pdou_btn.setMinimumHeight(34)
        self.export_pdou_btn.setStyleSheet("""
            QPushButton { background-color: #0ea5e9; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #0284c7; }
        """)
        self.export_pdou_btn.clicked.connect(self.export_pdou_session)
        exp_row.addWidget(self.export_pdou_btn)

        export_layout.addLayout(exp_row)

        # --- Импорт ---
        self.import_btn = QPushButton("📥 Импорт из архива (.zip)")
        self.import_btn.setMinimumHeight(36)
        self.import_btn.setStyleSheet("""
            QPushButton { background-color: #059669; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #047857; }
        """)
        self.import_btn.clicked.connect(self.import_sessions)
        export_layout.addWidget(self.import_btn)

        # --- Статус файлов ---
        status_label = QLabel("<b>Текущее состояние файлов:</b>")
        export_layout.addWidget(status_label)

        self.session_status_text = QTextEdit()
        self.session_status_text.setReadOnly(True)
        self.session_status_text.setMaximumHeight(120)
        self.session_status_text.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, monospace;
                font-size: 9pt;
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        export_layout.addWidget(self.session_status_text)

        self.refresh_status_btn = QPushButton("🔄 Обновить состояние")
        self.refresh_status_btn.setMaximumWidth(220)
        self.refresh_status_btn.clicked.connect(self.refresh_session_status)
        export_layout.addWidget(self.refresh_status_btn)

        main_layout.addWidget(export_group)

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
        self.auth = auth
        if auth:
            self.auth_status_label.setText("✅ Авторизован")
            self.auth_status_label.setStyleSheet(
                "font-size: 11pt; color: #059669; font-weight: bold;"
            )
        else:
            self.auth_status_label.setText("❌ Не авторизован")
            self.auth_status_label.setStyleSheet(
                "font-size: 11pt; color: #dc2626;"
            )

    def relogin(self):
        reply = QMessageBox.question(
            self, "Смена пользователя",
            "Сбросить текущую ЭЖД-сессию и войти заново?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Удаляем ЭЖД-сессию
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
    #  ЭКСПОРТ / ИМПОРТ СЕССИЙ
    # ================================================================
    def refresh_session_status(self):
        """Обновляет текстовое поле со статусом файлов."""
        lines = []
        lines.append("=== ЭЖД ===")
        for fname in EJD_FILES:
            fpath = DATA_DIR / fname
            if fpath.exists():
                mtime = datetime.fromtimestamp(fpath.stat().st_mtime).strftime(
                    "%d.%m.%Y %H:%M"
                )
                size = fpath.stat().st_size
                lines.append(f"  ✅ {fname:24s} {size:>8} Б, {mtime}")
            else:
                lines.append(f"  ❌ {fname}")

        lines.append("")
        lines.append("=== ПДОУ ===")
        for fname in PDOU_FILES:
            fpath = DATA_DIR / fname
            if fpath.exists():
                mtime = datetime.fromtimestamp(fpath.stat().st_mtime).strftime(
                    "%d.%m.%Y %H:%M"
                )
                size = fpath.stat().st_size
                lines.append(f"  ✅ {fname:24s} {size:>8} Б, {mtime}")
            else:
                lines.append(f"  ❌ {fname}")

        self.session_status_text.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    def _get_files_to_export(self, include_ejd: bool, include_pdou: bool):
        """Возвращает список существующих файлов для экспорта."""
        files = []
        if include_ejd:
            for fname in EJD_FILES:
                fpath = DATA_DIR / fname
                if fpath.exists():
                    files.append(fpath)
        if include_pdou:
            for fname in PDOU_FILES:
                fpath = DATA_DIR / fname
                if fpath.exists():
                    files.append(fpath)
        return files

    def _export_to_zip(self, zip_path: str, include_ejd: bool,
                       include_pdou: bool, label: str):
        """Общая функция экспорта в .zip."""
        files = self._get_files_to_export(include_ejd, include_pdou)
        if not files:
            QMessageBox.warning(
                self, "Нет данных",
                f"Нечего экспортировать ({label}).\n"
                "Соответствующие файлы не найдены."
            )
            return

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fpath in files:
                    zf.write(fpath, arcname=fpath.name)

            QMessageBox.information(
                self, "Готово",
                f"✅ Экспортировано файлов: {len(files)}\n\n"
                f"Архив: {zip_path}\n\n"
                "⚠️ Скопируйте архив на другой компьютер и импортируйте там."
            )
            self.refresh_session_status()
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка экспорта",
                f"Не удалось создать архив:\n{e}"
            )

    def export_all_sessions(self):
        """Экспорт ЭЖД + ПДОУ."""
        dlg = SessionExportDialog(self, default_ejd=True, default_pdou=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inc_ejd, inc_pdou = dlg.get_selection()
        if not inc_ejd and not inc_pdou:
            QMessageBox.warning(self, "Ошибка", "Ничего не выбрано.")
            return

        default_name = (
            f"zavuch2_sessions_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        zip_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить архив сессий", default_name,
            "ZIP archives (*.zip)"
        )
        if not zip_path:
            return

        self._export_to_zip(zip_path, inc_ejd, inc_pdou, "все")

    def export_ejd_session(self):
        """Экспорт только ЭЖД."""
        default_name = (
            f"zavuch2_ejd_session_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        zip_path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт ЭЖД-сессии", default_name,
            "ZIP archives (*.zip)"
        )
        if not zip_path:
            return

        self._export_to_zip(zip_path, True, False, "ЭЖД")

    def export_pdou_session(self):
        """Экспорт только ПДОУ."""
        default_name = (
            f"zavuch2_pdou_session_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        zip_path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт ПДОУ-сессии", default_name,
            "ZIP archives (*.zip)"
        )
        if not zip_path:
            return

        self._export_to_zip(zip_path, False, True, "ПДОУ")

    # ------------------------------------------------------------------
    def import_sessions(self):
        """Импорт сессий из .zip."""
        zip_path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать архив с сессиями", str(Path.home()),
            "ZIP archives (*.zip);;Все файлы (*.*)"
        )
        if not zip_path:
            return

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка",
                f"Не удалось открыть архив:\n{e}"
            )
            return

        has_ejd = any(n in EJD_FILES for n in names)
        has_pdou = any(n in PDOU_FILES for n in names)

        if not has_ejd and not has_pdou:
            QMessageBox.warning(
                self, "Нет данных",
                "В архиве не найдено файлов сессий zavuch 2."
            )
            return

        # Спросим, что восстанавливать
        dlg = SessionImportDialog(self, has_ejd, has_pdou)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        inc_ejd, inc_pdou = dlg.get_selection()
        if not inc_ejd and not inc_pdou:
            QMessageBox.warning(self, "Ошибка", "Ничего не выбрано.")
            return

        # Подтверждение перезаписи
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Существующие файлы будут перезаписаны.\nПродолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Собираем список файлов для восстановления
        to_restore = []
        if inc_ejd:
            to_restore.extend(EJD_FILES)
        if inc_pdou:
            to_restore.extend(PDOU_FILES)

        restored = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for fname in to_restore:
                    if fname in zf.namelist():
                        target = DATA_DIR / fname
                        with zf.open(fname) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        restored.append(fname)
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка импорта",
                f"Не удалось извлечь файлы:\n{e}"
            )
            return

        self.refresh_session_status()

        QMessageBox.information(
            self, "Импорт завершён",
            f"✅ Восстановлено файлов: {len(restored)}\n\n"
            + "\n".join(f"• {f}" for f in restored)
            + "\n\n"
            "Рекомендуется перезапустить приложение для применения сессий."
        )

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