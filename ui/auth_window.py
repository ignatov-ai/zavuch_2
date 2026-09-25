# -*- coding: utf-8 -*-
"""
Окно авторизации. Открывается при старте приложения.
После успешного входа создаёт MainWindow.

Две кнопки входа:
  • «Войти с использованием браузера» — Selenium + 2FA + сохранение сессии.
  • «Войти используя имеющиеся данные» — загрузка session.pkl без браузера.

После Selenium-входа браузер НЕ закрывается автоматически.
Появляется попап «Куки получены» с кнопками «OK» и «Закрыть браузер».
"""
import sys
import json
import pickle
import threading
import time
from pathlib import Path

import requests
from urllib.parse import urljoin

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QPlainTextEdit,
    QMessageBox, QFrame, QStackedWidget
)


DATA_DIR = Path.home() / ".ejd_checker"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"
AUTH_DATA_FILE = DATA_DIR / "auth_data.json"


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
    for f in (SESSION_FILE, AUTH_DATA_FILE):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass


# ============================================================
#  Проверка сохранённой сессии (без побочных эффектов)
# ============================================================
def check_saved_session() -> dict:
    """
    Проверяет сохранённую сессию через API dnevnik.mos.ru.
    Возвращает dict:
        ok: bool
        reason: str
        school: str | None
        profile_id: str | None
        auth_obj: dn_Auth | None
    """
    result = {
        "ok": False, "reason": "", "school": None,
        "profile_id": None, "auth_obj": None
    }

    if not SESSION_FILE.exists():
        result["reason"] = "session.pkl не найден"
        return result

    try:
        from auth import dn_Auth
        auth = dn_Auth()
        if auth.load_session():
            # load_session уже проверил API и заполнил sid/pid
            result["ok"] = True
            result["school"] = f"school_id={auth.sid}"
            result["profile_id"] = auth.pid
            result["auth_obj"] = auth
            result["reason"] = "сессия живая"
            return result
        else:
            result["reason"] = "cookies не приняты API (403 или мёртвая сессия)"
            return result
    except Exception as e:
        result["reason"] = f"ошибка проверки: {e}"
        return result


# ============================================================
#  Поток проверки сессии (для автозапуска при старте)
# ============================================================
class SessionCheckWorker(QThread):
    done = Signal(dict)

    def run(self):
        self.done.emit(check_saved_session())


# ============================================================
#  Поток ручной загрузки cookies («Войти используя имеющиеся данные»)
# ============================================================
class LoadCookiesWorker(QThread):
    """Просто вызывает check_saved_session в фоне, чтобы UI не зависал."""
    done = Signal(dict)

    def run(self):
        self.done.emit(check_saved_session())


# ============================================================
#  Поток авторизации (Selenium)
# ============================================================
class AuthWorker(QThread):
    """
    Авторизация через Selenium.
    После успеха показывает попап «Куки получены» через сигнал cookies_ready.
    Браузер закрывается только если пользователь нажал «Закрыть браузер».
    При нажатии OK — браузер остаётся открытым, поток отвязывается.
    """
    log = Signal(str)
    finished_ok = Signal(object)
    finished_err = Signal(str)
    cookies_ready = Signal()

    def __init__(self, username: str, password: str,
                 totp_key: str = None, browser: str = "chrome"):
        super().__init__()
        self.username = username
        self.password = password
        self.totp_key = totp_key or ""
        self.browser = browser
        self._close_browser_event = threading.Event()   # «Закрыть браузер»
        self._detach_browser_event = threading.Event()  # «OK — оставить»
        self._current_driver = None

    def _log(self, msg: str):
        print(msg, flush=True)
        self.log.emit(msg)

    def _gui_confirm(self, driver, auth_obj):
        """
        Вызывается из потока Selenium после успешного получения cookies.
        Просит GUI показать попап и ждёт:
          • _close_browser_event — пользователь нажал «Закрыть браузер»
          • _detach_browser_event — пользователь нажал «OK»
        """
        self._current_driver = driver
        self.cookies_ready.emit()

        end = time.time() + 600
        while time.time() < end:
            if self._close_browser_event.is_set():
                try:
                    driver.quit()
                    self._log("[i] Браузер закрыт пользователем")
                except Exception as e:
                    self._log(f"[!] Ошибка закрытия браузера: {e}")
                return
            if self._detach_browser_event.is_set():
                self._log("[i] Браузер оставлен открытым (по выбору пользователя)")
                return
            time.sleep(0.2)

        try:
            driver.quit()
            self._log("[i] Таймаут ожидания. Браузер закрыт.")
        except Exception:
            pass

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
                gui_confirm_callback=self._gui_confirm,
            )

            if success:
                self._log("[+] Авторизация успешна!")
                self.finished_ok.emit(auth)
            else:
                self._log("[!] Авторизация не удалась")
                if self._current_driver is not None:
                    self._close_browser_event.set()
                self.finished_err.emit(
                    "Не удалось авторизоваться.\n"
                    "Проверьте логин, пароль и код 2FA."
                )

        except Exception as e:
            self._log(f"[!] Ошибка: {e}")
            if self._current_driver is not None:
                self._close_browser_event.set()
            self.finished_err.emit(str(e))


# ============================================================
#  Окно авторизации
# ============================================================
class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Вход")
        self.setMinimumSize(640, 680)

        self.auth = None
        self.check_worker = None
        self.load_cookies_worker = None
        self.auth_worker = None
        self.main_window = None

        self._build_ui()
        self._load_saved_credentials()
        self._start_session_check()

    # ------------------------------------------------------------------
    def _build_ui(self):
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
        layout.setSpacing(8)

        title = QLabel("Вход в ЭЖД МЭШ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin: 4px;")

        hint = QLabel(
            "Выберите способ входа:\n"
            "• «Используя имеющиеся данные» — если уже входили ранее (cookies сохранены).\n"
            "• «С использованием браузера» — если нужно авторизоваться заново (Selenium + 2FA)."
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; padding: 4px;")

        # ============================================================
        #  КНОПКА 1: Войти используя имеющиеся данные
        # ============================================================
        self.load_cookies_btn = QPushButton("📂 Войти используя имеющиеся данные")
        self.load_cookies_btn.setMinimumHeight(42)
        self.load_cookies_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: white; font-size: 11pt;
                font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        self.load_cookies_btn.clicked.connect(self.on_login_with_cookies)

        # ============================================================
        #  КНОПКА 2: Войти с использованием браузера
        # ============================================================
        self.login_btn = QPushButton("🌐 Войти с использованием браузера")
        self.login_btn.setMinimumHeight(42)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb; color: white; font-size: 11pt;
                font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        self.login_btn.clicked.connect(self.on_login_with_browser)

        # --- Разделитель «или» ---
        or_label = QLabel("─  или введите логин и пароль ниже  ─")
        or_label.setAlignment(Qt.AlignCenter)
        or_label.setStyleSheet("color: #999; font-size: 9pt; padding: 6px;")

        # --- Поля ввода (для браузерной авторизации) ---
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

        # --- Сборка ---
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addSpacing(4)
        layout.addWidget(self.load_cookies_btn)
        layout.addWidget(self.login_btn)
        layout.addWidget(or_label)
        layout.addWidget(self.login_edit)
        layout.addWidget(self.password_edit)
        layout.addWidget(self.totp_edit)
        layout.addLayout(cb_row)
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
            self.checking_label.setText(
                f"✅ Найдена живая сессия ({result.get('reason')})\n"
                "Открываю главное окно..."
            )
            self.checking_label.setStyleSheet(
                "color: green; font-weight: bold; padding: 8px;"
            )
            self.auth = result.get("auth_obj")
            QTimer.singleShot(700, self._open_main_window)
        else:
            reason = result.get("reason", "неизвестная причина")
            self._show_login_form(f"Сессия не найдена ({reason})")

    # ------------------------------------------------------------------
    def _show_login_form(self, message: str = ""):
        self.checking_label.setText(f"{message}\nПереход к форме входа...")
        self.checking_label.setStyleSheet("color: #666; padding: 8px;")
        QTimer.singleShot(500, lambda: self.stack.setCurrentIndex(1))

    # ------------------------------------------------------------------
    def _open_main_window(self):
        from ui.main_window import MainWindow

        self.main_window = MainWindow()
        if self.auth:
            self.main_window.on_global_auth(self.auth)
        self.main_window.show()
        self.close()

    # ------------------------------------------------------------------
    def on_clear(self):
        answer = QMessageBox.question(
            self, "Подтверждение",
            "Удалить сохранённые логин, пароль, TOTP-ключ и cookies?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            clear_credentials()
            clear_session()
            self.login_edit.clear()
            self.password_edit.clear()
            self.totp_edit.clear()
            self.append_log("[i] Сохранённые данные удалены")

    # ==================================================================
    #  КНОПКА 1: Войти используя имеющиеся данные
    # ==================================================================
    def on_login_with_cookies(self):
        """Пробует зайти по сохранённым cookies БЕЗ браузера."""
        if not SESSION_FILE.exists():
            QMessageBox.warning(
                self, "Нет сохранённых данных",
                "Файл session.pkl не найден.\n\n"
                "Сначала войдите через браузер — тогда cookies сохранятся, "
                "и эта кнопка заработает."
            )
            return

        self.append_log("[i] Проверяю сохранённые cookies...")
        self._set_ui_enabled(False)

        self.load_cookies_worker = LoadCookiesWorker()
        self.load_cookies_worker.done.connect(self._on_cookies_loaded)
        self.load_cookies_worker.start()

    def _on_cookies_loaded(self, result: dict):
        self._set_ui_enabled(True)

        if result.get("ok"):
            self.append_log(f"[+] Cookies живы: {result.get('reason')}")
            self.auth = result.get("auth_obj")
            QTimer.singleShot(300, self._open_main_window)
        else:
            reason = result.get("reason", "неизвестная причина")
            self.append_log(f"[!] Cookies не подошли: {reason}")
            QMessageBox.warning(
                self, "Cookies не подошли",
                f"Сохранённые cookies не приняты сервером.\n\n"
                f"Причина: {reason}\n\n"
                "Войдите с использованием браузера."
            )

    # ==================================================================
    #  КНОПКА 2: Войти с использованием браузера
    # ==================================================================
    def on_login_with_browser(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        totp_key = self.totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(
                self, "Ошибка",
                "Для входа через браузер введите логин и пароль."
            )
            return

        if self.remember_cb.isChecked():
            save_credentials(login, password, totp_key or "")

        self._set_ui_enabled(False)
        self.log_view.clear()
        self.append_log("⏳ Запуск браузера для входа...")

        self.auth_worker = AuthWorker(login, password, totp_key, "chrome")
        self.auth_worker.log.connect(self.append_log)
        self.auth_worker.cookies_ready.connect(self.on_cookies_ready)
        self.auth_worker.finished_ok.connect(self.on_login_ok)
        self.auth_worker.finished_err.connect(self.on_login_err)
        self.auth_worker.start()

    # ------------------------------------------------------------------
    def on_cookies_ready(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Куки получены")
        msg.setText("🍪 Куки успешно получены!")
        msg.setInformativeText(
            "Авторизация в ЭЖД МЭШ завершена.\n\n"
            "• «OK» — оставить окно браузера открытым (закроете вручную).\n"
            "• «Закрыть браузер» — закрыть сейчас и продолжить работу."
        )
        msg.setIcon(QMessageBox.Icon.Information)

        ok_btn = msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        close_btn = msg.addButton("Закрыть браузер", QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(ok_btn)
        msg.exec()

        clicked = msg.clickedButton()

        if self.auth_worker is None:
            return

        if clicked == close_btn:
            self.append_log("[i] Закрываю браузер...")
            self.auth_worker._close_browser_event.set()
        else:
            self.append_log("[i] Браузер оставлен открытым.")
            self.auth_worker._detach_browser_event.set()

    # ------------------------------------------------------------------
    def on_login_ok(self, auth):
        self.auth = auth
        self.append_log("[+] Вход выполнен. Открываю главное окно...")
        QTimer.singleShot(500, self._open_main_window)

    # ------------------------------------------------------------------
    def on_login_err(self, err: str):
        self._set_ui_enabled(True)
        self.append_log(f"[!] {err}")
        QMessageBox.critical(self, "Ошибка входа", err)

    # ------------------------------------------------------------------
    def _set_ui_enabled(self, enabled: bool):
        self.login_btn.setEnabled(enabled)
        self.load_cookies_btn.setEnabled(enabled)
        self.login_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.totp_edit.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)