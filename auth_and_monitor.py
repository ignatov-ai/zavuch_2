# -*- coding: utf-8 -*-
"""
ЭЖД МЭШ — Вход + Мониторинг + Проверка сохранённой сессии.

Логика:
  1. При запуске проверяем ~/.ejd_checker/session.pkl.
  2. Если сессия живая (API возвращает 200) — показываем окно
     «Вы уже вошли» и НЕ запускаем Selenium.
  3. Если сессии нет — показываем форму входа.

Кнопка «Сбросить сессию» удаляет session.pkl и возвращает форму входа.
"""
import sys
import io
import json
import time
import pickle
import tempfile
import traceback
from pathlib import Path
from datetime import datetime

import requests
from urllib.parse import urljoin

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox, QPlainTextEdit,
    QComboBox, QFrame, QStackedWidget,
)


# --- Буферизация вывода ---
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
except Exception:
    pass

DATA_DIR = Path.home() / ".ejd_checker"
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "monitor_log.jsonl"
STORAGE_FILE = DATA_DIR / "storage_dump.json"
COOKIES_FILE = DATA_DIR / "cookies_dump.json"
AUTH_FILE = DATA_DIR / "auth_data.json"
SESSION_FILE = DATA_DIR / "session.pkl"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"


# ============================================================
#  Утилиты
# ============================================================
def append_log_event(event_type: str, payload: dict):
    try:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event_type,
            **payload,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def save_session_cookies(cookies: dict) -> bool:
    """Сохраняет cookies в pickle-файл."""
    try:
        with open(SESSION_FILE, "wb") as f:
            pickle.dump(cookies, f)
        return True
    except Exception:
        return False


def load_session_cookies() -> dict:
    """Загружает cookies из pickle-файла."""
    if not SESSION_FILE.exists():
        return {}
    try:
        with open(SESSION_FILE, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def clear_session():
    """Удаляет session.pkl и auth_data.json."""
    for f in (SESSION_FILE, AUTH_FILE):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass


# ============================================================
#  Проверка сессии (без Selenium)
# ============================================================
def check_saved_session(verbose: bool = True) -> dict:
    """
    Проверяет сохранённую сессию через API dnevnik.mos.ru.

    Возвращает:
      {
        "ok": bool,
        "reason": str,
        "school": str | None,
        "profile_id": str | None,
        "auth_token": str | None,
      }
    """
    result = {"ok": False, "reason": "", "school": None,
              "profile_id": None, "auth_token": None}

    cookies = load_session_cookies()
    if not cookies:
        result["reason"] = "session.pkl не найден"
        return result

    try:
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

        url = "https://dnevnik.mos.ru/core/api/schools"
        resp = session.get(url, timeout=15)

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
        result["auth_token"] = auth_token
        result["reason"] = "сессия живая"

        return result

    except Exception as e:
        result["reason"] = f"ошибка проверки: {e}"
        return result


# ============================================================
#  Поток входа (Selenium)
# ============================================================
class LoginWorker(QThread):
    log = Signal(str)
    finished_ok = Signal(object)      # driver
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

    # ------------------------------------------------------------------
    def _create_chrome_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager

        options = ChromeOptions()
        # options.add_argument("--headless=new")

        temp_profile_dir = tempfile.mkdtemp(prefix="selenium_chrome_")
        options.add_argument(f"--user-data-dir={temp_profile_dir}")
        options.add_argument("--disable-features=ProfilePicker,WelcomeExperience")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-search-engine-choice-screen")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        self._log("[i] Проверяю/скачиваю ChromeDriver...")
        driver_path = ChromeDriverManager().install()
        self._log(f"[+] ChromeDriver: {driver_path}")

        service = ChromeService(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', "
                       "{get: () => undefined})"},
        )
        return driver

    # ------------------------------------------------------------------
    def run(self):
        driver = None
        try:
            self._log("=== Начало авторизации ===")
            self._log(f"[i] Логин: {self.username}")
            self._log(f"[i] 2FA: {'TOTP' if self.totp_key else 'SMS вручную'}")

            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            driver = self._create_chrome_driver()
            self._log("[+] Браузер запущен")

            login_url = (
                "https://login.mos.ru/sps/login/methods/password"
                "?bo=%2Fsps%2Foauth%2Fae%3Fresponse_type%3Dcode"
                "%26access_type%3Doffline"
                "%26client_id%3Ddnevnik.mos.ru"
                "%26scope%3Dopenid%2Bprofile%2Bbirthday%2Bcontacts"
                "%2Bsnils%2Bblitz_user_rights%2Bblitz_change_password"
                "%2Boffline_access"
                "%26redirect_uri%3Dhttps%3A%2F%2Fschool.mos.ru"
                "%2Fv3%2Fauth%2Fsudir%2Fcallback"
            )
            driver.get(login_url)
            wait = WebDriverWait(driver, 30)
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(1.5)

            self._log("[i] Ввожу логин...")
            login_el = wait.until(EC.element_to_be_clickable((By.ID, "login")))
            login_el.click()
            login_el.clear()
            login_el.send_keys(self.username)
            self._log("[+] Логин введён")

            self._log("[i] Ввожу пароль...")
            pass_el = wait.until(EC.element_to_be_clickable((By.ID, "password")))
            pass_el.click()
            pass_el.clear()
            pass_el.send_keys(self.password)
            self._log("[+] Пароль введён")

            self._log("[i] Ищу кнопку 'Войти'...")
            submit = None
            for by, value in [
                (By.ID, "bind"),
                (By.CSS_SELECTOR, "button.bc-form-btn"),
                (By.XPATH, "//button[contains(., 'Войти')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ]:
                try:
                    submit = wait.until(EC.element_to_be_clickable((by, value)))
                    self._log(f"[+] Кнопка найдена: {by}={value}")
                    break
                except Exception:
                    continue
            if submit is None:
                raise Exception("Не удалось найти кнопку 'Войти'")
            submit.click()
            self._log("[+] Кнопка нажата")

            # --- 2FA ---
            time.sleep(3)
            if "methods2" in driver.current_url:
                self._log("[+] Требуется 2FA (SMS)")

                otp_input = None
                for by, value in [
                    (By.CSS_SELECTOR, "input[type='tel']"),
                    (By.ID, "otp"),
                    (By.ID, "code"),
                    (By.CSS_SELECTOR, "input.form-control"),
                ]:
                    try:
                        el = driver.find_element(by, value)
                        if el.is_displayed():
                            otp_input = el
                            break
                    except Exception:
                        continue

                if otp_input is None:
                    raise Exception("Не найдено поле для кода 2FA")

                if self.totp_key:
                    import pyotp
                    code = pyotp.TOTP(self.totp_key).now()
                    self._log(f"[+] TOTP-код: {code}")
                    otp_input.click()
                    otp_input.send_keys(code)
                else:
                    self._log("[!] Введите SMS-код вручную в браузере (5 минут).")
                    end = time.time() + 300
                    while time.time() < end and "login.mos.ru" in driver.current_url:
                        time.sleep(1)
                    if "login.mos.ru" in driver.current_url:
                        raise Exception("Таймаут ожидания ручного ввода SMS")

            # --- ждём редирект на school.mos.ru ---
            self._log("[i] Жду редирект на school.mos.ru...")
            end = time.time() + 60
            while time.time() < end:
                if "school.mos.ru" in driver.current_url and "/auth/callback" not in driver.current_url:
                    break
                time.sleep(1)
            self._log(f"[+] Текущий URL: {driver.current_url}")

            # --- переходим на dnevnik.mos.ru для получения его cookies ---
            self._log("[i] Перехожу на dnevnik.mos.ru для получения cookies...")
            try:
                driver.get("https://dnevnik.mos.ru/")
                time.sleep(4)
                self._log(f"[+] Текущий URL: {driver.current_url}")
            except Exception as e:
                self._log(f"[!] Не удалось перейти: {e}")

            self.finished_ok.emit(driver)

        except Exception as e:
            self._log(f"[!] Ошибка входа: {e}")
            self._log(traceback.format_exc())
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.finished_err.emit(str(e))


# ============================================================
#  Поток мониторинга
# ============================================================
class MonitorWorker(QThread):
    log = Signal(str)
    token_found = Signal(str)
    session_saved = Signal()

    TOKEN_KEYS = ["auth_token", "token", "access_token", "authToken"]

    def __init__(self, driver, interval_sec: float = 2.0):
        super().__init__()
        self.driver = driver
        self.interval = interval_sec
        self._stop = False
        self.prev_url = None
        self.prev_ls = {}
        self.prev_ss = {}
        self.prev_cookies = {}
        self.token_saved = False
        self.session_saved_flag = False

    def stop(self):
        self._stop = True

    def _get_storage(self, kind: str) -> dict:
        try:
            return self.driver.execute_script(
                f"return Object.fromEntries(Object.entries(window.{kind}));"
            ) or {}
        except Exception:
            return {}

    def _get_all_cookies(self) -> dict:
        """Cookies всех доменов через CDP (fallback — текущий домен)."""
        try:
            result = self.driver.execute_cdp_cmd("Network.getAllCookies", {})
            cookies = result.get("cookies", [])
            out = {}
            for c in cookies:
                key = f"{c.get('domain', '?')}|{c['name']}"
                out[key] = c["value"]
            return out
        except Exception:
            try:
                return {c["name"]: c["value"] for c in self.driver.get_cookies()}
            except Exception:
                return {}

    def _diff(self, old: dict, new: dict) -> dict:
        changes = {}
        for k, v in new.items():
            if k not in old or old[k] != v:
                changes[k] = (old.get(k), v)
        return changes

    def _extract_token_from_cookies(self, cookies: dict):
        for key, value in cookies.items():
            name = key.split("|", 1)[-1] if "|" in key else key
            if name in self.TOKEN_KEYS and value:
                return value, key
        return None, None

    def _try_save_session(self, cookies: dict):
        """Пытается сохранить session.pkl, если есть auth_token + profile_id."""
        if self.session_saved_flag:
            return

        # Ищем auth_token и profile_id среди cookies
        auth_token = None
        profile_id = None
        for key, value in cookies.items():
            name = key.split("|", 1)[-1] if "|" in key else key
            if name == "auth_token":
                auth_token = value
            elif name == "profile_id":
                profile_id = value

        if not auth_token or not profile_id:
            return

        # Собираем cookies для dnevnik.mos.ru
        dnevnik_cookies = {}
        for key, value in cookies.items():
            if "|" in key and key.startswith("dnevnik.mos.ru|"):
                name = key.split("|", 1)[-1]
                dnevnik_cookies[name] = value

        if save_session_cookies(dnevnik_cookies):
            self.log.emit(f"[+] session.pkl сохранён ({len(dnevnik_cookies)} cookies)")
            append_log_event("session_saved", {"count": len(dnevnik_cookies)})
            self.session_saved_flag = True
            self.session_saved.emit()

    def run(self):
        self.log.emit(f"[i] Мониторинг запущен. Интервал: {self.interval} сек.")
        append_log_event("monitor_start", {"interval": self.interval})

        while not self._stop:
            try:
                url = self.driver.current_url
            except Exception:
                self.log.emit("[!] Потеряна связь с браузером.")
                break

            if url != self.prev_url:
                self.log.emit(f"[URL] {url}")
                append_log_event("url_change", {"url": url})
                self.prev_url = url

            # --- localStorage ---
            ls = self._get_storage("localStorage")
            for k, (old, new) in self._diff(self.prev_ls, ls).items():
                short = str(new)[:60] if new is not None else "None"
                self.log.emit(f"[LS] {k} = {short}")
                append_log_event("localStorage", {"key": k, "value": new})
            self.prev_ls = ls

            # --- sessionStorage ---
            ss = self._get_storage("sessionStorage")
            for k, (old, new) in self._diff(self.prev_ss, ss).items():
                short = str(new)[:60] if new is not None else "None"
                self.log.emit(f"[SS] {k} = {short}")
                append_log_event("sessionStorage", {"key": k, "value": new})
            self.prev_ss = ss

            # --- cookies всех доменов ---
            ck = self._get_all_cookies()
            for k, (old, new) in self._diff(self.prev_cookies, ck).items():
                short = str(new)[:60] if new is not None else "None"
                self.log.emit(f"[CK] {k} = {short}")
                append_log_event("cookie", {"key": k, "value": new})
            self.prev_cookies = ck

            # --- сохраняем снимки ---
            try:
                with open(STORAGE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"localStorage": ls, "sessionStorage": ss},
                              f, ensure_ascii=False, indent=2)
                with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                    json.dump(ck, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            # --- ищем auth_token ---
            if not self.token_saved:
                token = None
                where = None

                for key in self.TOKEN_KEYS:
                    if ls.get(key):
                        token, where = ls[key], f"localStorage['{key}']"
                        break
                if not token:
                    for key in self.TOKEN_KEYS:
                        if ss.get(key):
                            token, where = ss[key], f"sessionStorage['{key}']"
                            break
                if not token:
                    token, where = self._extract_token_from_cookies(ck)

                if token:
                    self.log.emit(f"[+] ТОКЕН НАЙДЕН ({where}): {token[:60]}...")
                    append_log_event("token_found", {"token": token, "where": where})
                    try:
                        with open(AUTH_FILE, "w", encoding="utf-8") as f:
                            json.dump({
                                "auth_token": token,
                                "where": where,
                                "profile_id": ls.get("MES_API_PROFILE_ID")
                                              or ls.get("profileId"),
                                "year_id": ls.get("MES_API_YEAR_ID"),
                            }, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    self.token_found.emit(token)
                    self.token_saved = True

            # --- пытаемся сохранить session.pkl ---
            self._try_save_session(ck)

            slept = 0.0
            while slept < self.interval and not self._stop:
                time.sleep(0.2)
                slept += 0.2

        append_log_event("monitor_stop", {})
        self.log.emit("[i] Мониторинг остановлен.")


# ============================================================
#  Окно «Вы уже вошли»
# ============================================================
class AlreadyLoggedInWindow(QWidget):
    """Показывается, если сессия уже есть и она живая."""
    continue_clicked = Signal()
    reset_clicked = Signal()

    def __init__(self, session_info: dict):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Вы уже вошли")
        self.setMinimumSize(520, 320)
        self.session_info = session_info
        self._build_ui()

    def _build_ui(self):
        title = QLabel("✅ Вы уже вошли")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: green; margin: 10px;")

        info_lines = [
            f"Школа: {self.session_info.get('school', 'неизвестно')}",
            f"Profile ID: {self.session_info.get('profile_id', '?')}",
            f"Токен: {str(self.session_info.get('auth_token', ''))[:40]}...",
            "",
            f"Сессия сохранена: {SESSION_FILE}",
            "",
            "Вход выполнять не нужно — программа будет использовать",
            "сохранённые cookies. Никаких запросов к mos.ru не будет.",
        ]
        info = QLabel("\n".join(info_lines))
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        info.setStyleSheet("color: #333; padding: 10px; font-size: 12px;")

        self.continue_btn = QPushButton("Продолжить работу")
        self.continue_btn.setMinimumHeight(38)
        self.continue_btn.clicked.connect(self.continue_clicked.emit)

        self.reset_btn = QPushButton("Сбросить сессию и войти заново")
        self.reset_btn.setMinimumHeight(32)
        self.reset_btn.setStyleSheet("color: #a00;")
        self.reset_btn.clicked.connect(self.reset_clicked.emit)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(info)
        layout.addStretch()
        layout.addWidget(self.continue_btn)
        layout.addWidget(self.reset_btn)
        self.setLayout(layout)


# ============================================================
#  Главное окно с двумя экранами
# ============================================================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Вход + Мониторинг")
        self.setMinimumSize(760, 660)

        self.driver = None
        self.login_worker = None
        self.monitor_worker = None

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        # StackedWidget позволяет переключать «экраны» без пересоздания окна
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome_screen())
        self.stack.addWidget(self._build_login_screen())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    def _build_welcome_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("ЭЖД МЭШ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; margin: 20px;")

        self.welcome_status = QLabel("Проверяю сохранённую сессию...")
        self.welcome_status.setAlignment(Qt.AlignCenter)
        self.welcome_status.setWordWrap(True)
        self.welcome_status.setStyleSheet("color: #666; padding: 8px;")

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(self.welcome_status)
        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    def _build_login_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("Вход в ЭЖД МЭШ с мониторингом токенов")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin: 6px;")

        hint = QLabel(
            "1) Введите логин и пароль, нажмите «Войти».\n"
            "2) Если попросит SMS — введите код в браузере (5 минут).\n"
            "3) После входа скрипт перейдёт на dnevnik.mos.ru и получит cookies.\n"
            "4) Мониторинг запустится автоматически. Ходите по сайту.\n"
            "5) Когда токен появится — увидите уведомление."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #444; padding: 4px;")

        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Логин")
        self.login_edit.setMinimumHeight(30)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(30)

        self.totp_edit = QLineEdit()
        self.totp_edit.setPlaceholderText("TOTP-ключ (можно пусто — тогда SMS вручную)")
        self.totp_edit.setMinimumHeight(30)

        browser_row = QHBoxLayout()
        browser_row.addWidget(QLabel("Браузер:"))
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["chrome"])
        browser_row.addWidget(self.browser_combo)
        browser_row.addStretch()

        self.login_btn = QPushButton("Войти")
        self.login_btn.setMinimumHeight(36)
        self.login_btn.clicked.connect(self.on_login)

        self.stop_btn = QPushButton("Остановить и закрыть")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.clicked.connect(self.on_stop)
        self.stop_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.login_btn)
        btn_row.addWidget(self.stop_btn)

        self.status = QLabel("Готов к работе")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #666; padding: 4px;")

        line = QFrame()
        line.setFrameShape(QFrame.HLine)

        log_label = QLabel("Журнал событий:")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
            "background-color: #1e1e1e; color: #d4d4d4;"
        )

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.login_edit)
        layout.addWidget(self.password_edit)
        layout.addWidget(self.totp_edit)
        layout.addLayout(browser_row)
        layout.addLayout(btn_row)
        layout.addWidget(self.status)
        layout.addWidget(line)
        layout.addWidget(log_label)
        layout.addWidget(self.log_view, stretch=1)
        return w

    # ------------------------------------------------------------------
    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ================================================================
    #  ПРОВЕРКА СЕССИИ ПРИ СТАРТЕ
    # ================================================================
    def start_session_check(self):
        """
        Вызывается после показа окна.
        Проверяет сохранённую сессию и переключает экран.
        """
        self.welcome_status.setText("Проверяю сохранённую сессию...")
        self.welcome_status.setStyleSheet("color: #666; padding: 8px;")

        # Делаем проверку в отдельном потоке, чтобы GUI не подвисал
        class CheckWorker(QThread):
            done = Signal(dict)

            def run(self):
                self.done.emit(check_saved_session())

        self.check_worker = CheckWorker()
        self.check_worker.done.connect(self.on_session_checked)
        self.check_worker.start()

    # ------------------------------------------------------------------
    def on_session_checked(self, result: dict):
        if result.get("ok"):
            # --- сессия живая — показываем окно «Вы уже вошли» ---
            self.welcome_status.setText(
                f"✅ Найдена живая сессия: {result.get('school')}"
            )
            self.welcome_status.setStyleSheet(
                "color: green; font-weight: bold; padding: 8px;"
            )

            self.already_window = AlreadyLoggedInWindow(result)
            self.already_window.continue_clicked.connect(self.on_continue_work)
            self.already_window.reset_clicked.connect(self.on_reset_session)
            self.already_window.show()
            self.hide()
        else:
            # --- сессии нет — показываем форму входа ---
            reason = result.get("reason", "")
            self.welcome_status.setText(
                f"Сессия не найдена ({reason}).\nПереход к форме входа..."
            )
            self.welcome_status.setStyleSheet("color: #666; padding: 8px;")
            QApplication.processEvents()
            time.sleep(0.7)
            self.stack.setCurrentIndex(1)
            self.show()

    # ------------------------------------------------------------------
    def on_continue_work(self):
        """
        Пользователь нажал «Продолжить работу» — переходим на экран
        логина, но БЕЗ запуска Selenium. Пользователь сам выберет,
        что делать дальше.
        """
        if hasattr(self, "already_window") and self.already_window:
            self.already_window.close()
            self.already_window = None

        self.stack.setCurrentIndex(1)
        self.show()

        # Заполняем поля из credentials.json (если есть)
        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    creds = json.load(f)
                self.login_edit.setText(creds.get("login", ""))
                self.password_edit.setText(creds.get("password", ""))
                self.totp_edit.setText(creds.get("totp_key", ""))
            except Exception:
                pass

        self.status.setText("Используется сохранённая сессия. "
                            "Можно закрыть приложение — она уже работает.")
        self.status.setStyleSheet("color: green; font-weight: bold;")
        self.append_log("[+] Сессия загружена. Selenium не запущен.")
        self.append_log(f"[i] cookies: {SESSION_FILE}")

    # ------------------------------------------------------------------
    def on_reset_session(self):
        """Пользователь хочет сбросить сессию и войти заново."""
        if hasattr(self, "already_window") and self.already_window:
            self.already_window.close()
            self.already_window = None

        clear_session()
        self.stack.setCurrentIndex(1)
        self.show()
        self.append_log("[i] Сессия сброшена. Войдите заново.")
        self.status.setText("Сессия сброшена. Войдите заново.")
        self.status.setStyleSheet("color: #666;")

    # ================================================================
    #  ВХОД ЧЕРЕЗ SELENIUM
    # ================================================================
    def on_login(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        totp = self.totp_edit.text().strip() or None

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль.")
            return

        # Сохраняем введённые данные
        try:
            with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump({"login": login, "password": password,
                           "totp_key": totp or ""},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        self.login_btn.setEnabled(False)
        self.status.setText("Выполняется вход...")
        self.status.setStyleSheet("color: #0066cc; font-weight: bold;")
        self.log_view.clear()

        self.login_worker = LoginWorker(login, password, totp, "chrome")
        self.login_worker.log.connect(self.append_log)
        self.login_worker.finished_ok.connect(self.on_login_ok)
        self.login_worker.finished_err.connect(self.on_login_err)
        self.login_worker.start()

    # ------------------------------------------------------------------
    def on_login_ok(self, driver):
        self.driver = driver
        self.status.setText("Вход выполнен. Мониторинг идёт...")
        self.status.setStyleSheet("color: green; font-weight: bold;")
        self.stop_btn.setEnabled(True)
        self.append_log("[+] Вход выполнен. Запускаю мониторинг.")

        self.monitor_worker = MonitorWorker(self.driver, interval_sec=2.0)
        self.monitor_worker.log.connect(self.append_log)
        self.monitor_worker.token_found.connect(self.on_token_found)
        self.monitor_worker.session_saved.connect(self.on_session_saved)
        self.monitor_worker.start()

    # ------------------------------------------------------------------
    def on_login_err(self, err: str):
        self.login_btn.setEnabled(True)
        self.status.setText("Ошибка входа")
        self.status.setStyleSheet("color: red; font-weight: bold;")
        QMessageBox.critical(self, "Ошибка", err)

    # ------------------------------------------------------------------
    def on_token_found(self, token: str):
        self.append_log(f"[+] ТОКЕН: {token[:60]}...")

    # ------------------------------------------------------------------
    def on_session_saved(self):
        self.append_log("[+] session.pkl сохранён — в следующий раз "
                        "вход не потребуется.")
        self.status.setText("Вход выполнен. Сессия сохранена ✅")
        self.status.setStyleSheet("color: green; font-weight: bold;")

    # ------------------------------------------------------------------
    def on_stop(self):
        if self.monitor_worker:
            self.monitor_worker.stop()
            self.monitor_worker.wait(3000)
            self.monitor_worker = None
        if self.driver:
            try:
                self.driver.quit()
                self.append_log("[i] Браузер закрыт.")
            except Exception:
                pass
            self.driver = None
        self.stop_btn.setEnabled(False)
        self.login_btn.setEnabled(True)
        self.status.setText("Остановлено.")
        self.status.setStyleSheet("color: #666;")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self.on_stop()
        event.accept()


# ============================================================
def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    # Проверку сессии запускаем после отрисовки окна
    w.start_session_check()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()