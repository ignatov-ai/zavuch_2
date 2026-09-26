# -*- coding: utf-8 -*-
"""
Окно авторизации. Открывается при старте приложения.
После успешного входа создаёт MainWindow.

Способы входа:
  1. 📂 Войти используя имеющиеся данные
        → ~/.zavuch2/session.pkl (текущая сохранённая сессия этой версии)
  2. 📁 Обзор… + ✅ Использовать выбранный файл
        → импорт session.pkl с любого пути (например, с другого ПК)
  3. 🌐 Войти с использованием браузера
        → Selenium + 2FA + сохранение в ~/.zavuch2/
  4. 👁 Монитор сессии
        → запускает session_monitor.py отдельным процессом; ловит токен
          из Chrome, запущенного с --remote-debugging-port=9222
  5. 📋 Импорт токенов
        → диалог вставки auth_token/aupd_token из DevTools
          (для случаев, когда вы уже залогинены в Chrome)

Все файлы новой версии хранятся в ~/.zavuch2/ (НЕ трогаем ~/.ejd_checker/).
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
    QPushButton, QCheckBox, QComboBox, QPlainTextEdit,
    QMessageBox, QFrame, QStackedWidget, QFileDialog,
    QGroupBox
)


# === НОВАЯ ПАПКА ДЛЯ НОВОЙ ВЕРСИИ ===
DATA_DIR = Path.home() / ".zavuch2"
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
#  Проверка сохранённой сессии
# ============================================================
def check_saved_session() -> dict:
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
#  Потоки
# ============================================================
class SessionCheckWorker(QThread):
    done = Signal(dict)

    def run(self):
        self.done.emit(check_saved_session())


class LoadCookiesWorker(QThread):
    """Загрузка текущего ~/.zavuch2/session.pkl."""
    done = Signal(dict)

    def run(self):
        self.done.emit(check_saved_session())


class ImportedSessionCheckWorker(QThread):
    """
    Копирует указанный пользователем файл сессии в ~/.zavuch2/session.pkl
    и пробует залогиниться.
    Если рядом с исходным файлом лежит auth_data.json — тоже копирует.
    """
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
                result["reason"] = f"Не удалось скопировать файл: {e}"
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
                    "Файл скопирован, но API не принял сессию.\n"
                    "Вероятно, токен устарел или привязан к другому устройству.\n\n"
                    "Можно попробовать войти через браузер."
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
                 totp_key: str = None, browser: str = "chrome"):
        super().__init__()
        self.username = username
        self.password = password
        self.totp_key = totp_key or ""
        self.browser = browser
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
        self.setMinimumSize(680, 900)

        self.auth = None
        self.check_worker = None
        self.load_cookies_worker = None
        self.import_worker = None
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
            "• «Используя имеющиеся данные» — если уже входили в этой версии.\n"
            "• «Импорт файла сессии» — если нужно подключить session.pkl с другого ПК.\n"
            "• «С использованием браузера» — если нужно авторизоваться заново (Selenium + 2FA).\n"
            "• «Монитор сессии» — ловит токен из Chrome с --remote-debugging-port=9222.\n"
            "• «Импорт токенов» — вставить auth_token/aupd_token из DevTools вручную."
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
        #  БЛОК ИМПОРТА: поле пути + Обзор + Использовать
        # ============================================================
        import_group = QGroupBox("📁 Импорт файла сессии с другого компьютера")
        import_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 10pt;
                border: 1px solid #cccccc; border-radius: 8px;
                margin-top: 8px; padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 6px 0 6px; color: #4b5563;
            }
        """)
        import_layout = QVBoxLayout(import_group)
        import_layout.setSpacing(6)

        file_row = QHBoxLayout()
        file_row.setSpacing(6)

        self.session_path_edit = QLineEdit()
        self.session_path_edit.setPlaceholderText(
            "Путь к файлу session.pkl (например, с другого ПК)"
        )
        self.session_path_edit.setMinimumHeight(34)
        self.session_path_edit.textChanged.connect(self._update_use_file_btn)
        file_row.addWidget(self.session_path_edit, 1)

        self.browse_session_btn = QPushButton("📁 Обзор…")
        self.browse_session_btn.setMinimumHeight(34)
        self.browse_session_btn.setMaximumWidth(100)
        self.browse_session_btn.clicked.connect(self.on_browse_session_file)
        file_row.addWidget(self.browse_session_btn)

        import_layout.addLayout(file_row)

        self.use_session_file_btn = QPushButton("✅ Использовать выбранный файл")
        self.use_session_file_btn.setMinimumHeight(38)
        self.use_session_file_btn.setEnabled(False)
        self.use_session_file_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280; color: white; font-size: 10pt;
                font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #4b5563; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """)
        self.use_session_file_btn.clicked.connect(self.on_use_selected_file)
        import_layout.addWidget(self.use_session_file_btn)

        # ============================================================
        #  КНОПКА 3: Войти с использованием браузера
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

        # ============================================================
        #  КНОПКА 4: Монитор сессии
        # ============================================================
        self.monitor_btn = QPushButton("👁 Монитор сессии")
        self.monitor_btn.setMinimumHeight(34)
        self.monitor_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6; color: white; font-size: 10pt;
                font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #7c3aed; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """)
        self.monitor_btn.setToolTip(
            "Запустить отдельный процесс, который будет ловить auth_token "
            "из Chrome (запущенного с --remote-debugging-port=9222)"
        )
        self.monitor_btn.clicked.connect(self.on_start_monitor)

        # ============================================================
        #  КНОПКА 5: Импорт токенов (вставить из буфера)
        # ============================================================
        self.import_tokens_btn = QPushButton("📋 Импорт токенов")
        self.import_tokens_btn.setMinimumHeight(34)
        self.import_tokens_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9; color: white; font-size: 10pt;
                font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #0284c7; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """)
        self.import_tokens_btn.setToolTip(
            "Вставить auth_token / aupd_token из DevTools браузера — "
            "для случаев, когда сессия уже есть в обычном Chrome"
        )
        self.import_tokens_btn.clicked.connect(self.on_open_token_dialog)

        # --- Подсказка про текущий путь ---
        path_hint = QLabel(f"ℹ️ Текущая сессия хранится в:\n{DATA_DIR}")
        path_hint.setAlignment(Qt.AlignCenter)
        path_hint.setStyleSheet("color: #999; font-size: 8pt; padding: 2px;")
        path_hint.setWordWrap(True)

        or_label = QLabel("─  или введите логин и пароль для браузерного входа  ─")
        or_label.setAlignment(Qt.AlignCenter)
        or_label.setStyleSheet("color: #999; font-size: 9pt; padding: 6px;")

        # --- Поля ввода для Selenium ---
        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Логин (телефон, email или СНИЛС)")
        self.login_edit.setMinimumHeight(34)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(34)

        self.totp_edit = QLineEdit()
        self.totp_edit.setPlaceholderText(
            "TOTP-ключ (Base32; можно пусто — SMS вручную)"
        )
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
        layout.addWidget(import_group)
        layout.addWidget(self.login_btn)
        layout.addWidget(self.monitor_btn)
        layout.addWidget(self.import_tokens_btn)
        layout.addWidget(path_hint)
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
        if not SESSION_FILE.exists():
            QMessageBox.warning(
                self, "Нет сохранённых данных",
                f"Файл session.pkl не найден по пути:\n{SESSION_FILE}\n\n"
                "Можно импортировать файл через блок «📁 Импорт файла сессии»,\n"
                "либо вставить токен через «📋 Импорт токенов»,\n"
                "либо войти через браузер."
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
                "Можно войти с использованием браузера."
            )

    # ==================================================================
    #  БЛОК ИМПОРТА: Обзор и Использовать
    # ==================================================================
    def on_browse_session_file(self):
        start_dir = str(Path.home())

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл сессии (session.pkl)",
            start_dir,
            "Pickle session files (*.pkl);;Все файлы (*.*)"
        )

        if not file_path:
            return

        self.session_path_edit.setText(file_path)
        self.append_log(f"[i] Выбран файл: {file_path}")
        self.append_log("[i] Нажмите «✅ Использовать выбранный файл» для импорта.")

    def _update_use_file_btn(self, text: str):
        path_str = (text or "").strip()
        self.use_session_file_btn.setEnabled(bool(path_str))

    def on_use_selected_file(self):
        file_path = self.session_path_edit.text().strip()
        if not file_path:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите файл сессии.")
            return

        src = Path(file_path)
        if not src.exists():
            QMessageBox.warning(
                self, "Файл не найден",
                f"Файл не существует:\n{src}"
            )
            return

        if SESSION_FILE.exists():
            answer = QMessageBox.question(
                self, "Подтверждение",
                f"Текущая сессия уже существует:\n{SESSION_FILE}\n\n"
                f"Заменить её на выбранный файл?\n{src}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self._set_ui_enabled(False)
        self.append_log(f"[i] Импортирую файл сессии: {src}")

        self.import_worker = ImportedSessionCheckWorker(str(src))
        self.import_worker.done.connect(self._on_import_finished)
        self.import_worker.start()

    def _on_import_finished(self, result: dict):
        self._set_ui_enabled(True)

        if result.get("ok"):
            self.append_log(f"[+] {result.get('reason')}")
            self.auth = result.get("auth_obj")
            QTimer.singleShot(300, self._open_main_window)
        else:
            self.append_log(f"[!] {result.get('reason')}")
            QMessageBox.warning(
                self, "Сессия не подошла",
                result.get("reason", "Неизвестная ошибка")
            )

    # ==================================================================
    #  КНОПКА 3: Войти с использованием браузера
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

    # ==================================================================
    #  КНОПКА 4: Монитор сессии
    # ==================================================================
    def on_start_monitor(self):
        import subprocess
        import sys as _sys
        from pathlib import Path as _Path

        project_root = _Path(__file__).resolve().parent.parent
        monitor_script = project_root / "session_monitor.py"

        if not monitor_script.exists():
            QMessageBox.warning(
                self, "Не найден монитор",
                f"Файл не найден:\n{monitor_script}\n\n"
                "Сохраните session_monitor.py в корень проекта."
            )
            return

        answer = QMessageBox.question(
            self, "Монитор сессии",
            "Запустить монитор сессии?\n\n"
            "⚠️ Требуется Chrome, запущенный с флагом:\n"
            "--remote-debugging-port=9222\n\n"
            "Откроется окно консоли — там будет виден лог монитора.\n"
            "Как только токен будет пойман, сессия сохранится в ~/.zavuch2/,\n"
            "а монитор завершится.\n\n"
            "Потом нажмите «📂 Войти используя имеющиеся данные».\n\n"
            "Продолжить?",
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
            self.append_log(f"[i] Монитор запущен: {monitor_script}")
            self.append_log("[i] Следите за окном консоли.")
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка запуска",
                f"Не удалось запустить монитор:\n{e}"
            )

    # ==================================================================
    #  КНОПКА 5: Импорт токенов (диалог)
    # ==================================================================
    def on_open_token_dialog(self):
        """Открывает диалог импорта токенов."""
        from ui.token_import_dialog import TokenImportDialog

        dlg = TokenImportDialog(self)
        dlg.tokens_saved.connect(self._on_tokens_saved)
        dlg.exec()

    def _on_tokens_saved(self, auth):
        """Вызывается после успешного сохранения токенов в диалоге."""
        if auth is None:
            return
        self.append_log("[+] Токены импортированы, открываю главное окно…")
        self.auth = auth
        QTimer.singleShot(300, self._open_main_window)

    # ------------------------------------------------------------------
    def _set_ui_enabled(self, enabled: bool):
        self.login_btn.setEnabled(enabled)
        self.load_cookies_btn.setEnabled(enabled)
        self.browse_session_btn.setEnabled(enabled)
        self.monitor_btn.setEnabled(enabled)
        self.import_tokens_btn.setEnabled(enabled)
        if enabled:
            self._update_use_file_btn(self.session_path_edit.text())
        else:
            self.use_session_file_btn.setEnabled(False)
        self.session_path_edit.setEnabled(enabled)
        self.login_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.totp_edit.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)