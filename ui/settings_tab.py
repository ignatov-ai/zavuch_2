# -*- coding: utf-8 -*-
"""
Вкладка «⚙️ Настройки».
• Статус авторизации
• Учебный год
• Экспорт / импорт сессий (ЭЖД и ПДОУ)
"""
import json
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QFileDialog, QMessageBox, QComboBox, QDialog,
    QDialogButtonBox, QCheckBox, QTextEdit,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor

# ==== ПАПКА ====
from paths import (
    SESSIONS_DIR,
    EJD_FILES,
    PDOU_FILES,
)
DATA_DIR = SESSIONS_DIR


# ============================================================
# Диалоги экспорта / импорта
# ============================================================
class SessionExportDialog(QDialog):
    """Диалог экспорта. Показывает чекбоксы, что включать."""

    def __init__(self, parent=None, default_ejd=True, default_pdou=True):
        super().__init__(parent)
        self.setWindowTitle("Экспорт сессий")
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { color: #1e293b; }
            QCheckBox {
                color: #334155;
                spacing: 7px;
                font-size: 10.5pt;
                padding: 4px 0;
            }
            QCheckBox::indicator { width: 17px; height: 17px; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("📦  Экспорт сессий в ZIP-архив")
        title.setStyleSheet(
            "font-size: 13pt; font-weight: 700; color: #0f172a;"
        )
        layout.addWidget(title)

        info = QLabel(
            "Выберите, какие сессии включить в архив.\n"
            "Архив можно перенести на другой компьютер и импортировать."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #64748b;")
        layout.addWidget(info)

        warning = QLabel(
            "⚠️  Файлы содержат пароли и токены — храните архив "
            "в защищённом месте!"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("""
            color: #b45309; background-color: #fffbeb;
            border: 1px solid #fde68a;
            padding: 10px; border-radius: 6px;
            font-weight: 600;
        """)
        layout.addWidget(warning)

        self.ejd_cb = QCheckBox("🔐  ЭЖД-сессия "
                                "(session.pkl, auth_data.json, credentials.json)")
        self.ejd_cb.setChecked(default_ejd)
        layout.addWidget(self.ejd_cb)

        self.pdou_cb = QCheckBox("🎨  ПДОУ-сессия "
                                 "(pdou_token.json, pdou_cookies.json)")
        self.pdou_cb.setChecked(default_pdou)
        layout.addWidget(self.pdou_cb)

        layout.addSpacing(8)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet("""
            QPushButton {
                min-height: 32px;
                padding: 4px 16px;
                border-radius: 6px;
                font-weight: 600;
            }
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selection(self):
        return self.ejd_cb.isChecked(), self.pdou_cb.isChecked()


class SessionImportDialog(QDialog):
    """Диалог импорта. Показывает, что есть в архиве, и что восстанавливать."""

    def __init__(self, parent=None, has_ejd=True, has_pdou=True):
        super().__init__(parent)
        self.setWindowTitle("Импорт сессий")
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { color: #1e293b; }
            QCheckBox {
                color: #334155;
                spacing: 7px;
                font-size: 10.5pt;
                padding: 4px 0;
            }
            QCheckBox::indicator { width: 17px; height: 17px; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("📥  Импорт сессий из ZIP-архива")
        title.setStyleSheet(
            "font-size: 13pt; font-weight: 700; color: #0f172a;"
        )
        layout.addWidget(title)

        info = QLabel(
            "Выберите, что восстановить из архива.\n"
            "Существующие файлы будут перезаписаны."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #64748b;")
        layout.addWidget(info)

        self.ejd_cb = QCheckBox("🔐  Восстановить ЭЖД-сессию")
        self.ejd_cb.setChecked(has_ejd)
        self.ejd_cb.setEnabled(has_ejd)
        if not has_ejd:
            self.ejd_cb.setText("🔐  ЭЖД-сессия (нет в архиве)")
        layout.addWidget(self.ejd_cb)

        self.pdou_cb = QCheckBox("🎨  Восстановить ПДОУ-сессию")
        self.pdou_cb.setChecked(has_pdou)
        self.pdou_cb.setEnabled(has_pdou)
        if not has_pdou:
            self.pdou_cb.setText("🎨  ПДОУ-сессия (нет в архиве)")
        layout.addWidget(self.pdou_cb)

        layout.addSpacing(8)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet("""
            QPushButton {
                min-height: 32px;
                padding: 4px 16px;
                border-radius: 6px;
                font-weight: 600;
            }
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selection(self):
        return self.ejd_cb.isChecked(), self.pdou_cb.isChecked()


# ============================================================
# Единый стиль (нейтральный slate — настройки)
# ============================================================
TAB_STYLE = """
    QWidget {
        font-size: 10pt;
        color: #1e293b;
    }
    QGroupBox {
        font-size: 11pt;
        font-weight: 700;
        color: #475569;
        border: 1px solid #cbd5e1;
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
    QPushButton {
        min-height: 32px;
        padding: 4px 14px;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #f8fafc;
        color: #1e293b;
        font-weight: 500;
    }
    QPushButton:hover { background: #e2e8f0; }
    QPushButton:pressed { background: #cbd5e1; }
    QComboBox {
        min-height: 32px;
        padding: 2px 10px;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #ffffff;
        font-size: 11pt;
    }
    QComboBox:focus { border: 1px solid #475569; }
    QLabel { color: #334155; }
"""


# ============================================================
# Вкладка
# ============================================================
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
    # UI
    # ================================================================
    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(16, 14, 16, 14)

        # === Заголовок ===
        title = QLabel("⚙️  Настройки")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: 700; color: #0f172a; padding: 2px 0 6px 0;"
        )
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Статус авторизации, учебный год, экспорт и импорт сессий."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #64748b; margin-bottom: 4px;")
        main_layout.addWidget(subtitle)

        # === СТАТУС АВТОРИЗАЦИИ ===
        auth_group = QGroupBox("🔐  Статус авторизации")
        auth_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt; font-weight: 700;
                color: #1d4ed8;
                border: 1px solid #93c5fd;
                border-radius: 10px;
                margin-top: 12px;
                padding: 18px 14px 14px 14px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
            }
        """)
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setSpacing(12)

        self.auth_status_label = QLabel("⏳ Ожидание авторизации")
        self.auth_status_label.setStyleSheet("""
            color: #475569; background: #f1f5f9;
            border-radius: 6px; padding: 10px 12px;
            font-weight: 600; font-size: 11pt;
        """)
        auth_layout.addWidget(self.auth_status_label)

        info_label = QLabel(
            "ℹ️  Авторизация выполняется в отдельном окне при запуске. "
            "Смена пользователя — через кнопку ниже."
        )
        info_label.setStyleSheet("""
            color: #64748b; font-size: 9pt;
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 10px; border-radius: 6px;
        """)
        info_label.setWordWrap(True)
        auth_layout.addWidget(info_label)

        self.relogin_btn = QPushButton("🔄  Сменить пользователя")
        self.relogin_btn.setMinimumHeight(38)
        self.relogin_btn.setStyleSheet("""
            QPushButton {
                background: #eff6ff; color: #1d4ed8;
                border: 1px solid #bfdbfe; font-weight: 600;
            }
            QPushButton:hover { background: #dbeafe; }
        """)
        self.relogin_btn.clicked.connect(self.relogin)
        auth_layout.addWidget(self.relogin_btn)

        main_layout.addWidget(auth_group)

        # === ЭКСПОРТ / ИМПОРТ СЕССИЙ ===
        export_group = QGroupBox("💾  Экспорт / Импорт сессий")
        export_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt; font-weight: 700;
                color: #7c3aed;
                border: 1px solid #c4b5fd;
                border-radius: 10px;
                margin-top: 12px;
                padding: 18px 14px 14px 14px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
            }
        """)
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(12)

        hint = QLabel(
            "📋  Перенос сессий на другой компьютер:\n"
            "   1. Экспортируйте в .zip на этом компьютере.\n"
            "   2. Скопируйте .zip на другой компьютер.\n"
            "   3. Импортируйте там через кнопку ниже."
        )
        hint.setStyleSheet("""
            color: #475569; background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 10px; border-radius: 6px;
            font-size: 9.5pt;
        """)
        hint.setWordWrap(True)
        export_layout.addWidget(hint)

        warning = QLabel(
            "⚠️  Архив содержит пароли и токены — храните его в защищённом месте."
        )
        warning.setStyleSheet("""
            color: #b45309; background-color: #fffbeb;
            border: 1px solid #fde68a;
            padding: 8px 10px; border-radius: 6px;
            font-weight: 600; font-size: 9.5pt;
        """)
        warning.setWordWrap(True)
        export_layout.addWidget(warning)

        # --- Кнопки экспорта ---
        exp_row = QHBoxLayout()
        exp_row.setSpacing(8)

        self.export_all_btn = QPushButton("📦  Экспорт всех сессий")
        self.export_all_btn.setMinimumHeight(36)
        self.export_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed; color: #ffffff;
                font-weight: 700; border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #6d28d9; }
        """)
        self.export_all_btn.clicked.connect(self.export_all_sessions)
        exp_row.addWidget(self.export_all_btn)

        self.export_ejd_btn = QPushButton("🔐  Только ЭЖД")
        self.export_ejd_btn.setMinimumHeight(36)
        self.export_ejd_btn.setStyleSheet("""
            QPushButton {
                background-color: #1d4ed8; color: #ffffff;
                font-weight: 600; border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #1e40af; }
        """)
        self.export_ejd_btn.clicked.connect(self.export_ejd_session)
        exp_row.addWidget(self.export_ejd_btn)

        self.export_pdou_btn = QPushButton("🎨  Только ПДОУ")
        self.export_pdou_btn.setMinimumHeight(36)
        self.export_pdou_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9; color: #ffffff;
                font-weight: 600; border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #0284c7; }
        """)
        self.export_pdou_btn.clicked.connect(self.export_pdou_session)
        exp_row.addWidget(self.export_pdou_btn)
        export_layout.addLayout(exp_row)

        # --- Импорт ---
        self.import_btn = QPushButton("📥  Импорт из архива (.zip)")
        self.import_btn.setMinimumHeight(38)
        self.import_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: #ffffff;
                font-weight: 700; border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        self.import_btn.clicked.connect(self.import_sessions)
        export_layout.addWidget(self.import_btn)

        # --- Статус файлов ---
        status_label = QLabel("<b>Текущее состояние файлов:</b>")
        status_label.setStyleSheet("color: #334155; font-size: 10pt;")
        export_layout.addWidget(status_label)

        self.session_status_text = QTextEdit()
        self.session_status_text.setReadOnly(True)
        self.session_status_text.setMaximumHeight(140)
        self.session_status_text.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, "Courier New", monospace;
                font-size: 9.5pt;
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        export_layout.addWidget(self.session_status_text)

        self.refresh_status_btn = QPushButton("🔄  Обновить состояние")
        self.refresh_status_btn.setMaximumWidth(220)
        self.refresh_status_btn.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #475569;
                border: 1px solid #cbd5e1; font-weight: 600;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.refresh_status_btn.clicked.connect(self.refresh_session_status)
        export_layout.addWidget(self.refresh_status_btn)

        main_layout.addWidget(export_group)

        # === УЧЕБНЫЙ ГОД ===
        year_group = QGroupBox("📅  Учебный год")
        year_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt; font-weight: 700;
                color: #059669;
                border: 1px solid #6ee7b7;
                border-radius: 10px;
                margin-top: 12px;
                padding: 18px 14px 14px 14px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
            }
        """)
        year_layout = QVBoxLayout(year_group)
        year_row = QHBoxLayout()
        year_row.setSpacing(12)
        year_row.addWidget(QLabel("Выберите учебный год:"))

        self.year_combo = QComboBox()
        self.year_combo.setMinimumWidth(220)
        self.year_combo.setStyleSheet("""
            QComboBox {
                padding: 8px 12px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 11pt;
                background: #ffffff;
            }
            QComboBox:focus { border: 1px solid #059669; }
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
        self.year_id_label.setStyleSheet("""
            color: #065f46; background: #ecfdf5;
            border: 1px solid #a7f3d0;
            border-radius: 6px; padding: 6px 10px;
            font-weight: 600; font-size: 9.5pt;
        """)
        year_layout.addWidget(self.year_id_label)
        main_layout.addWidget(year_group)

        main_layout.addStretch()
        self.update_year_display()
        self.setStyleSheet(TAB_STYLE)

    # ================================================================
    # АВТОРИЗАЦИЯ
    # ================================================================
    def set_auth(self, auth):
        self.auth = auth
        if auth:
            self.auth_status_label.setText("✅  Авторизован")
            self.auth_status_label.setStyleSheet("""
                color: #065f46; background: #ecfdf5;
                border: 1px solid #a7f3d0;
                border-radius: 6px; padding: 10px 12px;
                font-weight: 700; font-size: 11pt;
            """)
        else:
            self.auth_status_label.setText("❌  Не авторизован")
            self.auth_status_label.setStyleSheet("""
                color: #991b1b; background: #fef2f2;
                border: 1px solid #fecaca;
                border-radius: 6px; padding: 10px 12px;
                font-weight: 700; font-size: 11pt;
            """)

    def relogin(self):
        reply = QMessageBox.question(
            self, "Смена пользователя",
            "Сбросить текущую ЭЖД-сессию и войти заново?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
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
    # ЭКСПОРТ / ИМПОРТ СЕССИЙ
    # ================================================================
    def refresh_session_status(self):
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

    def _get_files_to_export(self, include_ejd: bool, include_pdou: bool):
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

    def import_sessions(self):
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
        dlg = SessionImportDialog(self, has_ejd, has_pdou)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inc_ejd, inc_pdou = dlg.get_selection()
        if not inc_ejd and not inc_pdou:
            QMessageBox.warning(self, "Ошибка", "Ничего не выбрано.")
            return
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Существующие файлы будут перезаписаны.\nПродолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
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
    # УЧЕБНЫЙ ГОД
    # ================================================================
    def update_year_display(self):
        aid = self.year_combo.currentData()
        year_text = self.year_combo.currentText()
        self.year_id_label.setText(f"ID учебного года (aid): {aid}  |  {year_text}")

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