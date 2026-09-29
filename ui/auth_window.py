# -*- coding: utf-8 -*-
"""
Окно авторизации. Открывается при старте приложения.

Две независимые колонки:
  • Слева — ЭЖД (журналы): session.pkl + Selenium.
  • Справа — ПДОУ (кружки): pdou_token.json (может быть от другого пользователя).
"""
import sys
import json
import pickle
import shutil
import threading
import time
from pathlib import Path

import requests
from urllib.parse import urljoin

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QPlainTextEdit, QMessageBox, QFrame,
    QStackedWidget, QFileDialog, QGroupBox
)


# ============================================================
#  Пути
# ============================================================
DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"
AUTH_DATA_FILE = DATA_DIR / "auth_data.json"
PDOU_TOKEN_FILE = DATA_DIR / "pdou_token.json"


# ============================================================
#  Утилиты для ЭЖД
# ============================================================
def load_credentials() -> dict:
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_credentials(login: str, password: str, totp_key: str = "") -> bool:
    try:
        data = {"login": login, "password": password, "totp_key": totp_key or ""}
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_credentials():
    try:
        if CREDENTIALS_FILE.exists():
            CREDENTIALS_FILE.unlink()
    except Exception:
        pass


def clear_session():
    for f in (SESSION_FILE, AUTH_DATA_FILE):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass


# ============================================================
#  Утилиты для ПДОУ-токена
# ============================================================
def load_pdou_token() -> dict:
    if not PDOU_TOKEN_FILE.exists():
        return {}
    try:
        with open(PDOU_TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_pdou_token(token: str, user_name: str = "",
                    user_roles=None) -> bool:
    try:
        data = {
            "aupd_token": token.strip(),
            "user_name": user_name.strip(),
            "user_roles": list(user_roles or []),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(PDOU_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_pdou_token():
    try:
        if PDOU_TOKEN_FILE.exists():
            PDOU_TOKEN_FILE.unlink()
    except Exception:
        pass


# ============================================================
#  Проверка сохранённой ЭЖД-сессии
# ============================================================
def check_saved_session() -> dict:
    result = {"ok": False, "reason": "", "school": None,
              "profile_id": None, "auth_obj": None}
    if not SESSION_FILE.exists():
        result["reason"] = "session.pkl не найден"
        return result
    try:
        from auth import dn_Auth
        auth = dn_Auth()
        if auth.load_session():
            result["ok"] = True
            result["school"] = f"school_id={auth.sid}"
            result["profile_id"] = auth.pid
            result["auth_obj"] = auth
            result["reason"] = "сессия живая"
            return result
        result["reason"] = "cookies не приняты API"
        return result
    except Exception as e:
        result["reason"] = f"ошибка: {e}"
        return result


# ============================================================
#  Потоки
# ============================================================
class SessionCheckWorker(QThread):
    done = Signal(dict)
    def run(self):
        self.done.emit(check_saved_session())


class LoadCookiesWorker(QThread):
    done = Signal(dict)
    def run(self):
        self.done.emit(check_saved_session())


class ImportedSessionCheckWorker(QThread):
    done = Signal(dict)
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
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(SESSION_FILE))
            except Exception as e:
                result["reason"] = f"Не удалось скопировать: {e}"
                self.done.emit(result)
                return
            if self.copy_adjacent_auth_data:
                adjacent = src.parent / "auth_data.json"
                if adjacent.exists():
                    try:
                        shutil.copy2(str(adjacent), str(AUTH_DATA_FILE))
                    except Exception:
                        pass
            from auth import dn_Auth
            auth = dn_Auth()
            if auth.load_session():
                result["ok"] = True
                result["auth_obj"] = auth
                result["reason"] = f"Сессия из {src.name} рабочая"
            else:
                result["reason"] = (
                    "Файл скопирован, но API не принял сессию."
                )
        except Exception as e:
            result["reason"] = f"Ошибка: {e}"
        self.done.emit(result)


class AuthWorker(QThread):
    log = Signal(str)
    finished_ok = Signal(object)
    finished_err = Signal(str)
    cookies_ready = Signal()

    def __init__(self, username: str, password: str,
                 totp_key: str = None, browser: str = "chrome",
                 pdou_mode: bool = False):
        super().__init__()
        self.username = username
        self.password = password
        self.totp_key = totp_key or ""
        self.browser = browser
        self.pdou_mode = pdou_mode
        self._close_browser_event = threading.Event()
        self._detach_browser_event = threading.Event()
        self._current_driver = None

    def _log(self, msg: str):
        print(msg, flush=True)
        self.log.emit(msg)

    def _gui_confirm(self, driver, auth_obj):
        self._current_driver = driver
        self.cookies_ready.emit()
        end = time.time() + 600
        while time.time() < end:
            if self._close_browser_event.is_set():
                try:
                    driver.quit()
                except Exception:
                    pass
                return
            if self._detach_browser_event.is_set():
                return
            time.sleep(0.2)
        try:
            driver.quit()
        except Exception:
            pass

    def run(self):
        from auth import dn_Auth
        try:
            self._log("=== Начало авторизации ===")
            self._log(f"[i] Логин: {self.username}")
            self._log(f"[i] 2FA: {'TOTP' if self.totp_key else 'SMS вручную'}")
            self._log(f"[i] Режим: {'ПДОУ' if self.pdou_mode else 'ЭЖД'}")

            auth = dn_Auth()
            success = auth.login_with_selenium_advanced(
                self.username,
                self.password,
                totp_key=self.totp_key,
                browser=self.browser,
                log_callback=self._log,
                gui_confirm_callback=self._gui_confirm,
                pdou_mode=self.pdou_mode,
            )
            if success:
                self._log("[+] Авторизация успешна!")
                self.finished_ok.emit(auth)
            else:
                self._log("[!] Не удалось авторизоваться")
                if self._current_driver is not None:
                    self._close_browser_event.set()
                self.finished_err.emit("Не удалось авторизоваться.")
        except Exception as e:
            self._log(f"[!] Ошибка: {e}")
            if self._current_driver is not None:
                self._close_browser_event.set()
            self.finished_err.emit(str(e))


# ============================================================
#  Поток проверки ПДОУ-токена  —  4 значения!
# ============================================================
class PDOUTokenCheckThread(QThread):
    finished = Signal(bool, str, list, str)   # (ok, user_name, roles, reason)
    log = Signal(str)

    def __init__(self, token):
        super().__init__()
        self.token = token

    def run(self):
        try:
            from collector_pdou import PDOUCollector
            collector = PDOUCollector(self.token)
            collector.log_callback = lambda t: self.log.emit(t)
            ok, user_name, roles, reason = collector.check_token()   # ← 4 значения
            self.finished.emit(ok, user_name, roles, reason)
        except Exception as e:
            self.finished.emit(False, "", [], f"Исключение: {e}")


# ============================================================
#  Окно авторизации
# ============================================================
class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Вход")
        self.setMinimumSize(1200, 900)

        self.auth = None
        self.check_worker = None
        self.load_cookies_worker = None
        self.import_worker = None
        self.auth_worker = None
        self.pdou_check_worker = None
        self.main_window = None

        self.pdou_user_name = ""
        self.pdou_roles = []

        self._build_ui()
        self._load_saved_credentials()
        self._load_saved_pdou_token()
        self._start_session_check()
        self._start_pdou_auto_check()

    # ==================================================================
    #  UI
    # ==================================================================
    def _build_ui(self):
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_checking_screen())
        self.stack.addWidget(self._build_login_screen())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.setLayout(layout)

    def _build_checking_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("ЭЖД МЭШ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; margin: 20px;")
        self.checking_label = QLabel("Проверяю сохранённую сессию...")
        self.checking_label.setAlignment(Qt.AlignCenter)
        self.checking_label.setWordWrap(True)
        self.checking_label.setStyleSheet("color: #666; padding: 8px;")
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(self.checking_label)
        layout.addStretch()
        return w

    def _build_login_screen(self) -> QWidget:
        w = QWidget()
        main_layout = QVBoxLayout(w)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(10)

        title = QLabel("Вход в систему")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin: 4px;")
        main_layout.addWidget(title)

        columns = QHBoxLayout()
        columns.setSpacing(15)
        columns.addWidget(self._build_ejd_column(), 1)
        columns.addWidget(self._build_pdou_column(), 1)
        main_layout.addLayout(columns, 1)

        # Служебные кнопки
        service_row = QHBoxLayout()
        service_row.setSpacing(8)
        service_row.addStretch()

        self.monitor_btn = QPushButton("👁 Монитор сессии")
        self.monitor_btn.setMinimumHeight(30)
        self.monitor_btn.setMaximumWidth(180)
        self.monitor_btn.clicked.connect(self.on_start_monitor)
        service_row.addWidget(self.monitor_btn)

        self.import_tokens_btn = QPushButton("📋 Импорт токенов (ЭЖД)")
        self.import_tokens_btn.setMinimumHeight(30)
        self.import_tokens_btn.setMaximumWidth(200)
        self.import_tokens_btn.clicked.connect(self.on_open_token_dialog)
        service_row.addWidget(self.import_tokens_btn)

        self.clear_all_btn = QPushButton("🗑 Очистить все данные")
        self.clear_all_btn.setMinimumHeight(30)
        self.clear_all_btn.setMaximumWidth(200)
        self.clear_all_btn.clicked.connect(self.on_clear_all)
        service_row.addWidget(self.clear_all_btn)

        service_row.addStretch()
        main_layout.addLayout(service_row)

        # Журнал
        log_group = QGroupBox("📋 Журнал")
        log_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 11pt;
                border: 1px solid #cccccc; border-radius: 8px;
                margin-top: 6px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px;
                padding: 0 6px 0 6px; }
        """)
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 12, 8, 8)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 10px;"
            "background-color: #1e1e1e; color: #d4d4d4;"
        )
        self.log_view.setMinimumHeight(140)
        log_layout.addWidget(self.log_view)

        main_layout.addWidget(log_group)

        return w

    def _build_ejd_column(self) -> QWidget:
        group = QGroupBox("🔐 ЭЖД — журналы и итоги")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 12pt;
                border: 2px solid #2563eb; border-radius: 10px;
                margin-top: 1ex; padding-top: 15px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px;
                padding: 0 8px 0 8px; color: #2563eb;
            }
        """)
        col = QVBoxLayout(group)
        col.setSpacing(8)
        col.setContentsMargins(12, 18, 12, 12)

        self.ejd_status_label = QLabel("⏳ Проверяю сохранённую сессию...")
        self.ejd_status_label.setWordWrap(True)
        self.ejd_status_label.setStyleSheet(
            "color: #666; font-weight: bold; padding: 4px;"
        )
        col.addWidget(self.ejd_status_label)

        self.load_cookies_btn = QPushButton("📂 Использовать session.pkl")
        self.load_cookies_btn.setMinimumHeight(34)
        self.load_cookies_btn.setStyleSheet("""
            QPushButton { background-color: #059669; color: white;
                font-size: 10pt; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.load_cookies_btn.clicked.connect(self.on_login_with_cookies)
        col.addWidget(self.load_cookies_btn)

        import_row = QHBoxLayout()
        import_row.setSpacing(4)
        self.session_path_edit = QLineEdit()
        self.session_path_edit.setPlaceholderText("Путь к session.pkl")
        self.session_path_edit.setMinimumHeight(30)
        self.session_path_edit.textChanged.connect(self._update_use_file_btn)
        import_row.addWidget(self.session_path_edit, 1)

        self.browse_session_btn = QPushButton("…")
        self.browse_session_btn.setMaximumWidth(34)
        self.browse_session_btn.setMinimumHeight(30)
        self.browse_session_btn.clicked.connect(self.on_browse_session_file)
        import_row.addWidget(self.browse_session_btn)
        col.addLayout(import_row)

        self.use_session_file_btn = QPushButton("✅ Использовать выбранный файл")
        self.use_session_file_btn.setMinimumHeight(32)
        self.use_session_file_btn.setEnabled(False)
        self.use_session_file_btn.setStyleSheet("""
            QPushButton { background-color: #6b7280; color: white;
                font-size: 10pt; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #4b5563; }
            QPushButton:disabled { background-color: #cccccc; color: #888; }
        """)
        self.use_session_file_btn.clicked.connect(self.on_use_selected_file)
        col.addWidget(self.use_session_file_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #dddddd;")
        col.addWidget(sep)

        col.addWidget(QLabel("Логин:"))
        self.ejd_login_edit = QLineEdit()
        self.ejd_login_edit.setPlaceholderText("Телефон / email / СНИЛС")
        self.ejd_login_edit.setMinimumHeight(30)
        col.addWidget(self.ejd_login_edit)

        col.addWidget(QLabel("Пароль:"))
        self.ejd_password_edit = QLineEdit()
        self.ejd_password_edit.setPlaceholderText("Пароль")
        self.ejd_password_edit.setEchoMode(QLineEdit.Password)
        self.ejd_password_edit.setMinimumHeight(30)
        col.addWidget(self.ejd_password_edit)

        col.addWidget(QLabel("TOTP (если есть):"))
        self.ejd_totp_edit = QLineEdit()
        self.ejd_totp_edit.setPlaceholderText("Base32, можно пусто")
        self.ejd_totp_edit.setMinimumHeight(30)
        col.addWidget(self.ejd_totp_edit)

        self.ejd_show_pass_cb = QCheckBox("Показывать пароль")
        self.ejd_show_pass_cb.stateChanged.connect(
            lambda s: self._toggle_echo(self.ejd_password_edit, s)
        )
        self.ejd_remember_cb = QCheckBox("Запомнить логин/пароль")
        self.ejd_remember_cb.setChecked(True)
        cb_row = QHBoxLayout()
        cb_row.addWidget(self.ejd_show_pass_cb)
        cb_row.addWidget(self.ejd_remember_cb)
        cb_row.addStretch()
        col.addLayout(cb_row)

        self.ejd_login_btn = QPushButton("🌐 Войти в ЭЖД через браузер")
        self.ejd_login_btn.setMinimumHeight(38)
        self.ejd_login_btn.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: white;
                font-size: 11pt; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.ejd_login_btn.clicked.connect(self.on_login_with_browser)
        col.addWidget(self.ejd_login_btn)

        col.addStretch()

        path_hint = QLabel(f"📁 {DATA_DIR / 'session.pkl'}")
        path_hint.setStyleSheet("color: #999; font-size: 8pt;")
        path_hint.setWordWrap(True)
        col.addWidget(path_hint)

        return group

    def _build_pdou_column(self) -> QWidget:
        group = QGroupBox("🎨 ПДОУ — кружки и секции")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 12pt;
                border: 2px solid #8b5cf6; border-radius: 10px;
                margin-top: 1ex; padding-top: 15px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px;
                padding: 0 8px 0 8px; color: #8b5cf6;
            }
        """)
        col = QVBoxLayout(group)
        col.setSpacing(8)
        col.setContentsMargins(12, 18, 12, 12)

        self.pdou_status_label = QLabel("⏳ Токен не задан")
        self.pdou_status_label.setWordWrap(True)
        self.pdou_status_label.setStyleSheet(
            "color: #666; font-weight: bold; padding: 4px;"
        )
        col.addWidget(self.pdou_status_label)

        col.addWidget(QLabel("Токен ПДОУ (aupdToken):"))
        self.pdou_token_edit = QLineEdit()
        self.pdou_token_edit.setPlaceholderText("JWT от school.mos.ru")
        self.pdou_token_edit.setMinimumHeight(30)
        col.addWidget(self.pdou_token_edit)

        token_btn_row = QHBoxLayout()
        token_btn_row.setSpacing(4)

        self.pdou_paste_btn = QPushButton("📋 Из буфера")
        self.pdou_paste_btn.setMinimumHeight(30)
        self.pdou_paste_btn.clicked.connect(self.on_pdou_paste)
        token_btn_row.addWidget(self.pdou_paste_btn)

        self.pdou_check_btn = QPushButton("🔍 Проверить")
        self.pdou_check_btn.setMinimumHeight(30)
        self.pdou_check_btn.clicked.connect(self.on_pdou_check)
        token_btn_row.addWidget(self.pdou_check_btn)

        self.pdou_save_btn = QPushButton("💾 Сохранить")
        self.pdou_save_btn.setMinimumHeight(30)
        self.pdou_save_btn.setStyleSheet("""
            QPushButton { background-color: #059669; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.pdou_save_btn.clicked.connect(self.on_pdou_save)
        token_btn_row.addWidget(self.pdou_save_btn)

        col.addLayout(token_btn_row)

        self.pdou_from_ejd_btn = QPushButton("📥 Взять токен из ЭЖД-сессии")
        self.pdou_from_ejd_btn.setMinimumHeight(30)
        self.pdou_from_ejd_btn.clicked.connect(self.on_pdou_from_ejd)
        col.addWidget(self.pdou_from_ejd_btn)

        self.pdou_clear_btn = QPushButton("🗑 Очистить токен ПДОУ")
        self.pdou_clear_btn.setMinimumHeight(28)
        self.pdou_clear_btn.setStyleSheet("""
            QPushButton { background-color: #dc2626; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.pdou_clear_btn.clicked.connect(self.on_pdou_clear)
        col.addWidget(self.pdou_clear_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #dddddd;")
        col.addWidget(sep)

        col.addWidget(QLabel("Или войти через браузер:"))
        col.addWidget(QLabel("Логин:"))

        self.pdou_login_edit = QLineEdit()
        self.pdou_login_edit.setPlaceholderText("Логин учётки с доступом к ПДОУ")
        self.pdou_login_edit.setMinimumHeight(30)
        col.addWidget(self.pdou_login_edit)

        col.addWidget(QLabel("Пароль:"))
        self.pdou_password_edit = QLineEdit()
        self.pdou_password_edit.setPlaceholderText("Пароль")
        self.pdou_password_edit.setEchoMode(QLineEdit.Password)
        self.pdou_password_edit.setMinimumHeight(30)
        col.addWidget(self.pdou_password_edit)

        col.addWidget(QLabel("TOTP (если есть):"))
        self.pdou_totp_edit = QLineEdit()
        self.pdou_totp_edit.setPlaceholderText("Base32, можно пусто")
        self.pdou_totp_edit.setMinimumHeight(30)
        col.addWidget(self.pdou_totp_edit)

        self.pdou_show_pass_cb = QCheckBox("Показывать пароль")
        self.pdou_show_pass_cb.stateChanged.connect(
            lambda s: self._toggle_echo(self.pdou_password_edit, s)
        )
        col.addWidget(self.pdou_show_pass_cb)

        self.pdou_login_btn = QPushButton("🎨 Войти как ПДОУ через браузер")
        self.pdou_login_btn.setMinimumHeight(38)
        self.pdou_login_btn.setStyleSheet("""
            QPushButton { background-color: #8b5cf6; color: white;
                font-size: 11pt; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #7c3aed; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.pdou_login_btn.clicked.connect(self.on_login_as_pdou)
        col.addWidget(self.pdou_login_btn)

        col.addStretch()

        path_hint = QLabel(f"📁 {PDOU_TOKEN_FILE}")
        path_hint.setStyleSheet("color: #999; font-size: 8pt;")
        path_hint.setWordWrap(True)
        col.addWidget(path_hint)

        return group

    def _toggle_echo(self, line_edit: QLineEdit, state):
        if state == Qt.CheckState.Checked.value:
            line_edit.setEchoMode(QLineEdit.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.Password)

    def _load_saved_credentials(self):
        creds = load_credentials()
        if not creds:
            return
        self.ejd_login_edit.setText(creds.get("login", ""))
        self.ejd_password_edit.setText(creds.get("password", ""))
        self.ejd_totp_edit.setText(creds.get("totp_key", ""))

    def _load_saved_pdou_token(self):
        data = load_pdou_token()
        token = data.get("aupd_token", "")
        user_name = data.get("user_name", "")
        roles = data.get("user_roles", [])
        if token:
            self.pdou_token_edit.setText(token)
            self.pdou_user_name = user_name
            self.pdou_roles = roles
            self._update_pdou_status(True, user_name, roles)

    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ==================================================================
    #  СТАРТОВАЯ ПРОВЕРКА
    # ==================================================================
    def _start_session_check(self):
        self.checking_label.setText("Проверяю сохранённую сессию...")
        self.checking_label.setStyleSheet("color: #666; padding: 8px;")
        self.check_worker = SessionCheckWorker()
        self.check_worker.done.connect(self._on_session_checked)
        self.check_worker.start()

    def _on_session_checked(self, result: dict):
        if result.get("ok"):
            self.checking_label.setText(
                f"✅ Найдена живая сессия ЭЖД ({result.get('reason')})\n"
                "Открываю главное окно..."
            )
            self.checking_label.setStyleSheet(
                "color: green; font-weight: bold; padding: 8px;"
            )
            self.auth = result.get("auth_obj")
            QTimer.singleShot(700, self._open_main_window)
        else:
            reason = result.get("reason", "неизвестная причина")
            self._show_login_form(f"Сессия ЭЖД не найдена ({reason})")

    def _start_pdou_auto_check(self):
        data = load_pdou_token()
        token = data.get("aupd_token", "")
        if token:
            self._run_pdou_check(token, silent=True)

    def _show_login_form(self, message: str = ""):
        self.checking_label.setText(f"{message}\nПереход к форме входа...")
        self.checking_label.setStyleSheet("color: #666; padding: 8px;")
        QTimer.singleShot(500, lambda: self.stack.setCurrentIndex(1))

    def _open_main_window(self):
        from ui.main_window import MainWindow
        self.main_window = MainWindow()
        if self.auth:
            self.main_window.on_global_auth(self.auth)
        self.main_window.show()
        self.close()

    # ==================================================================
    #  ЭЖД — кнопки
    # ==================================================================
    def on_login_with_cookies(self):
        if not SESSION_FILE.exists():
            QMessageBox.warning(self, "Нет данных",
                                f"Файл не найден:\n{SESSION_FILE}")
            return
        self.append_log("[i] Проверяю сохранённые cookies ЭЖД...")
        self._set_ejd_ui_enabled(False)
        self.load_cookies_worker = LoadCookiesWorker()
        self.load_cookies_worker.done.connect(self._on_cookies_loaded)
        self.load_cookies_worker.start()

    def _on_cookies_loaded(self, result: dict):
        self._set_ejd_ui_enabled(True)
        if result.get("ok"):
            self.auth = result.get("auth_obj")
            QTimer.singleShot(300, self._open_main_window)
        else:
            QMessageBox.warning(self, "Cookies не подошли",
                                result.get("reason", ""))

    def on_browse_session_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите session.pkl", str(Path.home()),
            "Pickle session files (*.pkl);;Все файлы (*.*)"
        )
        if file_path:
            self.session_path_edit.setText(file_path)

    def _update_use_file_btn(self, text: str):
        self.use_session_file_btn.setEnabled(bool((text or "").strip()))

    def on_use_selected_file(self):
        file_path = self.session_path_edit.text().strip()
        if not file_path:
            QMessageBox.warning(self, "Ошибка", "Выберите файл.")
            return
        if not Path(file_path).exists():
            QMessageBox.warning(self, "Ошибка", f"Файл не найден:\n{file_path}")
            return
        self._set_ejd_ui_enabled(False)
        self.import_worker = ImportedSessionCheckWorker(file_path)
        self.import_worker.done.connect(self._on_import_finished)
        self.import_worker.start()

    def _on_import_finished(self, result: dict):
        self._set_ejd_ui_enabled(True)
        if result.get("ok"):
            self.auth = result.get("auth_obj")
            QTimer.singleShot(300, self._open_main_window)
        else:
            QMessageBox.warning(self, "Сессия не подошла",
                                result.get("reason", ""))

    def on_login_with_browser(self):
        login = self.ejd_login_edit.text().strip()
        password = self.ejd_password_edit.text()
        totp_key = self.ejd_totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль ЭЖД.")
            return

        if self.ejd_remember_cb.isChecked():
            save_credentials(login, password, totp_key or "")

        self._set_ejd_ui_enabled(False)
        self.append_log("⏳ Запуск браузера для входа (ЭЖД)...")

        self.auth_worker = AuthWorker(login, password, totp_key, "chrome",
                                     pdou_mode=False)
        self.auth_worker.log.connect(self.append_log)
        self.auth_worker.cookies_ready.connect(self.on_cookies_ready)
        self.auth_worker.finished_ok.connect(self.on_ejd_login_ok)
        self.auth_worker.finished_err.connect(self.on_login_err)
        self.auth_worker.start()

    def on_ejd_login_ok(self, auth):
        self.auth = auth
        self.append_log("[+] Вход (ЭЖД) выполнен. Открываю главное окно...")
        QTimer.singleShot(500, self._open_main_window)

    # ==================================================================
    #  ПДОУ — кнопки
    # ==================================================================
    def on_pdou_paste(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text:
            self.pdou_token_edit.setText(text)
            self.append_log(f"[clipboard] ПДОУ: вставлено {len(text)} символов")

    def on_pdou_check(self):
        token = self.pdou_token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "Ошибка", "Введите ПДОУ-токен.")
            return
        self._run_pdou_check(token, silent=False)

    def _run_pdou_check(self, token: str, silent: bool = False):
        self.pdou_check_btn.setEnabled(False)
        self.append_log("[i] Проверяю ПДОУ-токен через /User/CurrentUser...")

        self.pdou_check_worker = PDOUTokenCheckThread(token)
        self.pdou_check_worker.log.connect(self.append_log)

        def _on_done(ok, user_name, roles, reason):
            self.pdou_check_btn.setEnabled(True)
            if ok:
                self.pdou_user_name = user_name
                self.pdou_roles = roles
                self._update_pdou_status(True, user_name, roles)
                if not silent:
                    roles_text = "\n".join(f"• {r}" for r in roles) if roles else "(роли отсутствуют)"
                    has_pdou = any(
                        "оператор" in r.lower() or "пдоу" in r.lower() or "круж" in r.lower()
                        for r in roles
                    )
                    if has_pdou:
                        QMessageBox.information(
                            self, "Токен рабочий",
                            f"✅ Пользователь: {user_name}\n\nРоли ЕСЗ:\n{roles_text}\n\n"
                            "Нажмите «💾 Сохранить»."
                        )
                    else:
                        QMessageBox.warning(
                            self, "Нет прав ПДОУ",
                            f"⚠️ Пользователь: {user_name}\n\nРоли ЕСЗ:\n{roles_text}\n\n"
                            "Прав на кружки не видно."
                        )
            else:
                self._update_pdou_status(False)
                if not silent:
                    QMessageBox.warning(self, "Проверка не удалась", reason)

        self.pdou_check_worker.finished.connect(_on_done)
        self.pdou_check_worker.start()

    def on_pdou_save(self):
        token = self.pdou_token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "Ошибка", "Введите ПДОУ-токен.")
            return
        if save_pdou_token(token, self.pdou_user_name, self.pdou_roles):
            self._update_pdou_status(True, self.pdou_user_name, self.pdou_roles)
            self.append_log(f"[+] ПДОУ-токен сохранён ({self.pdou_user_name or 'без имени'})")
            QMessageBox.information(
                self, "Готово",
                f"✅ Токен сохранён.\n\nФайл: {PDOU_TOKEN_FILE}"
            )
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить токен.")

    def on_pdou_from_ejd(self):
        if not self.auth and SESSION_FILE.exists():
            from auth import dn_Auth
            auth = dn_Auth()
            if auth.load_session():
                self.auth = auth

        if not self.auth or not self.auth.session:
            QMessageBox.warning(
                self, "Ошибка",
                "Нет активной ЭЖД-сессии.\n\n"
                "Сначала войдите в ЭЖД слева, затем повторите."
            )
            return

        self.append_log("[i] Запрашиваю /core/api/profile...")
        try:
            profile = self.auth.fetch("core/api/profile")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить профиль:\n{e}")
            return

        if not isinstance(profile, dict):
            QMessageBox.warning(self, "Ошибка", "Пустой ответ профиля.")
            return

        token = profile.get("authentication_token") or ""
        if not token:
            QMessageBox.warning(
                self, "Не найдено",
                "В ответе /core/api/profile нет authentication_token."
            )
            return

        self.pdou_token_edit.setText(token)
        first = profile.get("first_name", "")
        last = profile.get("last_name", "")
        user_name = f"{last} {first}".strip()
        self.pdou_user_name = user_name
        self.append_log(f"[+] Токен из ЭЖД ({user_name})")
        QMessageBox.information(
            self, "Токен получен",
            f"Токен взят из ЭЖД-сессии.\n\nПользователь: {user_name}\n\n"
            "Нажмите «🔍 Проверить»."
        )

    def on_pdou_clear(self):
        reply = QMessageBox.question(
            self, "Очистить ПДОУ-токен?",
            "Удалить сохранённый токен ПДОУ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        clear_pdou_token()
        self.pdou_token_edit.clear()
        self.pdou_user_name = ""
        self.pdou_roles = []
        self._update_pdou_status(False)
        self.append_log("[i] ПДОУ-токен удалён")

    def on_login_as_pdou(self):
        login = self.pdou_login_edit.text().strip()
        password = self.pdou_password_edit.text()
        totp_key = self.pdou_totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(self, "Ошибка",
                                "Введите логин и пароль учётки с доступом к ПДОУ.")
            return

        answer = QMessageBox.question(
            self, "Вход как ПДОУ",
            "Будет сохранён ТОЛЬКО ПДОУ-токен (pdou_token.json).\n"
            "ЭЖД-сессия не изменится.\n\nПродолжить?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._set_pdou_ui_enabled(False)
        self.append_log("⏳ Запуск браузера (ПДОУ)...")

        self.auth_worker = AuthWorker(login, password, totp_key, "chrome",
                                     pdou_mode=True)
        self.auth_worker.log.connect(self.append_log)
        self.auth_worker.cookies_ready.connect(self.on_cookies_ready)
        self.auth_worker.finished_ok.connect(self.on_pdou_login_ok)
        self.auth_worker.finished_err.connect(self.on_login_err)
        self.auth_worker.start()

    def on_pdou_login_ok(self, auth):
        self._set_pdou_ui_enabled(True)

        data = load_pdou_token()
        user_name = data.get("user_name", "")
        token = data.get("aupd_token", "")
        roles = data.get("user_roles", [])

        if token:
            self.pdou_token_edit.setText(token)
            self.pdou_user_name = user_name
            self.pdou_roles = roles
            self._run_pdou_check(token, silent=True)

        self.append_log(f"[+] ПДОУ-токен сохранён. Пользователь: {user_name}")
        QMessageBox.information(
            self, "ПДОУ-токен сохранён",
            f"✅ Токен для ПДОУ сохранён.\n\n"
            f"Пользователь: {user_name or 'неизвестен'}\n"
            f"Файл: {PDOU_TOKEN_FILE}\n\n"
            "ЭЖД-сессия не изменилась."
        )

    def _update_pdou_status(self, ok, user_name="", roles=None):
        if ok:
            roles = roles or []
            has_pdou = any(
                "оператор" in r.lower() or "пдоу" in r.lower() or "круж" in r.lower()
                for r in roles
            )
            marker = "✅" if has_pdou else "⚠️"
            roles_text = ", ".join(roles) if roles else "роли отсутствуют"
            self.pdou_status_label.setText(
                f"{marker} {user_name or 'неизвестен'}\n"
                f"Роли ЕСЗ: {roles_text}"
            )
            if has_pdou:
                self.pdou_status_label.setStyleSheet(
                    "color: #059669; font-weight: bold; padding: 4px;"
                )
            else:
                self.pdou_status_label.setStyleSheet(
                    "color: #d97706; font-weight: bold; padding: 4px;"
                )
        else:
            self.pdou_status_label.setText("❌ Токен не задан или не работает")
            self.pdou_status_label.setStyleSheet(
                "color: #dc2626; font-weight: bold; padding: 4px;"
            )

    # ==================================================================
    #  Общие кнопки
    # ==================================================================
    def on_cookies_ready(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Куки получены")
        msg.setText("🍪 Куки успешно получены!")
        msg.setInformativeText(
            "• «OK» — оставить окно браузера открытым.\n"
            "• «Закрыть браузер» — закрыть сейчас."
        )
        msg.setIcon(QMessageBox.Icon.Information)
        ok_btn = msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        close_btn = msg.addButton("Закрыть браузер",
                                  QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(ok_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if self.auth_worker is None:
            return
        if clicked == close_btn:
            self.auth_worker._close_browser_event.set()
        else:
            self.auth_worker._detach_browser_event.set()

    def on_login_err(self, err: str):
        self._set_ejd_ui_enabled(True)
        self._set_pdou_ui_enabled(True)
        self.append_log(f"[!] {err}")
        QMessageBox.critical(self, "Ошибка входа", err)

    def on_start_monitor(self):
        import subprocess
        import sys as _sys
        from pathlib import Path as _Path

        project_root = _Path(__file__).resolve().parent.parent
        monitor_script = project_root / "session_monitor.py"

        if not monitor_script.exists():
            QMessageBox.warning(self, "Не найден",
                                f"Файл не найден:\n{monitor_script}")
            return

        answer = QMessageBox.question(
            self, "Монитор сессии",
            "Запустить монитор?\n\nТребуется Chrome с --remote-debugging-port=9222.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            if _sys.platform == "win32":
                subprocess.Popen(
                    ["cmd", "/k", _sys.executable, str(monitor_script)],
                    cwd=str(project_root),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(
                    [_sys.executable, str(monitor_script)],
                    cwd=str(project_root),
                )
            self.append_log("[i] Монитор запущен")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось:\n{e}")

    def on_open_token_dialog(self):
        from ui.token_import_dialog import TokenImportDialog
        dlg = TokenImportDialog(self)
        dlg.tokens_saved.connect(self._on_tokens_saved)
        dlg.exec()

    def _on_tokens_saved(self, auth):
        if auth is None:
            return
        self.append_log("[+] Токены ЭЖД импортированы, открываю окно…")
        self.auth = auth
        QTimer.singleShot(300, self._open_main_window)

    def on_clear_all(self):
        answer = QMessageBox.question(
            self, "Очистить всё?",
            "Удалить:\n"
            "• логин/пароль/TOTP ЭЖД\n"
            "• session.pkl и auth_data.json\n"
            "• pdou_token.json\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        clear_credentials()
        clear_session()
        clear_pdou_token()

        self.ejd_login_edit.clear()
        self.ejd_password_edit.clear()
        self.ejd_totp_edit.clear()
        self.pdou_token_edit.clear()
        self.pdou_user_name = ""
        self.pdou_roles = []

        self._update_pdou_status(False)
        self.ejd_status_label.setText("❌ Данные удалены")
        self.ejd_status_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        self.append_log("[i] Все сохранённые данные удалены")

    # ==================================================================
    #  Блокировка UI
    # ==================================================================
    def _set_ejd_ui_enabled(self, enabled: bool):
        self.ejd_login_btn.setEnabled(enabled)
        self.load_cookies_btn.setEnabled(enabled)
        self.browse_session_btn.setEnabled(enabled)
        if enabled:
            self._update_use_file_btn(self.session_path_edit.text())
        else:
            self.use_session_file_btn.setEnabled(False)
        self.session_path_edit.setEnabled(enabled)
        self.ejd_login_edit.setEnabled(enabled)
        self.ejd_password_edit.setEnabled(enabled)
        self.ejd_totp_edit.setEnabled(enabled)

    def _set_pdou_ui_enabled(self, enabled: bool):
        self.pdou_login_btn.setEnabled(enabled)
        self.pdou_check_btn.setEnabled(enabled)
        self.pdou_save_btn.setEnabled(enabled)
        self.pdou_paste_btn.setEnabled(enabled)
        self.pdou_from_ejd_btn.setEnabled(enabled)
        self.pdou_clear_btn.setEnabled(enabled)
        self.pdou_login_edit.setEnabled(enabled)
        self.pdou_password_edit.setEnabled(enabled)
        self.pdou_totp_edit.setEnabled(enabled)
        self.pdou_token_edit.setEnabled(enabled)