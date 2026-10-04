# -*- coding: utf-8 -*-
"""
Окно авторизации. Открывается при старте приложения.

Две симметричные колонки:
  • Слева — ЭЖД (журналы): session.pkl + импорт JSON + Selenium + вход по токену.
  • Справа — ПДОУ (кружки): pdou_session.json + Selenium.

Все сессии хранятся в <папка проекта>/sessions/ (см. paths.py).
"""
import json
import pickle
import shutil
import sys
import threading
import time
import zipfile
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

import requests
from urllib.parse import urljoin

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QPlainTextEdit, QMessageBox, QFrame,
    QStackedWidget, QFileDialog, QGroupBox
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
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump({"login": login, "password": password,
                       "totp_key": totp_key or ""},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_pdou_token() -> dict:
    if not PDOU_TOKEN_FILE.exists():
        return {}
    try:
        with open(PDOU_TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def format_file_info(fpath: Path) -> str:
    if fpath.exists():
        mtime = time.strftime("%d.%m.%Y %H:%M",
                              time.localtime(fpath.stat().st_mtime))
        size = fpath.stat().st_size
        return f"✅ {fpath.name} ({size} Б, {mtime})"
    return f"❌ {fpath.name}"


def _build_cookie(name, value, domain):
    return Cookie(
        version=0, name=name, value=str(value),
        port=None, port_specified=False,
        domain=domain, domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/", path_specified=True,
        secure=False, expires=None, discard=False,
        comment=None, comment_url=None,
        rest={}, rfc2109=False,
    )


# ============================================================
#  Проверка ЭЖД-сессии
# ============================================================
def check_saved_session() -> dict:
    result = {"ok": False, "reason": "", "auth_obj": None}
    if not SESSION_FILE.exists():
        result["reason"] = "session.pkl не найден"
        return result
    try:
        if SESSION_FILE.stat().st_size == 0:
            result["reason"] = "session.pkl пустой (0 байт)"
            return result
    except Exception:
        pass
    try:
        from auth import dn_Auth
        auth = dn_Auth()
        if auth.load_session():
            result["ok"] = True
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


class TokenLoginWorker(QThread):
    """
    Проверяет auth_token/aupd_token из строки и сохраняет сессию.
    Используется кнопкой «🔑 Войти по токену» в колонке ЭЖД.
    """
    log = Signal(str)
    finished_ok = Signal(object)   # dn_Auth
    finished_err = Signal(str)

    def __init__(self, auth_token: str, profile_id: str = "",
                 school_id: str = ""):
        super().__init__()
        self.auth_token = auth_token.strip()
        self.profile_id = str(profile_id or "").strip()
        self.school_id = str(school_id or "").strip()

    def _log(self, msg):
        print(msg, flush=True)
        self.log.emit(msg)

    def run(self):
        try:
            if not self.auth_token:
                self.finished_err.emit("Токен пустой")
                return
            if len(self.auth_token) < 50:
                self.finished_err.emit(
                    f"Токен слишком короткий ({len(self.auth_token)} симв.)"
                )
                return

            self._log(f"[i] Длина токена: {len(self.auth_token)} симв.")
            self._log("[i] Проверяю через dnevnik.mos.ru/core/api/schools...")

            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/152.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Auth-Token": self.auth_token,
                "Authorization": f"Bearer {self.auth_token}",
            })
            if self.profile_id:
                session.headers["Profile-Id"] = self.profile_id

            # Кладём токен в cookies
            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                session.cookies.set("auth_token", self.auth_token,
                                     domain=domain)
            if self.profile_id:
                session.cookies.set("profile_id", self.profile_id,
                                     domain="dnevnik.mos.ru")

            try:
                r = session.get("https://dnevnik.mos.ru/core/api/schools",
                                 timeout=15)
            except Exception as e:
                self.finished_err.emit(f"Ошибка сети: {e}")
                return

            self._log(f"[i] HTTP {r.status_code}")
            if r.status_code != 200:
                self.finished_err.emit(
                    f"HTTP {r.status_code}: {r.text[:200]}"
                )
                return

            try:
                data = r.json()
            except Exception:
                self.finished_err.emit("Ответ не JSON")
                return

            if not data:
                self.finished_err.emit("Пустой ответ API")
                return

            school_name = data[0].get("name", "?")
            sid = str(data[0].get("id", "") or self.school_id or "")
            self._log(f"[+] Токен принят. Школа: {school_name}")

            # Сохраняем session.pkl + auth_data.json
            # Сохраняем session.pkl + auth_data.json
            cookies_list = []
            for c in session.cookies:
                cookies_list.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                    "secure": bool(c.secure),
                    "expires": c.expires,
                })

            with open(SESSION_FILE, "wb") as f:
                pickle.dump(cookies_list, f)

            with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "auth_token": self.auth_token,
                    "aupd_token": self.auth_token,
                    "profile_id": self.profile_id,
                    "school_id": sid,
                }, f, ensure_ascii=False, indent=2)

            self._log(f"[+] Сохранено: {SESSION_FILE}")
            self._log(f"[+] Сохранено: {AUTH_DATA_FILE}")

            # Пробуем загрузить через dn_Auth, чтобы отдать объект
            try:
                from auth import dn_Auth
                auth = dn_Auth()
                if auth.load_session():
                    self._log("[+] Сессия активна (проверено через dn_Auth)")
                    self.finished_ok.emit(auth)
                    return
            except Exception as e:
                self._log(f"[!] dn_Auth.load_session: {e}")

            # Если не удалось через dn_Auth — всё равно эмитим
            # хотя бы чтобы открылось главное окно
            self.finished_err.emit(
                "Токен принят API, но dn_Auth.load_session() не смог "
                "восстановить сессию. Проверьте auth_data.json."
            )

        except Exception as e:
            import traceback
            self._log(f"[!] Исключение: {e}")
            self._log(traceback.format_exc())
            self.finished_err.emit(f"Ошибка: {e}")


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


class ZipImportWorker(QThread):
    done = Signal(dict)

    def __init__(self, zip_path: str, import_ejd: bool, import_pdou: bool):
        super().__init__()
        self.zip_path = zip_path
        self.import_ejd = import_ejd
        self.import_pdou = import_pdou

    def run(self):
        result = {"ok": False, "restored": [], "reason": "",
                  "ejud": False, "pdou": False}
        try:
            with zipfile.ZipFile(self.zip_path, "r") as zf:
                names = zf.namelist()

                has_ejd = any(n in EJD_FILES for n in names)
                has_pdou = any(n in PDOU_FILES for n in names)
                result["ejud"] = has_ejd
                result["pdou"] = has_pdou

                to_restore = []
                if self.import_ejd:
                    to_restore.extend(EJD_FILES)
                if self.import_pdou:
                    to_restore.extend(PDOU_FILES)

                for fname in to_restore:
                    if fname in names:
                        target = SESSIONS_DIR / fname
                        with zf.open(fname) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        result["restored"].append(fname)

            result["ok"] = bool(result["restored"])
            if not result["ok"]:
                result["reason"] = "В архиве не найдено нужных файлов."
        except Exception as e:
            result["reason"] = f"Ошибка: {e}"

        self.done.emit(result)


# ============================================================
#  Окно авторизации
# ============================================================
class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("zavuch 2 — Вход")
        self.setMinimumSize(1150, 820)

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
        title = QLabel("zavuch 2")
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

        # === СЛУЖЕБНЫЕ КНОПКИ ===
        service_row = QHBoxLayout()
        service_row.setSpacing(8)
        service_row.addStretch()

        self.zip_import_btn = QPushButton("📥 Импорт сессий из архива (.zip)")
        self.zip_import_btn.setMinimumHeight(32)
        self.zip_import_btn.setStyleSheet("""
            QPushButton { background-color: #059669; color: white;
                font-weight: bold; border-radius: 6px; padding: 0 16px; }
            QPushButton:hover { background-color: #047857; }
        """)
        self.zip_import_btn.clicked.connect(self.on_zip_import)
        service_row.addWidget(self.zip_import_btn)

        self.refresh_btn = QPushButton("🔄 Обновить статусы")
        self.refresh_btn.setMinimumHeight(32)
        self.refresh_btn.clicked.connect(self._refresh_statuses)
        service_row.addWidget(self.refresh_btn)

        self.clear_all_btn = QPushButton("🗑 Очистить все данные")
        self.clear_all_btn.setMinimumHeight(32)
        self.clear_all_btn.setStyleSheet("""
            QPushButton { background-color: #dc2626; color: white;
                font-weight: bold; border-radius: 6px; padding: 0 16px; }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.clear_all_btn.clicked.connect(self.on_clear_all)
        service_row.addWidget(self.clear_all_btn)

        service_row.addStretch()
        main_layout.addLayout(service_row)

        # === ОБЩИЙ ЖУРНАЛ ===
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
        self.log_view.setMinimumHeight(120)
        self.log_view.setMaximumHeight(180)
        log_layout.addWidget(self.log_view)

        main_layout.addWidget(log_group)

        return w

    # ------------------------------------------------------------------
    #  Левая колонка — ЭЖД
    # ------------------------------------------------------------------
    def _build_ejd_column(self) -> QWidget:
        group = QGroupBox("🔐  ЭЖД — журналы и итоги")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 13pt;
                border: 2px solid #2563eb; border-radius: 10px;
                margin-top: 1ex; padding-top: 18px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px;
                padding: 0 8px 0 8px; color: #2563eb;
            }
        """)
        col = QVBoxLayout(group)
        col.setSpacing(8)
        col.setContentsMargins(14, 18, 14, 14)

        # === Статус ===
        self.ejd_status_label = QLabel("⏳ Проверяю...")
        self.ejd_status_label.setWordWrap(True)
        self.ejd_status_label.setStyleSheet("""
            color: #1e3a8a; font-weight: bold; font-size: 10pt;
            background-color: #eff6ff; padding: 8px;
            border-radius: 6px;
        """)
        col.addWidget(self.ejd_status_label)

        # === Список файлов ===
        self.ejd_files_label = QLabel()
        self.ejd_files_label.setWordWrap(True)
        self.ejd_files_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 8pt; color: #475569;"
        )
        col.addWidget(self.ejd_files_label)

        col.addWidget(self._make_sep())

        # === ГЛАВНАЯ КНОПКА: ВОЙТИ В ЭЖД ===
        self.ejd_enter_btn = QPushButton("🔓  Войти в ЭЖД")
        self.ejd_enter_btn.setMinimumHeight(52)
        self.ejd_enter_btn.setStyleSheet("""
            QPushButton {
                background-color: #16a34a; color: white;
                font-size: 13pt; font-weight: bold; border-radius: 10px;
            }
            QPushButton:hover { background-color: #15803d; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.ejd_enter_btn.clicked.connect(self.on_enter_ejd)
        col.addWidget(self.ejd_enter_btn)

        col.addWidget(self._make_sep())

        # ============================================================
        #  ВХОД ПО ТОКЕНУ — новая кнопка + поле
        # ============================================================
        col.addWidget(QLabel("<b>🔑 Вход по токену (auth_token):</b>"))

        self.ejd_token_edit = QLineEdit()
        self.ejd_token_edit.setPlaceholderText(
            "Вставьте auth_token (JWT) — длинная строка"
        )
        self.ejd_token_edit.setMinimumHeight(34)
        self.ejd_token_edit.textChanged.connect(self._on_ejd_token_changed)
        col.addWidget(self.ejd_token_edit)

        # Дополнительные необязательные поля
        extra_row = QHBoxLayout()
        extra_row.setSpacing(4)

        extra_row.addWidget(QLabel("profile_id:"))
        self.ejd_profile_id_edit = QLineEdit()
        self.ejd_profile_id_edit.setPlaceholderText("необязательно")
        self.ejd_profile_id_edit.setMinimumHeight(30)
        self.ejd_profile_id_edit.setMaximumWidth(140)
        extra_row.addWidget(self.ejd_profile_id_edit)

        extra_row.addWidget(QLabel("school_id:"))
        self.ejd_school_id_edit = QLineEdit()
        self.ejd_school_id_edit.setPlaceholderText("необязательно")
        self.ejd_school_id_edit.setMinimumHeight(30)
        self.ejd_school_id_edit.setMaximumWidth(100)
        extra_row.addWidget(self.ejd_school_id_edit)

        extra_row.addStretch()
        col.addLayout(extra_row)

        # Кнопки под полем
        token_btn_row = QHBoxLayout()
        token_btn_row.setSpacing(4)

        self.ejd_token_paste_btn = QPushButton("📋 Из буфера")
        self.ejd_token_paste_btn.setMinimumHeight(32)
        self.ejd_token_paste_btn.setMaximumWidth(140)
        self.ejd_token_paste_btn.clicked.connect(self.on_ejd_token_paste)
        token_btn_row.addWidget(self.ejd_token_paste_btn)

        self.ejd_token_login_btn = QPushButton("🔑 Войти по токену")
        self.ejd_token_login_btn.setMinimumHeight(36)
        self.ejd_token_login_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9; color: white;
                font-size: 11pt; font-weight: bold; border-radius: 6px;
            }
            QPushButton:hover { background-color: #0284c7; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.ejd_token_login_btn.clicked.connect(self.on_login_by_token)
        token_btn_row.addWidget(self.ejd_token_login_btn, 1)

        col.addLayout(token_btn_row)

        col.addWidget(self._make_sep())

        # === Импорт JSON / файлов ===
        col.addWidget(QLabel("<b>Импорт ЭЖД-сессии:</b>"))

        row_import = QHBoxLayout()
        row_import.setSpacing(4)

        self.ejd_import_btn = QPushButton("📋 Импорт ЭЖД")
        self.ejd_import_btn.setMinimumHeight(34)
        self.ejd_import_btn.setToolTip(
            "Открывает диалог импорта ЭЖД-сессии:\n"
            "• вставить JSON из буфера\n"
            "• либо выбрать файл auth_data.json / ejd_session.json"
        )
        self.ejd_import_btn.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: white;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.ejd_import_btn.clicked.connect(self.on_import_ejd_json)
        row_import.addWidget(self.ejd_import_btn)

        self.ejd_load_pkl_btn = QPushButton("📁 sessions")
        self.ejd_load_pkl_btn.setMinimumHeight(34)
        self.ejd_load_pkl_btn.setToolTip("Импортировать готовый session.pkl")
        self.ejd_load_pkl_btn.clicked.connect(self.on_load_ejd_pkl)
        row_import.addWidget(self.ejd_load_pkl_btn)

        self.ejd_load_zip_btn = QPushButton("📦 ZIP")
        self.ejd_load_zip_btn.setMinimumHeight(34)
        self.ejd_load_zip_btn.setToolTip("Импортировать сессию из .zip архива")
        self.ejd_load_zip_btn.clicked.connect(lambda: self.on_zip_import("ejd"))
        row_import.addWidget(self.ejd_load_zip_btn)

        col.addLayout(row_import)

        col.addWidget(self._make_sep())

        # === Selenium-логин ===
        col.addWidget(QLabel("<b>Или войти через браузер:</b>"))

        col.addWidget(QLabel("Логин:"))
        self.ejd_login_edit = QLineEdit()
        self.ejd_login_edit.setPlaceholderText("Телефон / email / СНИЛС")
        self.ejd_login_edit.setMinimumHeight(32)
        col.addWidget(self.ejd_login_edit)

        col.addWidget(QLabel("Пароль:"))
        self.ejd_password_edit = QLineEdit()
        self.ejd_password_edit.setPlaceholderText("Пароль")
        self.ejd_password_edit.setEchoMode(QLineEdit.Password)
        self.ejd_password_edit.setMinimumHeight(32)
        col.addWidget(self.ejd_password_edit)

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

        col.addStretch()

        # === Кнопки внизу ===
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        self.ejd_login_btn = QPushButton("🌐 Войти через браузер")
        self.ejd_login_btn.setMinimumHeight(36)
        self.ejd_login_btn.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: white;
                font-size: 10pt; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.ejd_login_btn.clicked.connect(self.on_login_ejd)
        bottom_row.addWidget(self.ejd_login_btn, 1)

        self.ejd_clear_btn = QPushButton("🗑 Очистить")
        self.ejd_clear_btn.setMinimumHeight(36)
        self.ejd_clear_btn.setStyleSheet("""
            QPushButton { background-color: #fee2e2; color: #b91c1c;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #fecaca; }
        """)
        self.ejd_clear_btn.clicked.connect(self.on_clear_ejd)
        bottom_row.addWidget(self.ejd_clear_btn, 1)

        col.addLayout(bottom_row)

        return group

    # ------------------------------------------------------------------
    #  Правая колонка — ПДОУ
    # ------------------------------------------------------------------
    def _build_pdou_column(self) -> QWidget:
        group = QGroupBox("🎨  ПДОУ — кружки и заявления")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 13pt;
                border: 2px solid #8b5cf6; border-radius: 10px;
                margin-top: 1ex; padding-top: 18px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px;
                padding: 0 8px 0 8px; color: #8b5cf6;
            }
        """)
        col = QVBoxLayout(group)
        col.setSpacing(8)
        col.setContentsMargins(14, 18, 14, 14)

        # === Статус ===
        self.pdou_status_label = QLabel("⏳ Проверяю...")
        self.pdou_status_label.setWordWrap(True)
        self.pdou_status_label.setStyleSheet("""
            color: #5b21b6; font-weight: bold; font-size: 10pt;
            background-color: #f5f3ff; padding: 8px;
            border-radius: 6px;
        """)
        col.addWidget(self.pdou_status_label)

        self.pdou_files_label = QLabel()
        self.pdou_files_label.setWordWrap(True)
        self.pdou_files_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 8pt; color: #475569;"
        )
        col.addWidget(self.pdou_files_label)

        col.addWidget(self._make_sep())

        # === ГЛАВНАЯ КНОПКА: ИМПОРТ ПДОУ ===
        self.pdou_import_btn = QPushButton(
            "📋 Импорт ПДОУ-сессии (JSON / файл)"
        )
        self.pdou_import_btn.setMinimumHeight(44)
        self.pdou_import_btn.setToolTip(
            "Открывает диалог импорта ПДОУ-сессии:\n"
            "• вставить JSON из буфера (скрипт на esz.mos.ru)\n"
            "• либо выбрать файл pdou_session.json"
        )
        self.pdou_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6; color: white;
                font-size: 11pt; font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #7c3aed; }
        """)
        self.pdou_import_btn.clicked.connect(self.on_import_pdou_json)
        col.addWidget(self.pdou_import_btn)

        col.addWidget(self._make_sep())

        col.addWidget(QLabel("<b>Или подгрузить отдельный файл:</b>"))

        row1 = QHBoxLayout()
        row1.setSpacing(4)

        self.pdou_load_json_btn = QPushButton("📁 Файл pdou_token.json")
        self.pdou_load_json_btn.setMinimumHeight(30)
        self.pdou_load_json_btn.clicked.connect(self.on_load_pdou_json)
        row1.addWidget(self.pdou_load_json_btn)

        self.pdou_load_zip_btn = QPushButton("📦 Архив .zip")
        self.pdou_load_zip_btn.setMinimumHeight(30)
        self.pdou_load_zip_btn.clicked.connect(lambda: self.on_zip_import("pdou"))
        row1.addWidget(self.pdou_load_zip_btn)

        col.addLayout(row1)

        col.addWidget(self._make_sep())

        # === Selenium-логин (резерв) ===
        col.addWidget(QLabel("<b>Или войти через браузер (резерв):</b>"))

        col.addWidget(QLabel("Логин:"))
        self.pdou_login_edit = QLineEdit()
        self.pdou_login_edit.setPlaceholderText("Логин учётки с доступом к ПДОУ")
        self.pdou_login_edit.setMinimumHeight(32)
        col.addWidget(self.pdou_login_edit)

        col.addWidget(QLabel("Пароль:"))
        self.pdou_password_edit = QLineEdit()
        self.pdou_password_edit.setPlaceholderText("Пароль")
        self.pdou_password_edit.setEchoMode(QLineEdit.Password)
        self.pdou_password_edit.setMinimumHeight(32)
        col.addWidget(self.pdou_password_edit)

        col.addWidget(QLabel("TOTP-ключ (если есть):"))
        self.pdou_totp_edit = QLineEdit()
        self.pdou_totp_edit.setPlaceholderText("Base32, можно пусто")
        self.pdou_totp_edit.setMinimumHeight(32)
        col.addWidget(self.pdou_totp_edit)

        self.pdou_show_pass_cb = QCheckBox("Показывать пароль")
        self.pdou_show_pass_cb.stateChanged.connect(
            lambda s: self._toggle_echo(self.pdou_password_edit, s)
        )
        col.addWidget(self.pdou_show_pass_cb)

        self.pdou_login_btn = QPushButton("🎨 Войти как ПДОУ через браузер")
        self.pdou_login_btn.setMinimumHeight(40)
        self.pdou_login_btn.setStyleSheet("""
            QPushButton { background-color: #8b5cf6; color: white;
                font-size: 11pt; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #7c3aed; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.pdou_login_btn.clicked.connect(self.on_login_pdou)
        col.addWidget(self.pdou_login_btn)

        col.addStretch()

        self.pdou_clear_btn = QPushButton("🗑 Очистить ПДОУ-сессию")
        self.pdou_clear_btn.setMinimumHeight(26)
        self.pdou_clear_btn.setStyleSheet("""
            QPushButton { background-color: #f3e8ff; color: #6b21a8;
                font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #e9d5ff; }
        """)
        self.pdou_clear_btn.clicked.connect(self.on_clear_pdou)
        col.addWidget(self.pdou_clear_btn)

        return group

    # ------------------------------------------------------------------
    def _make_sep(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0; margin: 4px 0;")
        return sep

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

    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ==================================================================
    #  СТАТУСЫ
    # ==================================================================
    def _refresh_statuses(self):
        lines = []
        for fname in EJD_FILES:
            lines.append(format_file_info(SESSIONS_DIR / fname))
        self.ejd_files_label.setText("\n".join(lines))

        lines = []
        for fname in PDOU_FILES:
            lines.append(format_file_info(SESSIONS_DIR / fname))
        self.pdou_files_label.setText("\n".join(lines))

    # ==================================================================
    #  АВТОПРОВЕРКА ЭЖД-СЕССИИ
    # ==================================================================
    def _start_session_check(self):
        self.checking_label.setText("Проверяю сохранённую сессию...")
        self.check_worker = SessionCheckWorker()
        self.check_worker.done.connect(self._on_session_checked)
        self.check_worker.start()

    def _on_session_checked(self, result: dict):
        if result.get("ok"):
            self.checking_label.setText(
                "✅ Найдена живая сессия ЭЖД.\nОткрываю главное окно..."
            )
            self.checking_label.setStyleSheet(
                "color: green; font-weight: bold; padding: 8px;"
            )
            self.auth = result.get("auth_obj")
            QTimer.singleShot(700, self._open_main_window)
        else:
            reason = result.get("reason", "неизвестно")
            self.checking_label.setText(
                f"Сессия ЭЖД не найдена ({reason}).\nПереход к форме входа..."
            )
            self.checking_label.setStyleSheet("color: #666; padding: 8px;")
            QTimer.singleShot(500, lambda: self.stack.setCurrentIndex(1))

    # ==================================================================
    #  ОТКРЫТИЕ MAINWINDOW
    # ==================================================================
    def _open_main_window(self):
        try:
            from ui.main_window import MainWindow
            self.main_window = MainWindow()
            if self.auth:
                self.main_window.on_global_auth(self.auth)
            self.main_window.show()
            self.close()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось открыть главное окно:\n{e}")

    def _open_main_window_pdou(self, payload: dict):
        try:
            from ui.main_window import MainWindow
            self.main_window = MainWindow()
            self.main_window.on_global_auth(payload)
            self.main_window.show()
            self.close()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось открыть главное окно:\n{e}")

    # ==================================================================
    #  ГЛАВНАЯ КНОПКА «ВОЙТИ В ЭЖД»
    # ==================================================================
    def on_enter_ejd(self):
        if not SESSION_FILE.exists():
            reply = QMessageBox.question(
                self, "Нет ЭЖД-сессии",
                "Файл session.pkl не найден.\n\n"
                "Войти через браузер (Selenium)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.on_login_ejd()
            return

        self.ejd_enter_btn.setEnabled(False)
        self.ejd_enter_btn.setText("⏳ Проверяю...")
        self.append_log("[i] Проверяю сессию ЭЖД...")

        self.enter_check_worker = SessionCheckWorker()
        self.enter_check_worker.done.connect(self._on_enter_checked)
        self.enter_check_worker.start()

    def _on_enter_checked(self, result: dict):
        self.ejd_enter_btn.setEnabled(True)
        self.ejd_enter_btn.setText("🔓  Войти в ЭЖД")

        if result.get("ok"):
            self.auth = result.get("auth_obj")
            self.append_log("[+] Сессия ЭЖД живая. Открываю главное окно...")
            QTimer.singleShot(200, self._open_main_window)
            return

        reason = result.get("reason", "неизвестно")
        self.append_log(f"[!] Сессия ЭЖД не принята: {reason}")

        reply = QMessageBox.question(
            self, "Сессия недействительна",
            f"Сессия ЭЖД не принята API.\n\n"
            f"Причина: {reason}\n\n"
            "Войти через браузер (Selenium)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.on_login_ejd()

    # ==================================================================
    #  ВХОД ПО ТОКЕНУ
    # ==================================================================
    def _on_ejd_token_changed(self, text):
        has_token = bool(text.strip()) and len(text.strip()) > 50
        self.ejd_token_login_btn.setEnabled(has_token)

    def on_ejd_token_paste(self):
        try:
            from PySide6.QtWidgets import QApplication
            text = QApplication.clipboard().text().strip()
        except Exception:
            text = ""
        if text:
            self.ejd_token_edit.setText(text)
            self.append_log(f"[clipboard] Вставлено {len(text)} символов")
        else:
            self.append_log("[clipboard] Буфер обмена пуст")

    def on_login_by_token(self):
        token = self.ejd_token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "Ошибка", "Введите auth_token.")
            return
        if len(token) < 50:
            QMessageBox.warning(
                self, "Ошибка",
                f"Токен слишком короткий ({len(token)} симв.).\n"
                "Скопируйте значение полностью."
            )
            return

        profile_id = self.ejd_profile_id_edit.text().strip()
        school_id = self.ejd_school_id_edit.text().strip()

        self._set_ejd_ui_enabled(False)
        self.append_log("=" * 50)
        self.append_log("[i] Вход по токену...")

        self.token_login_worker = TokenLoginWorker(
            auth_token=token,
            profile_id=profile_id,
            school_id=school_id,
        )
        self.token_login_worker.log.connect(self.append_log)
        self.token_login_worker.finished_ok.connect(self.on_token_login_ok)
        self.token_login_worker.finished_err.connect(self.on_token_login_err)
        self.token_login_worker.start()

    def on_token_login_ok(self, auth):
        self.auth = auth
        self._set_ejd_ui_enabled(True)
        self._refresh_statuses()
        self.append_log("[+] Вход по токену выполнен. Открываю главное окно...")
        QTimer.singleShot(500, self._open_main_window)

    def on_token_login_err(self, err: str):
        self._set_ejd_ui_enabled(True)
        self.append_log(f"[!] {err}")
        QMessageBox.critical(self, "Ошибка входа по токену", err)

    # ==================================================================
    #  ЭЖД — ИМПОРТ JSON
    # ==================================================================
    def on_import_ejd_json(self):
        try:
            from ui.token_import_dialog import EJDImportDialog
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось открыть диалог импорта ЭЖД:\n{e}")
            return

        dlg = EJDImportDialog(self)
        dlg.tokens_saved.connect(self._on_ejd_imported)
        dlg.exec()

    def _on_ejd_imported(self, payload):
        self.append_log("[+] ЭЖД-сессия импортирована.")

        if hasattr(payload, "session"):
            self.auth = payload
            QTimer.singleShot(200, self._open_main_window)
        else:
            QTimer.singleShot(200, self._start_session_check)

    # ==================================================================
    #  ПДОУ — ИМПОРТ JSON
    # ==================================================================
    def on_import_pdou_json(self):
        try:
            from ui.token_import_dialog import PDOUImportDialog
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось открыть диалог импорта ПДОУ:\n{e}")
            return

        dlg = PDOUImportDialog(self)
        dlg.tokens_saved.connect(self._on_pdou_imported)
        dlg.exec()

    def _on_pdou_imported(self, payload: dict):
        if not payload or not payload.get("saved"):
            return
        user_name = payload.get("user_name", "") or "неизвестен"
        self.append_log(
            f"[+] ПДОУ-сессия импортирована. Пользователь: {user_name}"
        )
        QTimer.singleShot(200, lambda: self._open_main_window_pdou(payload))

    # ==================================================================
    #  ИМПОРТ ИЗ ZIP
    # ==================================================================
    def on_zip_import(self, mode: str = None):
        zip_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите архив .zip с сессиями", str(Path.home()),
            "ZIP archives (*.zip);;Все файлы (*.*)"
        )
        if not zip_path:
            return

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось открыть архив:\n{e}")
            return

        has_ejd = any(n in EJD_FILES for n in names)
        has_pdou = any(n in PDOU_FILES for n in names)

        if not has_ejd and not has_pdou:
            QMessageBox.warning(self, "Нет данных",
                "В архиве не найдено файлов сессий zavuch 2.")
            return

        if mode == "ejd":
            if not has_ejd:
                QMessageBox.warning(self, "Ошибка",
                                    "В архиве нет файлов ЭЖД-сессии.")
                return
            import_ejd, import_pdou = True, False
        elif mode == "pdou":
            if not has_pdou:
                QMessageBox.warning(self, "Ошибка",
                                    "В архиве нет файлов ПДОУ-сессии.")
                return
            import_ejd, import_pdou = False, True
        else:
            import_ejd, import_pdou = self._ask_import_choice(
                has_ejd, has_pdou
            )
            if not import_ejd and not import_pdou:
                return

        reply = QMessageBox.question(
            self, "Подтверждение",
            "Существующие файлы сессий будут перезаписаны.\nПродолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.zip_worker = ZipImportWorker(zip_path, import_ejd, import_pdou)
        self.zip_worker.done.connect(self._on_zip_import_finished)
        self.zip_worker.start()

    def _ask_import_choice(self, has_ejd: bool, has_pdou: bool):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Импорт сессий")
        dlg.setMinimumWidth(400)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Что восстановить из архива?"))

        ejd_cb = QCheckBox("🔐 ЭЖД-сессия")
        ejd_cb.setChecked(has_ejd)
        ejd_cb.setEnabled(has_ejd)
        if not has_ejd:
            ejd_cb.setText("🔐 ЭЖД-сессия (нет в архиве)")
        layout.addWidget(ejd_cb)

        pdou_cb = QCheckBox("🎨 ПДОУ-сессия")
        pdou_cb.setChecked(has_pdou)
        pdou_cb.setEnabled(has_pdou)
        if not has_pdou:
            pdou_cb.setText("🎨 ПДОУ-сессия (нет в архиве)")
        layout.addWidget(pdou_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False, False
        return ejd_cb.isChecked(), pdou_cb.isChecked()

    def _on_zip_import_finished(self, result: dict):
        self._refresh_statuses()

        if result.get("ok"):
            restored = "\n".join(f"• {f}" for f in result.get("restored", []))
            QMessageBox.information(
                self, "Импорт завершён",
                f"✅ Восстановлено файлов: {len(result['restored'])}\n\n"
                f"{restored}\n\n"
                "Рекомендуется перезапустить приложение для применения сессий."
            )
            self.append_log(f"[+] Импорт: {restored}")

            if result.get("ejud") or "session.pkl" in result.get("restored", []):
                self.append_log("[i] Проверяю ЭЖД-сессию...")
                self._start_session_check()
        else:
            QMessageBox.warning(self, "Импорт не удался",
                result.get("reason", "Неизвестная ошибка"))

    # ==================================================================
    #  ИМПОРТ ОТДЕЛЬНЫХ ФАЙЛОВ
    # ==================================================================
    def on_load_ejd_pkl(self):
        pkl_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите session.pkl", str(Path.home()),
            "Pickle session files (*.pkl);;Все файлы (*.*)"
        )
        if not pkl_path:
            return

        try:
            shutil.copy2(pkl_path, SESSION_FILE)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось скопировать session.pkl:\n{e}")
            return

        adjacent = Path(pkl_path).parent / "auth_data.json"
        if adjacent.exists():
            reply = QMessageBox.question(
                self, "Импорт auth_data.json",
                f"Рядом найден auth_data.json:\n{adjacent}\n\n"
                "Скопировать его тоже?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    shutil.copy2(adjacent, AUTH_DATA_FILE)
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка",
                                        f"auth_data.json: {e}")

        self._refresh_statuses()
        QMessageBox.information(self, "Готово",
            "✅ session.pkl импортирован.\n\nПроверяю сессию...")
        self.append_log(f"[+] Импортирован session.pkl: {pkl_path}")
        self._start_session_check()

    def on_load_pdou_json(self):
        token_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите pdou_token.json", str(Path.home()),
            "JSON files (*.json);;Все файлы (*.*)"
        )
        if not token_path:
            return

        try:
            shutil.copy2(token_path, PDOU_TOKEN_FILE)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось скопировать pdou_token.json:\n{e}")
            return

        cookies_candidates = [
            Path(token_path).parent / "pdou_cookies.json",
            Path.home() / "Downloads" / "pdou_cookies.json",
        ]
        cookies_src = None
        for c in cookies_candidates:
            if c.exists():
                cookies_src = c
                break

        if cookies_src:
            reply = QMessageBox.question(
                self, "Импорт pdou_cookies.json",
                f"Найден pdou_cookies.json:\n{cookies_src}\n\n"
                "Скопировать его?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    shutil.copy2(cookies_src, PDOU_COOKIES_FILE)
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка",
                                        f"pdou_cookies.json: {e}")

        self._refresh_statuses()
        QMessageBox.information(self, "Готово",
            "✅ ПДОУ-сессия импортирована.\n\n"
            "Или используйте «📋 Импорт ПДОУ-сессии (JSON / файл)» "
            "для полного импорта с проверкой.")
        self.append_log(f"[+] Импортирован pdou_token.json: {token_path}")

    # ==================================================================
    #  ВХОД ЧЕРЕЗ SELENIUM
    # ==================================================================
    def on_login_ejd(self):
        login = self.ejd_login_edit.text().strip()
        password = self.ejd_password_edit.text()

        if not login or not password:
            QMessageBox.warning(self, "Ошибка",
                                "Введите логин и пароль ЭЖД.")
            return

        if self.ejd_remember_cb.isChecked():
            save_credentials(login, password, "")

        self._set_ejd_ui_enabled(False)
        self.append_log("⏳ Запуск браузера для входа (ЭЖД)...")

        self.ejd_auth_worker = AuthWorker(login, password, None,
                                          pdou_mode=False)
        self.ejd_auth_worker.log.connect(self.append_log)
        self.ejd_auth_worker.cookies_ready.connect(self.on_cookies_ready)
        self.ejd_auth_worker.finished_ok.connect(self.on_ejd_login_ok)
        self.ejd_auth_worker.finished_err.connect(self.on_ejd_login_err)
        self.ejd_auth_worker.start()

    def on_login_pdou(self):
        login = self.pdou_login_edit.text().strip()
        password = self.pdou_password_edit.text()
        totp_key = self.pdou_totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(self, "Ошибка",
                                "Введите логин и пароль учётки ПДОУ.")
            return

        reply = QMessageBox.question(
            self, "Вход как ПДОУ (Selenium)",
            "Будет запущен браузер и сохранена ПДОУ-сессия.\n"
            "Это резервный путь — основной способ входа — "
            "«📋 Импорт ПДОУ-сессии (JSON / файл)».\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_pdou_ui_enabled(False)
        self.append_log("⏳ Запуск браузера для входа (ПДОУ, Selenium)...")

        self.pdou_auth_worker = AuthWorker(login, password, totp_key,
                                           pdou_mode=True)
        self.pdou_auth_worker.log.connect(self.append_log)
        self.pdou_auth_worker.cookies_ready.connect(self.on_cookies_ready)
        self.pdou_auth_worker.finished_ok.connect(self.on_pdou_login_ok)
        self.pdou_auth_worker.finished_err.connect(self.on_pdou_login_err)
        self.pdou_auth_worker.start()

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
        worker = self.ejd_auth_worker or self.pdou_auth_worker
        if worker is None:
            return
        if clicked == close_btn:
            worker._close_browser_event.set()
        else:
            worker._detach_browser_event.set()

    def on_ejd_login_ok(self, auth):
        self.auth = auth
        self._set_ejd_ui_enabled(True)
        self._refresh_statuses()
        self.append_log("[+] ЭЖД: вход выполнен. Открываю главное окно...")
        QTimer.singleShot(500, self._open_main_window)

    def on_ejd_login_err(self, err: str):
        self._set_ejd_ui_enabled(True)
        self.append_log(f"[!] ЭЖД: {err}")
        QMessageBox.critical(self, "Ошибка входа", err)

    def on_pdou_login_ok(self, auth):
        self._set_pdou_ui_enabled(True)
        self._refresh_statuses()
        self.append_log("[+] ПДОУ: вход выполнен, токен сохранён.")

        data = load_pdou_token()
        user_name = data.get("user_name", "") or "неизвестен"
        roles = data.get("user_roles", []) or []

        QMessageBox.information(self, "ПДОУ-сессия сохранена",
            f"✅ ПДОУ-сессия сохранена.\n\nПользователь: {user_name}")

        payload = {
            "user_name": user_name,
            "roles": roles,
            "saved": True,
        }
        QTimer.singleShot(500, lambda: self._open_main_window_pdou(payload))

    def on_pdou_login_err(self, err: str):
        self._set_pdou_ui_enabled(True)
        self.append_log(f"[!] ПДОУ: {err}")
        QMessageBox.critical(self, "Ошибка входа ПДОУ", err)

    # ==================================================================
    #  ОЧИСТКА
    # ==================================================================
    def on_clear_ejd(self):
        reply = QMessageBox.question(
            self, "Очистить ЭЖД-сессию?",
            "Удалить session.pkl, auth_data.json, credentials.json?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for fname in EJD_FILES:
            try:
                (SESSIONS_DIR / fname).unlink(missing_ok=True)
            except Exception:
                pass
        self._refresh_statuses()
        self.append_log("[i] ЭЖД-сессия очищена")

    def on_clear_pdou(self):
        reply = QMessageBox.question(
            self, "Очистить ПДОУ-сессию?",
            "Удалить pdou_token.json и pdou_cookies.json?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for fname in PDOU_FILES:
            try:
                (SESSIONS_DIR / fname).unlink(missing_ok=True)
            except Exception:
                pass
        self._refresh_statuses()
        self.append_log("[i] ПДОУ-сессия очищена")

    def on_clear_all(self):
        reply = QMessageBox.question(
            self, "Очистить всё?",
            "Удалить все сохранённые сессии (ЭЖД + ПДОУ)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for fname in EJD_FILES + PDOU_FILES:
            try:
                (SESSIONS_DIR / fname).unlink(missing_ok=True)
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
        self.append_log("[i] Все сессии очищены")

    # ==================================================================
    #  БЛОКИРОВКА UI
    # ==================================================================
    def _set_ejd_ui_enabled(self, enabled: bool):
        self.ejd_enter_btn.setEnabled(enabled)
        self.ejd_token_login_btn.setEnabled(
            enabled and len(self.ejd_token_edit.text().strip()) > 50
        )
        self.ejd_import_btn.setEnabled(enabled)
        self.ejd_login_btn.setEnabled(enabled)
        self.ejd_load_pkl_btn.setEnabled(enabled)
        self.ejd_load_zip_btn.setEnabled(enabled)
        self.ejd_clear_btn.setEnabled(enabled)
        self.ejd_login_edit.setEnabled(enabled)
        self.ejd_password_edit.setEnabled(enabled)
        self.ejd_token_edit.setEnabled(enabled)
        self.ejd_profile_id_edit.setEnabled(enabled)
        self.ejd_school_id_edit.setEnabled(enabled)

    def _set_pdou_ui_enabled(self, enabled: bool):
        self.pdou_import_btn.setEnabled(enabled)
        self.pdou_login_btn.setEnabled(enabled)
        self.pdou_load_json_btn.setEnabled(enabled)
        self.pdou_load_zip_btn.setEnabled(enabled)
        self.pdou_clear_btn.setEnabled(enabled)
        self.pdou_login_edit.setEnabled(enabled)
        self.pdou_password_edit.setEnabled(enabled)
        self.pdou_totp_edit.setEnabled(enabled)