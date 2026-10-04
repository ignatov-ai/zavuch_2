# -*- coding: utf-8 -*-
"""
Компактное окно авторизации zavuch 2.

Основные действия вынесены на первый план:
- ЭЖД: войти по сохранённой сессии или импортировать данные.
- ПДОУ: импортировать сессию.

Редкие действия (токен, файлы, Selenium, TOTP) расположены
в раскрывающихся разделах «Другие способы входа».
"""

import json
import pickle
import shutil
import threading
import time
import zipfile
from http.cookiejar import Cookie
from pathlib import Path

import requests

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paths import (
    SESSIONS_DIR,
    SESSION_FILE,
    AUTH_DATA_FILE,
    CREDENTIALS_FILE,
    PDOU_TOKEN_FILE,
    PDOU_COOKIES_FILE,
    EJD_FILES,
    PDOU_FILES,
)


# ============================================================
# Утилиты
# ============================================================

def load_credentials() -> dict:
    """Загружает сохранённые данные ЭЖД."""
    if not CREDENTIALS_FILE.exists():
        return {}

    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_credentials(login: str, password: str, totp_key: str = "") -> bool:
    """Сохраняет логин и пароль для ЭЖД."""
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "login": login,
                    "password": password,
                    "totp_key": totp_key or "",
                },
                file,
                ensure_ascii=False,
                indent=2,
            )
        return True
    except Exception:
        return False


def load_pdou_token() -> dict:
    """Загружает сохранённые данные ПДОУ."""
    if not PDOU_TOKEN_FILE.exists():
        return {}

    try:
        with open(PDOU_TOKEN_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def format_file_info(file_path: Path) -> str:
    """Формирует короткую строку статуса файла сессии."""
    if file_path.exists():
        modified = time.strftime(
            "%d.%m.%Y %H:%M",
            time.localtime(file_path.stat().st_mtime),
        )
        size = file_path.stat().st_size
        return f"✓ {file_path.name} — {size} Б, {modified}"

    return f"— {file_path.name} не найден"


def _build_cookie(name, value, domain):
    """Создаёт cookie в совместимом формате."""
    return Cookie(
        version=0,
        name=name,
        value=str(value),
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=False,
        expires=None,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


# ============================================================
# Проверка ЭЖД-сессии
# ============================================================

def check_saved_session() -> dict:
    """
    Проверяет файл session.pkl через dn_Auth.

    Возвращает:
    {
        "ok": bool,
        "reason": str,
        "auth_obj": dn_Auth | None,
    }
    """
    result = {
        "ok": False,
        "reason": "",
        "auth_obj": None,
    }

    if not SESSION_FILE.exists():
        result["reason"] = "сохранённая сессия не найдена"
        return result

    try:
        if SESSION_FILE.stat().st_size == 0:
            result["reason"] = "файл session.pkl пустой"
            return result
    except Exception:
        pass

    try:
        from auth import dn_Auth

        auth = dn_Auth()

        if auth.load_session():
            result["ok"] = True
            result["auth_obj"] = auth
            result["reason"] = "сессия активна"
            return result

        result["reason"] = "сервер не принял сохранённые cookies"
        return result

    except Exception as error:
        result["reason"] = f"ошибка проверки: {error}"
        return result


# ============================================================
# Фоновые потоки
# ============================================================

class SessionCheckWorker(QThread):
    """Фоновая проверка сохранённой ЭЖД-сессии."""

    done = Signal(dict)

    def run(self):
        self.done.emit(check_saved_session())


class TokenLoginWorker(QThread):
    """
    Проверяет auth_token, создаёт session.pkl и auth_data.json,
    затем пытается восстановить dn_Auth.
    """

    log = Signal(str)
    finished_ok = Signal(object)
    finished_err = Signal(str)

    def __init__(
        self,
        auth_token: str,
        profile_id: str = "",
        school_id: str = "",
    ):
        super().__init__()
        self.auth_token = auth_token.strip()
        self.profile_id = str(profile_id or "").strip()
        self.school_id = str(school_id or "").strip()

    def _log(self, message: str):
        print(message, flush=True)
        self.log.emit(message)

    def run(self):
        try:
            if not self.auth_token:
                self.finished_err.emit("Токен не указан.")
                return

            if len(self.auth_token) < 50:
                self.finished_err.emit(
                    f"Токен слишком короткий: {len(self.auth_token)} символов."
                )
                return

            self._log(
                f"[i] Проверка токена: {len(self.auth_token)} символов."
            )
            self._log("[i] Запрашиваю список школ ЭЖД...")

            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Auth-Token": self.auth_token,
                    "Authorization": f"Bearer {self.auth_token}",
                }
            )

            if self.profile_id:
                session.headers["Profile-Id"] = self.profile_id

            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                session.cookies.set(
                    "auth_token",
                    self.auth_token,
                    domain=domain,
                )

            if self.profile_id:
                session.cookies.set(
                    "profile_id",
                    self.profile_id,
                    domain="dnevnik.mos.ru",
                )

            try:
                response = session.get(
                    "https://dnevnik.mos.ru/core/api/schools",
                    timeout=15,
                )
            except Exception as error:
                self.finished_err.emit(f"Ошибка сети: {error}")
                return

            self._log(f"[i] Ответ сервера: HTTP {response.status_code}")

            if response.status_code != 200:
                self.finished_err.emit(
                    f"Сервер вернул HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
                return

            try:
                data = response.json()
            except Exception:
                self.finished_err.emit("Сервер вернул ответ не в формате JSON.")
                return

            if not data:
                self.finished_err.emit("Сервер вернул пустой список школ.")
                return

            school_name = data[0].get("name", "?")
            school_id = str(
                data[0].get("id", "")
                or self.school_id
                or ""
            )

            self._log(f"[+] Токен принят. Школа: {school_name}")

            cookies_list = []
            for cookie in session.cookies:
                cookies_list.append(
                    {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain,
                        "path": cookie.path or "/",
                        "secure": bool(cookie.secure),
                        "expires": cookie.expires,
                    }
                )

            with open(SESSION_FILE, "wb") as file:
                pickle.dump(cookies_list, file)

            with open(AUTH_DATA_FILE, "w", encoding="utf-8") as file:
                json.dump(
                    {
                        "auth_token": self.auth_token,
                        "aupd_token": self.auth_token,
                        "profile_id": self.profile_id,
                        "school_id": school_id,
                    },
                    file,
                    ensure_ascii=False,
                    indent=2,
                )

            self._log(f"[+] Сохранён: {SESSION_FILE.name}")
            self._log(f"[+] Сохранён: {AUTH_DATA_FILE.name}")

            try:
                from auth import dn_Auth

                auth = dn_Auth()
                if auth.load_session():
                    self._log("[+] Сессия успешно восстановлена.")
                    self.finished_ok.emit(auth)
                    return

            except Exception as error:
                self._log(f"[!] Не удалось проверить сессию через dn_Auth: {error}")

            self.finished_err.emit(
                "Токен принят сервером, но приложение не смогло "
                "восстановить сессию. Проверьте auth_data.json."
            )

        except Exception as error:
            import traceback

            self._log(f"[!] Ошибка: {error}")
            self._log(traceback.format_exc())
            self.finished_err.emit(f"Ошибка входа по токену: {error}")


class AuthWorker(QThread):
    """Выполняет Selenium-авторизацию в отдельном потоке."""

    log = Signal(str)
    finished_ok = Signal(object)
    finished_err = Signal(str)
    cookies_ready = Signal()

    def __init__(
        self,
        username: str,
        password: str,
        totp_key: str = None,
        browser: str = "chrome",
        pdou_mode: bool = False,
    ):
        super().__init__()

        self.username = username
        self.password = password
        self.totp_key = totp_key or ""
        self.browser = browser
        self.pdou_mode = pdou_mode

        self._close_browser_event = threading.Event()
        self._detach_browser_event = threading.Event()
        self._current_driver = None

    def _log(self, message: str):
        print(message, flush=True)
        self.log.emit(message)

    def _gui_confirm(self, driver, auth_obj):
        """Ожидает решения пользователя: оставить или закрыть браузер."""
        self._current_driver = driver
        self.cookies_ready.emit()

        deadline = time.time() + 600

        while time.time() < deadline:
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
        try:
            from auth import dn_Auth

            self._log("=== Начало авторизации ===")
            self._log(f"[i] Логин: {self.username}")
            self._log(
                f"[i] 2FA: {'TOTP' if self.totp_key else 'SMS вручную'}"
            )
            self._log(
                f"[i] Режим: {'ПДОУ' if self.pdou_mode else 'ЭЖД'}"
            )

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
                self._log("[+] Авторизация успешно завершена.")
                self.finished_ok.emit(auth)
                return

            self._log("[!] Не удалось авторизоваться.")

            if self._current_driver is not None:
                self._close_browser_event.set()

            self.finished_err.emit("Не удалось авторизоваться.")

        except Exception as error:
            self._log(f"[!] Ошибка: {error}")

            if self._current_driver is not None:
                self._close_browser_event.set()

            self.finished_err.emit(str(error))


class ZipImportWorker(QThread):
    """Восстанавливает файлы сессий из ZIP-архива."""

    done = Signal(dict)

    def __init__(
        self,
        zip_path: str,
        import_ejd: bool,
        import_pdou: bool,
    ):
        super().__init__()
        self.zip_path = zip_path
        self.import_ejd = import_ejd
        self.import_pdou = import_pdou

    def run(self):
        result = {
            "ok": False,
            "restored": [],
            "reason": "",
            "ejud": False,
            "pdou": False,
        }

        try:
            with zipfile.ZipFile(self.zip_path, "r") as archive:
                names = archive.namelist()

                has_ejd = any(name in EJD_FILES for name in names)
                has_pdou = any(name in PDOU_FILES for name in names)

                result["ejud"] = has_ejd
                result["pdou"] = has_pdou

                files_to_restore = []

                if self.import_ejd:
                    files_to_restore.extend(EJD_FILES)

                if self.import_pdou:
                    files_to_restore.extend(PDOU_FILES)

                for filename in files_to_restore:
                    if filename not in names:
                        continue

                    target = SESSIONS_DIR / filename

                    with archive.open(filename) as source:
                        with open(target, "wb") as destination:
                            shutil.copyfileobj(source, destination)

                    result["restored"].append(filename)

            result["ok"] = bool(result["restored"])

            if not result["ok"]:
                result["reason"] = (
                    "В архиве не найдены файлы выбранных сессий."
                )

        except Exception as error:
            result["reason"] = f"Ошибка импорта: {error}"

        self.done.emit(result)


# ============================================================
# Окно авторизации
# ============================================================

class AuthWindow(QWidget):
    """Главное окно входа в приложение."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("zavuch 2 — Вход")
        self.resize(920, 980)
        self.setMinimumSize(760, 560)

        self.auth = None
        self.check_worker = None
        self.ejd_auth_worker = None
        self.pdou_auth_worker = None
        self.token_login_worker = None
        self.zip_worker = None
        self.enter_check_worker = None
        self.main_window = None

        self._build_ui()
        self._load_saved_credentials()
        self._refresh_statuses()
        self._start_session_check()

    # --------------------------------------------------------
    # Построение интерфейса
    # --------------------------------------------------------

    def _build_ui(self):
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_checking_screen())
        self.stack.addWidget(self._build_login_screen())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.setLayout(layout)

    def _build_checking_screen(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("zavuch 2")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #0f172a;"
        )

        self.checking_label = QLabel("Проверяю сохранённую сессию...")
        self.checking_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.checking_label.setWordWrap(True)
        self.checking_label.setStyleSheet(
            "color: #64748b; padding: 8px; font-size: 11pt;"
        )

        layout.addStretch()
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self.checking_label)
        layout.addStretch()

        return widget

    def _build_login_screen(self) -> QWidget:
        widget = QWidget()

        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(10)

        title = QLabel("Вход в систему")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #0f172a;"
        )
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Выберите нужный раздел или восстановите сохранённую сессию."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #64748b;")
        main_layout.addWidget(subtitle)

        columns = QHBoxLayout()
        columns.setSpacing(12)

        columns.addWidget(self._build_ejd_column(), 1)
        columns.addWidget(self._build_pdou_column(), 1)

        main_layout.addLayout(columns, 1)

        main_layout.addLayout(self._build_service_row())
        main_layout.addWidget(self._build_log_section())

        self.setStyleSheet("""
            QWidget {
                font-size: 10pt;
                color: #1e293b;
            }

            QLineEdit {
                min-height: 30px;
                padding: 2px 7px;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                background: white;
            }

            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }

            QPushButton {
                min-height: 28px;
                padding: 3px 9px;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                background: #f8fafc;
            }

            QPushButton:hover {
                background: #e2e8f0;
            }

            QPushButton:disabled {
                background: #e5e7eb;
                color: #94a3b8;
                border-color: #e5e7eb;
            }

            QToolButton {
                min-height: 23px;
                padding: 2px 4px;
                border: none;
                text-align: left;
                color: #334155;
                font-weight: 600;
            }

            QToolButton:hover {
                color: #1d4ed8;
                background: #eff6ff;
                border-radius: 4px;
            }

            QCheckBox {
                color: #475569;
            }
        """)

        return widget

    def _build_service_row(self) -> QHBoxLayout:
        """Нижняя строка с редкими общими действиями."""
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self.zip_import_btn = QPushButton("Импорт архива")
        self.zip_import_btn.setToolTip(
            "Восстановить ЭЖД- и/или ПДОУ-сессии из ZIP-архива."
        )
        self.zip_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                font-weight: 600;
                border: none;
            }

            QPushButton:hover {
                background-color: #047857;
            }
        """)
        self.zip_import_btn.clicked.connect(self.on_zip_import)

        self.refresh_btn = QPushButton("Обновить статусы")
        self.refresh_btn.setToolTip(
            "Обновить информацию о сохранённых файлах сессии."
        )
        self.refresh_btn.clicked.connect(self._refresh_statuses)

        self.clear_all_btn = QPushButton("Очистить всё")
        self.clear_all_btn.setToolTip(
            "Удалить все сохранённые сессии ЭЖД и ПДОУ."
        )
        self.clear_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #fff1f2;
                color: #be123c;
                border: 1px solid #fecdd3;
                font-weight: 600;
            }

            QPushButton:hover {
                background-color: #ffe4e6;
            }
        """)
        self.clear_all_btn.clicked.connect(self.on_clear_all)

        layout.addStretch()
        layout.addWidget(self.zip_import_btn)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.clear_all_btn)
        layout.addStretch()

        return layout

    def _build_log_section(self) -> QWidget:
        """Создаёт сворачиваемый раздел журнала."""
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setMinimumHeight(120)
        self.log_view.setMaximumHeight(150)
        self.log_view.setStyleSheet("""
            QPlainTextEdit {
                font-family: Consolas, "Courier New", monospace;
                font-size: 9pt;
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 5px;
            }
        """)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.log_view)

        return self._make_collapsible_section(
            "Журнал работы",
            content,
            expanded=False,
        )

    # --------------------------------------------------------
    # Колонка ЭЖД
    # --------------------------------------------------------

    def _build_ejd_column(self) -> QWidget:
        group = QGroupBox("ЭЖД")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14pt;
                font-weight: 700;
                color: #1d4ed8;
                border: 1px solid #93c5fd;
                border-radius: 10px;
                margin-top: 10px;
                padding: 13px 12px 12px 12px;
                background: #ffffff;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(13, 18, 13, 13)
        layout.setSpacing(8)

        description = QLabel("Журналы, оценки и итоги")
        description.setStyleSheet("color: #64748b;")
        layout.addWidget(description)

        self.ejd_status_label = QLabel("Проверяю сохранённую сессию...")
        self.ejd_status_label.setWordWrap(True)
        self.ejd_status_label.setStyleSheet("""
            color: #1e40af;
            background: #eff6ff;
            border-radius: 6px;
            padding: 7px;
            font-weight: 600;
        """)
        layout.addWidget(self.ejd_status_label)

        self.ejd_enter_btn = QPushButton("Войти в ЭЖД")
        self.ejd_enter_btn.setMinimumHeight(42)
        self.ejd_enter_btn.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                color: white;
                font-size: 11pt;
                font-weight: 700;
                border: none;
                border-radius: 7px;
            }

            QPushButton:hover {
                background-color: #15803d;
            }
        """)
        self.ejd_enter_btn.clicked.connect(self.on_enter_ejd)
        layout.addWidget(self.ejd_enter_btn)

        self.ejd_import_btn = QPushButton("Импортировать ЭЖД-сессию")
        self.ejd_import_btn.setToolTip(
            "Импортировать JSON-токены или файл сессии ЭЖД."
        )
        self.ejd_import_btn.setStyleSheet("""
            QPushButton {
                color: #1d4ed8;
                background: #eff6ff;
                border: 1px solid #bfdbfe;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #dbeafe;
            }
        """)
        self.ejd_import_btn.clicked.connect(self.on_import_ejd_json)
        layout.addWidget(self.ejd_import_btn)

        advanced = self._build_ejd_advanced_section()
        layout.addWidget(
            self._make_collapsible_section(
                "Другие способы входа",
                advanced,
                expanded=False,
            )
        )

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)

        self.ejd_files_label = QLabel()
        self.ejd_files_label.setWordWrap(True)
        self.ejd_files_label.setStyleSheet("""
            font-family: Consolas, "Courier New", monospace;
            font-size: 8pt;
            color: #64748b;
            padding: 4px;
        """)
        details_layout.addWidget(self.ejd_files_label)

        layout.addWidget(
            self._make_collapsible_section(
                "Детали сессии",
                details,
                expanded=False,
            )
        )

        layout.addStretch()

        self.ejd_clear_btn = QPushButton("Очистить ЭЖД-сессию")
        self.ejd_clear_btn.setToolTip(
            "Удалить сохранённые cookies, токены и данные входа ЭЖД."
        )
        self.ejd_clear_btn.setStyleSheet("""
            QPushButton {
                color: #b91c1c;
                background: #fff1f2;
                border: 1px solid #fecdd3;
            }

            QPushButton:hover {
                background: #ffe4e6;
            }
        """)
        self.ejd_clear_btn.clicked.connect(self.on_clear_ejd)
        layout.addWidget(self.ejd_clear_btn)

        return group

    def _build_ejd_advanced_section(self) -> QWidget:
        """Создаёт скрытые способы авторизации ЭЖД."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        token_label = QLabel("Вход по токену")
        token_label.setStyleSheet("font-weight: 600; color: #334155;")
        layout.addWidget(token_label)

        self.ejd_token_edit = QLineEdit()
        self.ejd_token_edit.setPlaceholderText("Вставьте auth_token")
        self.ejd_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ejd_token_edit.textChanged.connect(self._on_ejd_token_changed)
        layout.addWidget(self.ejd_token_edit)

        token_row = QHBoxLayout()
        token_row.setSpacing(6)

        self.ejd_token_paste_btn = QPushButton("Вставить")
        self.ejd_token_paste_btn.setToolTip(
            "Вставить токен из буфера обмена."
        )
        self.ejd_token_paste_btn.clicked.connect(self.on_ejd_token_paste)

        self.ejd_token_login_btn = QPushButton("Войти по токену")
        self.ejd_token_login_btn.setEnabled(False)
        self.ejd_token_login_btn.setStyleSheet("""
            QPushButton {
                background: #0284c7;
                color: white;
                border: none;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #0369a1;
            }
        """)
        self.ejd_token_login_btn.clicked.connect(self.on_login_by_token)

        token_row.addWidget(self.ejd_token_paste_btn)
        token_row.addWidget(self.ejd_token_login_btn, 1)
        layout.addLayout(token_row)

        optional_ids = QWidget()
        optional_ids_layout = QHBoxLayout(optional_ids)
        optional_ids_layout.setContentsMargins(0, 0, 0, 0)
        optional_ids_layout.setSpacing(6)

        self.ejd_profile_id_edit = QLineEdit()
        self.ejd_profile_id_edit.setPlaceholderText("profile_id, необязательно")

        self.ejd_school_id_edit = QLineEdit()
        self.ejd_school_id_edit.setPlaceholderText("school_id, необязательно")

        optional_ids_layout.addWidget(self.ejd_profile_id_edit, 1)
        optional_ids_layout.addWidget(self.ejd_school_id_edit, 1)

        layout.addWidget(
            self._make_collapsible_section(
                "Дополнительные параметры токена",
                optional_ids,
                expanded=False,
            )
        )

        layout.addWidget(self._make_sep())

        import_title = QLabel("Импорт отдельных файлов")
        import_title.setStyleSheet("font-weight: 600; color: #334155;")
        layout.addWidget(import_title)

        import_row = QHBoxLayout()
        import_row.setSpacing(6)

        self.ejd_load_pkl_btn = QPushButton("Файл session.pkl")
        self.ejd_load_pkl_btn.setToolTip(
            "Загрузить готовый файл session.pkl."
        )
        self.ejd_load_pkl_btn.clicked.connect(self.on_load_ejd_pkl)

        self.ejd_load_zip_btn = QPushButton("ZIP только ЭЖД")
        self.ejd_load_zip_btn.setToolTip(
            "Импортировать из ZIP только ЭЖД-сессию."
        )
        self.ejd_load_zip_btn.clicked.connect(
            lambda: self.on_zip_import("ejd")
        )

        import_row.addWidget(self.ejd_load_pkl_btn)
        import_row.addWidget(self.ejd_load_zip_btn)
        layout.addLayout(import_row)

        layout.addWidget(self._make_sep())

        browser_title = QLabel("Вход через браузер")
        browser_title.setStyleSheet("font-weight: 600; color: #334155;")
        layout.addWidget(browser_title)

        self.ejd_login_edit = QLineEdit()
        self.ejd_login_edit.setPlaceholderText("Телефон, e-mail или СНИЛС")
        layout.addWidget(self.ejd_login_edit)

        self.ejd_password_edit = QLineEdit()
        self.ejd_password_edit.setPlaceholderText("Пароль")
        self.ejd_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.ejd_password_edit)

        options_row = QHBoxLayout()
        options_row.setSpacing(10)

        self.ejd_show_pass_cb = QCheckBox("Показать пароль")
        self.ejd_show_pass_cb.stateChanged.connect(
            lambda state: self._toggle_echo(
                self.ejd_password_edit,
                state,
            )
        )

        self.ejd_remember_cb = QCheckBox("Запомнить данные")
        self.ejd_remember_cb.setChecked(True)

        options_row.addWidget(self.ejd_show_pass_cb)
        options_row.addWidget(self.ejd_remember_cb)
        options_row.addStretch()

        layout.addLayout(options_row)

        self.ejd_login_btn = QPushButton("Войти через браузер")
        self.ejd_login_btn.setStyleSheet("""
            QPushButton {
                background: #2563eb;
                color: white;
                border: none;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #1d4ed8;
            }
        """)
        self.ejd_login_btn.clicked.connect(self.on_login_ejd)
        layout.addWidget(self.ejd_login_btn)

        return content

    # --------------------------------------------------------
    # Колонка ПДОУ
    # --------------------------------------------------------

    def _build_pdou_column(self) -> QWidget:
        group = QGroupBox("ПДОУ")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14pt;
                font-weight: 700;
                color: #7c3aed;
                border: 1px solid #c4b5fd;
                border-radius: 10px;
                margin-top: 10px;
                padding: 13px 12px 12px 12px;
                background: #ffffff;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(13, 18, 13, 13)
        layout.setSpacing(8)

        description = QLabel("Кружки и заявления")
        description.setStyleSheet("color: #64748b;")
        layout.addWidget(description)

        self.pdou_status_label = QLabel("Проверяю сохранённые файлы...")
        self.pdou_status_label.setWordWrap(True)
        self.pdou_status_label.setStyleSheet("""
            color: #6d28d9;
            background: #f5f3ff;
            border-radius: 6px;
            padding: 7px;
            font-weight: 600;
        """)
        layout.addWidget(self.pdou_status_label)

        self.pdou_import_btn = QPushButton("Импортировать ПДОУ-сессию")
        self.pdou_import_btn.setMinimumHeight(42)
        self.pdou_import_btn.setToolTip(
            "Импортировать JSON-токены или файл сессии ПДОУ."
        )
        self.pdou_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                font-size: 11pt;
                font-weight: 700;
                border: none;
                border-radius: 7px;
            }

            QPushButton:hover {
                background-color: #7c3aed;
            }
        """)
        self.pdou_import_btn.clicked.connect(self.on_import_pdou_json)
        layout.addWidget(self.pdou_import_btn)

        advanced = self._build_pdou_advanced_section()
        layout.addWidget(
            self._make_collapsible_section(
                "Другие способы входа",
                advanced,
                expanded=False,
            )
        )

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)

        self.pdou_files_label = QLabel()
        self.pdou_files_label.setWordWrap(True)
        self.pdou_files_label.setStyleSheet("""
            font-family: Consolas, "Courier New", monospace;
            font-size: 8pt;
            color: #64748b;
            padding: 4px;
        """)
        details_layout.addWidget(self.pdou_files_label)

        layout.addWidget(
            self._make_collapsible_section(
                "Детали сессии",
                details,
                expanded=False,
            )
        )

        layout.addStretch()

        self.pdou_clear_btn = QPushButton("Очистить ПДОУ-сессию")
        self.pdou_clear_btn.setToolTip(
            "Удалить сохранённые токены и cookies ПДОУ."
        )
        self.pdou_clear_btn.setStyleSheet("""
            QPushButton {
                color: #6b21a8;
                background: #faf5ff;
                border: 1px solid #e9d5ff;
            }

            QPushButton:hover {
                background: #f3e8ff;
            }
        """)
        self.pdou_clear_btn.clicked.connect(self.on_clear_pdou)
        layout.addWidget(self.pdou_clear_btn)

        return group

    def _build_pdou_advanced_section(self) -> QWidget:
        """Создаёт скрытые способы авторизации ПДОУ."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        import_title = QLabel("Импорт файла")
        import_title.setStyleSheet("font-weight: 600; color: #334155;")
        layout.addWidget(import_title)

        import_row = QHBoxLayout()
        import_row.setSpacing(6)

        self.pdou_load_json_btn = QPushButton("Файл pdou_token.json")
        self.pdou_load_json_btn.setToolTip(
            "Загрузить файл pdou_token.json."
        )
        self.pdou_load_json_btn.clicked.connect(self.on_load_pdou_json)

        self.pdou_load_zip_btn = QPushButton("ZIP только ПДОУ")
        self.pdou_load_zip_btn.setToolTip(
            "Импортировать из ZIP только ПДОУ-сессию."
        )
        self.pdou_load_zip_btn.clicked.connect(
            lambda: self.on_zip_import("pdou")
        )

        import_row.addWidget(self.pdou_load_json_btn)
        import_row.addWidget(self.pdou_load_zip_btn)
        layout.addLayout(import_row)

        layout.addWidget(self._make_sep())

        browser_title = QLabel("Вход через браузер")
        browser_title.setStyleSheet("font-weight: 600; color: #334155;")
        layout.addWidget(browser_title)

        self.pdou_login_edit = QLineEdit()
        self.pdou_login_edit.setPlaceholderText(
            "Логин учётной записи с доступом к ПДОУ"
        )
        layout.addWidget(self.pdou_login_edit)

        self.pdou_password_edit = QLineEdit()
        self.pdou_password_edit.setPlaceholderText("Пароль")
        self.pdou_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.pdou_password_edit)

        self.pdou_totp_edit = QLineEdit()
        self.pdou_totp_edit.setPlaceholderText(
            "TOTP-ключ Base32, если используется"
        )
        layout.addWidget(self.pdou_totp_edit)

        self.pdou_show_pass_cb = QCheckBox("Показать пароль")
        self.pdou_show_pass_cb.stateChanged.connect(
            lambda state: self._toggle_echo(
                self.pdou_password_edit,
                state,
            )
        )
        layout.addWidget(self.pdou_show_pass_cb)

        self.pdou_login_btn = QPushButton("Войти через браузер")
        self.pdou_login_btn.setStyleSheet("""
            QPushButton {
                background: #8b5cf6;
                color: white;
                border: none;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #7c3aed;
            }
        """)
        self.pdou_login_btn.clicked.connect(self.on_login_pdou)
        layout.addWidget(self.pdou_login_btn)

        return content

    # --------------------------------------------------------
    # Компактные компоненты интерфейса
    # --------------------------------------------------------

    def _make_collapsible_section(
        self,
        title: str,
        content: QWidget,
        expanded: bool = False,
    ) -> QWidget:
        """Создаёт компактный раскрывающийся блок."""
        toggle_button = QToolButton()
        toggle_button.setText(title)
        toggle_button.setCheckable(True)
        toggle_button.setChecked(expanded)
        toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        toggle_button.setArrowType(
            Qt.ArrowType.DownArrow
            if expanded
            else Qt.ArrowType.RightArrow
        )
        toggle_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        content.setVisible(expanded)

        def toggle_content(checked: bool):
            content.setVisible(checked)
            toggle_button.setArrowType(
                Qt.ArrowType.DownArrow
                if checked
                else Qt.ArrowType.RightArrow
            )

        toggle_button.toggled.connect(toggle_content)

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(2)

        wrapper_layout.addWidget(toggle_button)
        wrapper_layout.addWidget(content)

        return wrapper

    def _make_sep(self) -> QFrame:
        """Создаёт тонкий горизонтальный разделитель."""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(
            "color: #e2e8f0; background: #e2e8f0; max-height: 1px;"
        )
        return separator

    def _toggle_echo(self, line_edit: QLineEdit, state):
        """Показывает или скрывает пароль."""
        if state == Qt.CheckState.Checked.value:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def _load_saved_credentials(self):
        """Подставляет сохранённые учётные данные ЭЖД."""
        credentials = load_credentials()

        if not credentials:
            return

        self.ejd_login_edit.setText(credentials.get("login", ""))
        self.ejd_password_edit.setText(credentials.get("password", ""))

    def append_log(self, message: str):
        """Добавляет сообщение в журнал."""
        self.log_view.appendPlainText(message)

        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # --------------------------------------------------------
    # Обновление статусов
    # --------------------------------------------------------

    def _refresh_statuses(self):
        """Обновляет информацию о файлах и сессиях."""
        ejd_lines = [
            format_file_info(SESSIONS_DIR / filename)
            for filename in EJD_FILES
        ]
        self.ejd_files_label.setText("\n".join(ejd_lines))

        pdou_lines = [
            format_file_info(SESSIONS_DIR / filename)
            for filename in PDOU_FILES
        ]
        self.pdou_files_label.setText("\n".join(pdou_lines))

        if SESSION_FILE.exists() and SESSION_FILE.stat().st_size > 0:
            self.ejd_status_label.setText(
                "Сохранённая сессия найдена. "
                "Нажмите «Войти в ЭЖД» для проверки."
            )
        else:
            self.ejd_status_label.setText(
                "Сохранённой ЭЖД-сессии нет. "
                "Импортируйте её или используйте другой способ входа."
            )

        if PDOU_TOKEN_FILE.exists() or PDOU_COOKIES_FILE.exists():
            self.pdou_status_label.setText(
                "Сохранённые данные ПДОУ найдены."
            )
        else:
            self.pdou_status_label.setText(
                "Сохранённой ПДОУ-сессии нет. "
                "Импортируйте данные для входа."
            )

    # --------------------------------------------------------
    # Автоматическая проверка ЭЖД
    # --------------------------------------------------------

    def _start_session_check(self):
        """Проверяет ЭЖД-сессию при запуске."""
        self.checking_label.setText("Проверяю сохранённую сессию...")

        self.check_worker = SessionCheckWorker()
        self.check_worker.done.connect(self._on_session_checked)
        self.check_worker.start()

    def _on_session_checked(self, result: dict):
        """Обрабатывает автоматическую проверку ЭЖД-сессии."""
        if result.get("ok"):
            self.checking_label.setText(
                "Сохранённая сессия ЭЖД активна.\n"
                "Открываю главное окно..."
            )
            self.checking_label.setStyleSheet(
                "color: #15803d; font-weight: 600; padding: 8px;"
            )

            self.auth = result.get("auth_obj")
            QTimer.singleShot(700, self._open_main_window)
            return

        reason = result.get("reason", "неизвестная причина")

        self.checking_label.setText(
            f"Автоматический вход недоступен: {reason}.\n"
            "Открываю форму входа..."
        )
        self.checking_label.setStyleSheet(
            "color: #64748b; padding: 8px;"
        )

        QTimer.singleShot(450, lambda: self.stack.setCurrentIndex(1))

    # --------------------------------------------------------
    # Открытие главного окна
    # --------------------------------------------------------

    def _open_main_window(self):
        """Открывает основное окно приложения с ЭЖД-авторизацией."""
        try:
            from ui.main_window import MainWindow

            self.main_window = MainWindow()

            if self.auth:
                self.main_window.on_global_auth(self.auth)

            self.main_window.show()
            self.close()

        except Exception as error:
            import traceback

            traceback.print_exc()

            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось открыть главное окно:\n{error}",
            )

    def _open_main_window_pdou(self, payload: dict):
        """Открывает основное окно приложения с ПДОУ-авторизацией."""
        try:
            from ui.main_window import MainWindow

            self.main_window = MainWindow()
            self.main_window.on_global_auth(payload)
            self.main_window.show()
            self.close()

        except Exception as error:
            import traceback

            traceback.print_exc()

            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось открыть главное окно:\n{error}",
            )

    # --------------------------------------------------------
    # ЭЖД: главный вход
    # --------------------------------------------------------

    def on_enter_ejd(self):
        """Проверяет сессию ЭЖД и открывает главное окно."""
        if not SESSION_FILE.exists():
            reply = QMessageBox.question(
                self,
                "Сессия ЭЖД не найдена",
                "Сохранённая сессия ЭЖД не найдена.\n\n"
                "Открыть вход через браузер?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._open_ejd_browser_section()

            return

        self.ejd_enter_btn.setEnabled(False)
        self.ejd_enter_btn.setText("Проверяю сессию...")
        self.append_log("[i] Проверяю ЭЖД-сессию...")

        self.enter_check_worker = SessionCheckWorker()
        self.enter_check_worker.done.connect(self._on_enter_checked)
        self.enter_check_worker.start()

    def _on_enter_checked(self, result: dict):
        """Обрабатывает проверку ЭЖД по кнопке «Войти»."""
        self.ejd_enter_btn.setEnabled(True)
        self.ejd_enter_btn.setText("Войти в ЭЖД")

        if result.get("ok"):
            self.auth = result.get("auth_obj")
            self.append_log("[+] ЭЖД-сессия активна. Открываю главное окно.")
            QTimer.singleShot(200, self._open_main_window)
            return

        reason = result.get("reason", "неизвестная причина")
        self.append_log(f"[!] ЭЖД-сессия недействительна: {reason}")

        reply = QMessageBox.question(
            self,
            "Сессия недействительна",
            "Сохранённая ЭЖД-сессия больше не действует.\n\n"
            f"Причина: {reason}\n\n"
            "Открыть вход через браузер?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._open_ejd_browser_section()

    def _open_ejd_browser_section(self):
        """
        Сообщает пользователю, где находится Selenium-вход.

        Раскрытие соответствующего блока программно не требуется:
        пользователь видит понятную подсказку и может открыть
        «Другие способы входа».
        """
        QMessageBox.information(
            self,
            "Вход через браузер",
            "Откройте раздел «Другие способы входа» в карточке ЭЖД, "
            "введите логин и пароль, затем нажмите "
            "«Войти через браузер».",
        )

    # --------------------------------------------------------
    # ЭЖД: вход по токену
    # --------------------------------------------------------

    def _on_ejd_token_changed(self, text: str):
        """Активирует кнопку, когда токен выглядит достаточно длинным."""
        has_token = bool(text.strip()) and len(text.strip()) > 50

        self.ejd_token_login_btn.setEnabled(has_token)

    def on_ejd_token_paste(self):
        """Вставляет auth_token из буфера обмена."""
        try:
            text = QApplication.clipboard().text().strip()
        except Exception:
            text = ""

        if text:
            self.ejd_token_edit.setText(text)
            self.append_log(
                f"[clipboard] Вставлено символов: {len(text)}"
            )
        else:
            self.append_log("[clipboard] Буфер обмена пуст.")

    def on_login_by_token(self):
        """Запускает проверку и сохранение ЭЖД-токена."""
        token = self.ejd_token_edit.text().strip()

        if not token:
            QMessageBox.warning(
                self,
                "Токен не указан",
                "Введите или вставьте auth_token.",
            )
            return

        if len(token) < 50:
            QMessageBox.warning(
                self,
                "Токен слишком короткий",
                f"Получено символов: {len(token)}.\n"
                "Скопируйте токен полностью.",
            )
            return

        profile_id = self.ejd_profile_id_edit.text().strip()
        school_id = self.ejd_school_id_edit.text().strip()

        self._set_ejd_ui_enabled(False)
        self.append_log("=" * 48)
        self.append_log("[i] Выполняется вход по токену ЭЖД...")

        self.token_login_worker = TokenLoginWorker(
            auth_token=token,
            profile_id=profile_id,
            school_id=school_id,
        )

        self.token_login_worker.log.connect(self.append_log)
        self.token_login_worker.finished_ok.connect(
            self.on_token_login_ok
        )
        self.token_login_worker.finished_err.connect(
            self.on_token_login_err
        )
        self.token_login_worker.start()

    def on_token_login_ok(self, auth):
        """Открывает приложение после успешной авторизации по токену."""
        self.auth = auth
        self._set_ejd_ui_enabled(True)
        self._refresh_statuses()

        self.append_log(
            "[+] Вход по токену завершён. Открываю главное окно."
        )

        QTimer.singleShot(500, self._open_main_window)

    def on_token_login_err(self, error: str):
        """Показывает ошибку входа по токену."""
        self._set_ejd_ui_enabled(True)
        self.append_log(f"[!] Вход по токену: {error}")

        QMessageBox.critical(
            self,
            "Ошибка входа по токену",
            error,
        )

    # --------------------------------------------------------
    # Импорт JSON
    # --------------------------------------------------------

    def on_import_ejd_json(self):
        """Открывает диалог импорта ЭЖД-токенов."""
        try:
            from ui.token_import_dialog import EJDImportDialog
        except Exception as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось открыть импорт ЭЖД:\n{error}",
            )
            return

        dialog = EJDImportDialog(self)
        dialog.tokens_saved.connect(self._on_ejd_imported)
        dialog.exec()

    def _on_ejd_imported(self, payload):
        """Обрабатывает успешный импорт ЭЖД."""
        self.append_log("[+] ЭЖД-сессия импортирована.")
        self._refresh_statuses()

        if hasattr(payload, "session"):
            self.auth = payload
            QTimer.singleShot(200, self._open_main_window)
            return

        QTimer.singleShot(200, self._start_session_check)

    def on_import_pdou_json(self):
        """Открывает диалог импорта ПДОУ-токенов."""
        try:
            from ui.token_import_dialog import PDOUImportDialog
        except Exception as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось открыть импорт ПДОУ:\n{error}",
            )
            return

        dialog = PDOUImportDialog(self)
        dialog.tokens_saved.connect(self._on_pdou_imported)
        dialog.exec()

    def _on_pdou_imported(self, payload: dict):
        """Открывает основное окно после импорта ПДОУ."""
        if not payload or not payload.get("saved"):
            return

        user_name = payload.get("user_name", "") or "неизвестен"

        self.append_log(
            f"[+] ПДОУ-сессия импортирована. Пользователь: {user_name}"
        )
        self._refresh_statuses()

        QTimer.singleShot(
            200,
            lambda: self._open_main_window_pdou(payload),
        )

    # --------------------------------------------------------
    # Импорт ZIP
    # --------------------------------------------------------

    def on_zip_import(self, mode: str = None):
        """
        Импортирует сессии из ZIP.

        mode:
        - None: предложить выбрать ЭЖД / ПДОУ;
        - "ejd": восстановить только ЭЖД;
        - "pdou": восстановить только ПДОУ.
        """
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите ZIP-архив с сессиями",
            str(Path.home()),
            "ZIP archives (*.zip);;Все файлы (*.*)",
        )

        if not zip_path:
            return

        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                names = archive.namelist()
        except Exception as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось открыть архив:\n{error}",
            )
            return

        has_ejd = any(name in EJD_FILES for name in names)
        has_pdou = any(name in PDOU_FILES for name in names)

        if not has_ejd and not has_pdou:
            QMessageBox.warning(
                self,
                "Нет данных",
                "В архиве не найдены файлы сессий zavuch 2.",
            )
            return

        if mode == "ejd":
            if not has_ejd:
                QMessageBox.warning(
                    self,
                    "Нет ЭЖД-сессии",
                    "В архиве нет файлов ЭЖД-сессии.",
                )
                return

            import_ejd = True
            import_pdou = False

        elif mode == "pdou":
            if not has_pdou:
                QMessageBox.warning(
                    self,
                    "Нет ПДОУ-сессии",
                    "В архиве нет файлов ПДОУ-сессии.",
                )
                return

            import_ejd = False
            import_pdou = True

        else:
            import_ejd, import_pdou = self._ask_import_choice(
                has_ejd,
                has_pdou,
            )

        if not import_ejd and not import_pdou:
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение импорта",
            "Существующие файлы сессий будут перезаписаны.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.zip_worker = ZipImportWorker(
            zip_path,
            import_ejd,
            import_pdou,
        )
        self.zip_worker.done.connect(self._on_zip_import_finished)
        self.zip_worker.start()

    def _ask_import_choice(self, has_ejd: bool, has_pdou: bool):
        """Показывает выбор данных для восстановления из ZIP."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Импорт сессий")
        dialog.setMinimumWidth(360)

        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel("Выберите данные, которые нужно восстановить:")
        )

        ejd_checkbox = QCheckBox("ЭЖД-сессия")
        ejd_checkbox.setChecked(has_ejd)
        ejd_checkbox.setEnabled(has_ejd)

        if not has_ejd:
            ejd_checkbox.setText("ЭЖД-сессия — отсутствует в архиве")

        layout.addWidget(ejd_checkbox)

        pdou_checkbox = QCheckBox("ПДОУ-сессия")
        pdou_checkbox.setChecked(has_pdou)
        pdou_checkbox.setEnabled(has_pdou)

        if not has_pdou:
            pdou_checkbox.setText("ПДОУ-сессия — отсутствует в архиве")

        layout.addWidget(pdou_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False, False

        return ejd_checkbox.isChecked(), pdou_checkbox.isChecked()

    def _on_zip_import_finished(self, result: dict):
        """Показывает результат ZIP-импорта."""
        self._refresh_statuses()

        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "Импорт не выполнен",
                result.get("reason", "Неизвестная ошибка."),
            )
            return

        restored = "\n".join(
            f"• {filename}"
            for filename in result.get("restored", [])
        )

        QMessageBox.information(
            self,
            "Импорт завершён",
            f"Восстановлено файлов: {len(result['restored'])}\n\n"
            f"{restored}",
        )

        self.append_log(f"[+] Импортированы файлы:\n{restored}")

        if result.get("ejud") or "session.pkl" in result.get("restored", []):
            self.append_log("[i] Проверяю импортированную ЭЖД-сессию...")
            self._start_session_check()

    # --------------------------------------------------------
    # Импорт отдельных файлов
    # --------------------------------------------------------

    def on_load_ejd_pkl(self):
        """Импортирует отдельный session.pkl."""
        pkl_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите session.pkl",
            str(Path.home()),
            "Pickle session files (*.pkl);;Все файлы (*.*)",
        )

        if not pkl_path:
            return

        try:
            shutil.copy2(pkl_path, SESSION_FILE)
        except Exception as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось скопировать session.pkl:\n{error}",
            )
            return

        adjacent_auth_data = Path(pkl_path).parent / "auth_data.json"

        if adjacent_auth_data.exists():
            reply = QMessageBox.question(
                self,
                "Найден auth_data.json",
                f"Рядом с session.pkl найден файл:\n"
                f"{adjacent_auth_data}\n\n"
                "Скопировать его тоже?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                try:
                    shutil.copy2(adjacent_auth_data, AUTH_DATA_FILE)
                except Exception as error:
                    QMessageBox.warning(
                        self,
                        "Не удалось скопировать auth_data.json",
                        str(error),
                    )

        self._refresh_statuses()

        QMessageBox.information(
            self,
            "Импорт выполнен",
            "Файл session.pkl импортирован.\n\n"
            "Проверяю сессию...",
        )

        self.append_log(f"[+] Импортирован session.pkl: {pkl_path}")
        self._start_session_check()

    def on_load_pdou_json(self):
        """Импортирует отдельный pdou_token.json."""
        token_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите pdou_token.json",
            str(Path.home()),
            "JSON files (*.json);;Все файлы (*.*)",
        )

        if not token_path:
            return

        try:
            shutil.copy2(token_path, PDOU_TOKEN_FILE)
        except Exception as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось скопировать pdou_token.json:\n{error}",
            )
            return

        candidates = [
            Path(token_path).parent / "pdou_cookies.json",
            Path.home() / "Downloads" / "pdou_cookies.json",
        ]

        cookies_source = None

        for candidate in candidates:
            if candidate.exists():
                cookies_source = candidate
                break

        if cookies_source:
            reply = QMessageBox.question(
                self,
                "Найден pdou_cookies.json",
                f"Найден файл:\n{cookies_source}\n\n"
                "Скопировать его?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                try:
                    shutil.copy2(cookies_source, PDOU_COOKIES_FILE)
                except Exception as error:
                    QMessageBox.warning(
                        self,
                        "Не удалось скопировать pdou_cookies.json",
                        str(error),
                    )

        self._refresh_statuses()

        QMessageBox.information(
            self,
            "Импорт выполнен",
            "ПДОУ-сессия импортирована.",
        )

        self.append_log(
            f"[+] Импортирован pdou_token.json: {token_path}"
        )

    # --------------------------------------------------------
    # Вход через Selenium
    # --------------------------------------------------------

    def on_login_ejd(self):
        """Запускает Selenium-вход в ЭЖД."""
        login = self.ejd_login_edit.text().strip()
        password = self.ejd_password_edit.text()

        if not login or not password:
            QMessageBox.warning(
                self,
                "Не заполнены данные",
                "Введите логин и пароль ЭЖД.",
            )
            return

        if self.ejd_remember_cb.isChecked():
            save_credentials(login, password, "")

        self._set_ejd_ui_enabled(False)
        self.append_log("[i] Запуск браузера для входа в ЭЖД...")

        self.ejd_auth_worker = AuthWorker(
            login,
            password,
            None,
            pdou_mode=False,
        )
        self.ejd_auth_worker.log.connect(self.append_log)
        self.ejd_auth_worker.cookies_ready.connect(
            self.on_cookies_ready
        )
        self.ejd_auth_worker.finished_ok.connect(
            self.on_ejd_login_ok
        )
        self.ejd_auth_worker.finished_err.connect(
            self.on_ejd_login_err
        )
        self.ejd_auth_worker.start()

    def on_login_pdou(self):
        """Запускает резервный Selenium-вход в ПДОУ."""
        login = self.pdou_login_edit.text().strip()
        password = self.pdou_password_edit.text()
        totp_key = self.pdou_totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(
                self,
                "Не заполнены данные",
                "Введите логин и пароль учётной записи ПДОУ.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Вход ПДОУ через браузер",
            "Будет запущен браузер и сохранена ПДОУ-сессия.\n\n"
            "Это резервный способ. Основной способ — импорт "
            "готовой ПДОУ-сессии.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_pdou_ui_enabled(False)
        self.append_log(
            "[i] Запуск браузера для входа в ПДОУ..."
        )

        self.pdou_auth_worker = AuthWorker(
            login,
            password,
            totp_key,
            pdou_mode=True,
        )
        self.pdou_auth_worker.log.connect(self.append_log)
        self.pdou_auth_worker.cookies_ready.connect(
            self.on_cookies_ready
        )
        self.pdou_auth_worker.finished_ok.connect(
            self.on_pdou_login_ok
        )
        self.pdou_auth_worker.finished_err.connect(
            self.on_pdou_login_err
        )
        self.pdou_auth_worker.start()

    def on_cookies_ready(self):
        """Спрашивает, нужно ли закрыть браузер после получения cookies."""
        message = QMessageBox(self)
        message.setWindowTitle("Сессия получена")
        message.setText("Данные сессии успешно сохранены.")
        message.setInformativeText(
            "Нажмите «Оставить браузер», чтобы не закрывать окно браузера, "
            "или «Закрыть браузер», чтобы завершить его работу."
        )
        message.setIcon(QMessageBox.Icon.Information)

        keep_open_button = message.addButton(
            "Оставить браузер",
            QMessageBox.ButtonRole.AcceptRole,
        )
        close_button = message.addButton(
            "Закрыть браузер",
            QMessageBox.ButtonRole.DestructiveRole,
        )

        message.setDefaultButton(keep_open_button)
        message.exec()

        clicked = message.clickedButton()
        worker = self.ejd_auth_worker or self.pdou_auth_worker

        if worker is None:
            return

        if clicked == close_button:
            worker._close_browser_event.set()
        else:
            worker._detach_browser_event.set()

    def on_ejd_login_ok(self, auth):
        """Открывает основное окно после Selenium-входа в ЭЖД."""
        self.auth = auth
        self._set_ejd_ui_enabled(True)
        self._refresh_statuses()

        self.append_log("[+] ЭЖД: вход выполнен. Открываю главное окно.")
        QTimer.singleShot(500, self._open_main_window)

    def on_ejd_login_err(self, error: str):
        """Показывает ошибку Selenium-входа в ЭЖД."""
        self._set_ejd_ui_enabled(True)
        self.append_log(f"[!] ЭЖД: {error}")

        QMessageBox.critical(
            self,
            "Ошибка входа в ЭЖД",
            error,
        )

    def on_pdou_login_ok(self, auth):
        """Открывает основное окно после Selenium-входа в ПДОУ."""
        self._set_pdou_ui_enabled(True)
        self._refresh_statuses()

        self.append_log("[+] ПДОУ: вход выполнен, токен сохранён.")

        data = load_pdou_token()
        user_name = data.get("user_name", "") or "неизвестен"
        roles = data.get("user_roles", []) or []

        QMessageBox.information(
            self,
            "ПДОУ-сессия сохранена",
            f"Пользователь: {user_name}",
        )

        payload = {
            "user_name": user_name,
            "roles": roles,
            "saved": True,
        }

        QTimer.singleShot(
            500,
            lambda: self._open_main_window_pdou(payload),
        )

    def on_pdou_login_err(self, error: str):
        """Показывает ошибку Selenium-входа в ПДОУ."""
        self._set_pdou_ui_enabled(True)
        self.append_log(f"[!] ПДОУ: {error}")

        QMessageBox.critical(
            self,
            "Ошибка входа в ПДОУ",
            error,
        )

    # --------------------------------------------------------
    # Очистка данных
    # --------------------------------------------------------

    def on_clear_ejd(self):
        """Удаляет данные ЭЖД-сессии."""
        reply = QMessageBox.question(
            self,
            "Очистить ЭЖД-сессию?",
            "Будут удалены файлы session.pkl, auth_data.json "
            "и credentials.json.\n\nПродолжить?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        for filename in EJD_FILES:
            try:
                (SESSIONS_DIR / filename).unlink(missing_ok=True)
            except Exception:
                pass

        self.ejd_login_edit.clear()
        self.ejd_password_edit.clear()
        self.ejd_token_edit.clear()
        self.ejd_profile_id_edit.clear()
        self.ejd_school_id_edit.clear()

        self._refresh_statuses()
        self.append_log("[i] ЭЖД-сессия очищена.")

    def on_clear_pdou(self):
        """Удаляет данные ПДОУ-сессии."""
        reply = QMessageBox.question(
            self,
            "Очистить ПДОУ-сессию?",
            "Будут удалены pdou_token.json и pdou_cookies.json.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        for filename in PDOU_FILES:
            try:
                (SESSIONS_DIR / filename).unlink(missing_ok=True)
            except Exception:
                pass

        self.pdou_login_edit.clear()
        self.pdou_password_edit.clear()
        self.pdou_totp_edit.clear()

        self._refresh_statuses()
        self.append_log("[i] ПДОУ-сессия очищена.")

    def on_clear_all(self):
        """Удаляет все сохранённые сессии."""
        reply = QMessageBox.question(
            self,
            "Очистить все данные?",
            "Будут удалены все сохранённые сессии ЭЖД и ПДОУ.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        for filename in EJD_FILES + PDOU_FILES:
            try:
                (SESSIONS_DIR / filename).unlink(missing_ok=True)
            except Exception:
                pass

        self.ejd_login_edit.clear()
        self.ejd_password_edit.clear()
        self.ejd_token_edit.clear()
        self.ejd_profile_id_edit.clear()
        self.ejd_school_id_edit.clear()

        self.pdou_login_edit.clear()
        self.pdou_password_edit.clear()
        self.pdou_totp_edit.clear()

        self._refresh_statuses()
        self.append_log("[i] Все сохранённые сессии очищены.")

    # --------------------------------------------------------
    # Блокировка интерфейса
    # --------------------------------------------------------

    def _set_ejd_ui_enabled(self, enabled: bool):
        """Включает или отключает ЭЖД-элементы на время операции."""
        self.ejd_enter_btn.setEnabled(enabled)

        self.ejd_token_login_btn.setEnabled(
            enabled
            and len(self.ejd_token_edit.text().strip()) > 50
        )

        self.ejd_import_btn.setEnabled(enabled)
        self.ejd_login_btn.setEnabled(enabled)
        self.ejd_load_pkl_btn.setEnabled(enabled)
        self.ejd_load_zip_btn.setEnabled(enabled)
        self.ejd_clear_btn.setEnabled(enabled)
        self.ejd_token_paste_btn.setEnabled(enabled)

        self.ejd_login_edit.setEnabled(enabled)
        self.ejd_password_edit.setEnabled(enabled)
        self.ejd_token_edit.setEnabled(enabled)
        self.ejd_profile_id_edit.setEnabled(enabled)
        self.ejd_school_id_edit.setEnabled(enabled)

    def _set_pdou_ui_enabled(self, enabled: bool):
        """Включает или отключает ПДОУ-элементы на время операции."""
        self.pdou_import_btn.setEnabled(enabled)
        self.pdou_login_btn.setEnabled(enabled)
        self.pdou_load_json_btn.setEnabled(enabled)
        self.pdou_load_zip_btn.setEnabled(enabled)
        self.pdou_clear_btn.setEnabled(enabled)

        self.pdou_login_edit.setEnabled(enabled)
        self.pdou_password_edit.setEnabled(enabled)
        self.pdou_totp_edit.setEnabled(enabled)