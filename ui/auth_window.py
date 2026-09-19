# -*- coding: utf-8 -*-
"""
Окно авторизации. Открывается при старте приложения.
После успешного входа создаёт MainWindow.
"""
import sys
import json
import pickle
from pathlib import Path

import requests
from urllib.parse import urljoin

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QPlainTextEdit,
    QMessageBox, QFrame, QStackedWidget
)


DATA_DIR = Path.home() / ".ejd_checker"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"


# ============================================================
#  Утилиты
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
    for f in (SESSION_FILE, DATA_DIR / "auth_data.json"):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass


# ============================================================
#  Проверка сессии
# ============================================================
def check_saved_session() -> dict:
    """Проверяет сохранённую сессию через API dnevnik.mos.ru."""
    result = {"ok": False, "reason": "", "school": None, "profile_id": None}

    if not SESSION_FILE.exists():
        result["reason"] = "session.pkl не найден"
        return result

    try:
        with open(SESSION_FILE, "rb") as f:
            cookies = pickle.load(f)

        session = requests.Session()
        session.cookies.update(cookies)
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)

        auth_token = cookies_dict.get("auth_token")
        profile_id = cookies_dict.get("profile_id")

        if not auth_token or not profile_id:
            result["reason"] = "в session.pkl нет auth_token или profile_id"
            return result

        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/152.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Auth-Token": auth_token,
            "Profile-Id": profile_id,
        })

        resp = session.get(
            "https://dnevnik.mos.ru/core/api/schools",
            timeout=15,
        )

        if resp.status_code != 200:
            result["reason"] = f"API вернул {resp.status_code}"
            return result

        data = resp.json()
        if not data:
            result["reason"] = "пустой ответ API"
            return result

        result["ok"] = True
        result["school"] = data[0].get("name")
        result["profile_id"] = profile_id
        result["reason"] = "сессия живая"
        return result

    except Exception as e:
        result["reason"] = f"ошибка проверки: {e}"
        return result


# ============================================================
#  Поток проверки сессии
# ============================================================
class SessionCheckWorker(QThread):
    done = Signal(dict)

    def run(self):
        self.done.emit(check_saved_session())


# ============================================================
#  Поток авторизации (Selenium)
# ============================================================
class AuthWorker(QThread):
    log = Signal(str)
    finished_ok = Signal(object)
    finished_err = Signal(str)

    def __init__(self, username: str, password: str,
                 totp_key: str = None, browser: str = "chrome"):
        super().__init__()
        self.username = username
        self.password = password
        self.totp_key = totp_key or ""
        self.browser = browser

    def _log(self, msg: str):
        print(msg, flush=True)
        self.log.emit(msg)

    def run(self):
        from auth import dn_Auth

        try:
            self._log("=== Начало авторизации ===")
            self._log(f"[i] Логин: {self.username}")
            self._log(f"[i] 2FA: {'TOTP' if self.totp_key else 'SMS вручную'}")

            auth = dn_Auth()
            success = auth.login_with_selenium_advanced(
                self.username,
                self.password,
                totp_key=self.totp_key,
                browser=self.browser,
                log_callback=self._log,
            )

            if success:
                self._log("[+] Авторизация успешна!")
                self.finished_ok.emit(auth)
            else:
                self.finished_err.emit(
                    "Не удалось авторизоваться.\n"
                    "Проверьте логин, пароль и код 2FA."
                )

        except Exception as e:
            self._log(f"[!] Ошибка: {e}")
            self.finished_err.emit(str(e))


# ============================================================
#  Окно авторизации
# ============================================================
class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Вход")
        self.setMinimumSize(620, 620)

        self.auth = None
        self.check_worker = None
        self.auth_worker = None
        self.main_window = None

        self._build_ui()
        self._load_saved_credentials()
        self._start_session_check()

    # ------------------------------------------------------------------
    def _build_ui(self):
        # StackedWidget: экран 1 — «Проверяю сессию», экран 2 — форма входа
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_checking_screen())
        self.stack.addWidget(self._build_login_screen())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.setLayout(layout)

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    def _build_login_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("Вход в ЭЖД МЭШ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin: 8px;")

        hint = QLabel(
            "Введите логин и пароль от mos.ru.\n"
            "Если включена двухфакторная аутентификация —\n"
            "укажите TOTP-ключ или введите SMS-код в браузере."
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; padding: 4px;")

        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Логин (телефон, email или СНИЛС)")
        self.login_edit.setMinimumHeight(34)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(34)

        self.totp_edit = QLineEdit()
        self.totp_edit.setPlaceholderText("TOTP-ключ (Base32; можно пусто — SMS вручную)")
        self.totp_edit.setMinimumHeight(34)

        self.show_password_cb = QCheckBox("Показывать пароль")
        self.show_password_cb.stateChanged.connect(self._toggle_password_echo)

        self.remember_cb = QCheckBox("Запомнить логин и пароль")
        self.remember_cb.setChecked(True)

        cb_row = QHBoxLayout()
        cb_row.addWidget(self.show_password_cb)
        cb_row.addWidget(self.remember_cb)
        cb_row.addStretch()

        self.login_btn = QPushButton("🔐 Войти")
        self.login_btn.setMinimumHeight(40)
        self.login_btn.clicked.connect(self.on_login)

        self.clear_btn = QPushButton("Очистить сохранённые данные")
        self.clear_btn.setMinimumHeight(28)
        self.clear_btn.clicked.connect(self.on_clear)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)

        log_label = QLabel("Журнал:")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
            "background-color: #1e1e1e; color: #d4d4d4;"
        )

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.login_edit)
        layout.addWidget(self.password_edit)
        layout.addWidget(self.totp_edit)
        layout.addLayout(cb_row)
        layout.addWidget(self.login_btn)
        layout.addWidget(self.clear_btn)
        layout.addWidget(line)
        layout.addWidget(log_label)
        layout.addWidget(self.log_view, stretch=1)
        return w

    # ------------------------------------------------------------------
    def _toggle_password_echo(self, state):
        if state == Qt.CheckState.Checked.value:
            self.password_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)

    # ------------------------------------------------------------------
    def _load_saved_credentials(self):
        creds = load_credentials()
        if not creds:
            return
        self.login_edit.setText(creds.get("login", ""))
        self.password_edit.setText(creds.get("password", ""))
        self.totp_edit.setText(creds.get("totp_key", ""))

    # ------------------------------------------------------------------
    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    def _start_session_check(self):
        self.checking_label.setText("Проверяю сохранённую сессию...")
        self.checking_label.setStyleSheet("color: #666; padding: 8px;")

        self.check_worker = SessionCheckWorker()
        self.check_worker.done.connect(self._on_session_checked)
        self.check_worker.start()

    # ------------------------------------------------------------------
    def _on_session_checked(self, result: dict):
        if result.get("ok"):
            # --- сессия живая → сразу открываем главное окно ---
            self.checking_label.setText(
                f"✅ Найдена живая сессия: {result.get('school')}\n"
                "Открываю главное окно..."
            )
            self.checking_label.setStyleSheet(
                "color: green; font-weight: bold; padding: 8px;"
            )

            # Загружаем auth из session.pkl
            from auth import dn_Auth
            auth = dn_Auth()
            if auth.load_session():
                self.auth = auth
                # Небольшая задержка, чтобы пользователь увидел сообщение
                from PySide6.QtCore import QTimer
                QTimer.singleShot(800, self._open_main_window)
            else:
                self._show_login_form("Сессия устарела. Войдите заново.")
        else:
            reason = result.get("reason", "неизвестная причина")
            self._show_login_form(f"Сессия не найдена ({reason})")

    # ------------------------------------------------------------------
    def _show_login_form(self, message: str = ""):
        self.checking_label.setText(
            f"{message}\nПереход к форме входа..."
        )
        self.checking_label.setStyleSheet("color: #666; padding: 8px;")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(600, lambda: self.stack.setCurrentIndex(1))

    # ------------------------------------------------------------------
    def _open_main_window(self):
        """Открывает главное окно с вкладками."""
        from ui.main_window import MainWindow

        self.main_window = MainWindow()
        # Передаём авторизацию в главное окно
        if self.auth:
            self.main_window.on_global_auth(self.auth)
        self.main_window.show()
        self.close()

    # ------------------------------------------------------------------
    def on_clear(self):
        answer = QMessageBox.question(
            self, "Подтверждение",
            "Удалить сохранённые логин, пароль и TOTP-ключ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            clear_credentials()
            clear_session()
            self.login_edit.clear()
            self.password_edit.clear()
            self.totp_edit.clear()
            self.append_log("[i] Сохранённые данные удалены")

    # ------------------------------------------------------------------
    def on_login(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        totp_key = self.totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль.")
            return

        if self.remember_cb.isChecked():
            save_credentials(login, password, totp_key or "")

        self._set_ui_enabled(False)
        self.log_view.clear()
        self.append_log("⏳ Выполняется вход...")

        self.auth_worker = AuthWorker(login, password, totp_key, "chrome")
        self.auth_worker.log.connect(self.append_log)
        self.auth_worker.finished_ok.connect(self.on_login_ok)
        self.auth_worker.finished_err.connect(self.on_login_err)
        self.auth_worker.start()

    # ------------------------------------------------------------------
    def on_login_ok(self, auth):
        self.auth = auth
        self.append_log("[+] Вход выполнен. Открываю главное окно...")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._open_main_window)

    # ------------------------------------------------------------------
    def on_login_err(self, err: str):
        self._set_ui_enabled(True)
        self.append_log(f"[!] {err}")
        QMessageBox.critical(self, "Ошибка входа", err)

    # ------------------------------------------------------------------
    def _set_ui_enabled(self, enabled: bool):
        self.login_btn.setEnabled(enabled)
        self.login_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.totp_edit.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)