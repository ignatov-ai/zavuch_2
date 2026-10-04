# -*- coding: utf-8 -*-
"""
Selenium-авторизация в ЭЖД МЭШ (отдельный воркер).
2FA: SMS (ручной ввод) и TOTP (pyotp).
Сессии сохраняются в <папка проекта>/sessions/ (см. paths.py).
"""
import io
import sys
import json
import time
import pickle
import logging
import tempfile
import traceback
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

import requests
from urllib.parse import urljoin

from PySide6.QtCore import QThread, Signal

from paths import (
    SESSIONS_DIR,
    SESSION_FILE,
    AUTH_DATA_FILE,
    CREDENTIALS_FILE,
)

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                   line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8',
                                   line_buffering=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)


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


def clear_credentials() -> bool:
    try:
        if CREDENTIALS_FILE.exists():
            CREDENTIALS_FILE.unlink()
        return True
    except Exception:
        return False


class AuthWorker(QThread):
    finished_ok = Signal(str)
    finished_err = Signal(str)
    log = Signal(str)

    def __init__(self, username: str, password: str,
                 totp_key: str = None, browser: str = "chrome"):
        super().__init__()
        self.username = username
        self.password = password
        self.totp_key = totp_key or ""
        self.browser = browser
        self.base = "https://dnevnik.mos.ru/"
        self.timeout = 30

    def _log(self, msg: str):
        print(msg, flush=True)
        self.log.emit(msg)

    def save_session(self, session: requests.Session) -> bool:
        """Сохраняет cookies как список словарей (без RLock)."""
        try:
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
            self._log(f"[+] Сессия сохранена: {SESSION_FILE}")
            return True
        except Exception as e:
            self._log(f"[!] Не удалось сохранить сессию: {e}")
            self._log(traceback.format_exc())
            return False

    def _save_debug(self, driver, name: str):
        debug_dir = Path(__file__).parent / "debug"
        debug_dir.mkdir(exist_ok=True)
        try:
            driver.save_screenshot(str(debug_dir / f"{name}.png"))
            with open(debug_dir / f"{name}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        except Exception:
            pass

    def _create_chrome_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager

        options = ChromeOptions()
        temp_profile_dir = tempfile.mkdtemp(prefix="selenium_chrome_")
        options.add_argument(f"--user-data-dir={temp_profile_dir}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        self._log("[i] Скачиваю ChromeDriver...")
        driver_path = ChromeDriverManager().install()
        self._log(f"[+] ChromeDriver: {driver_path}")
        service = ChromeService(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        return driver

    def _create_firefox_driver(self):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        from selenium.webdriver.firefox.service import Service as FirefoxService
        from webdriver_manager.firefox import GeckoDriverManager
        options = FirefoxOptions()
        self._log("[i] Скачиваю geckodriver...")
        driver_path = GeckoDriverManager().install()
        service = FirefoxService(executable_path=driver_path)
        return webdriver.Firefox(service=service, options=options)

    def run(self):
        driver = None
        try:
            self._log("=== Начало авторизации ===")
            self._log(f"[i] Логин: {self.username}")
            self._log(f"[i] Папка сессий: {SESSIONS_DIR}")

            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            if self.browser == "firefox":
                driver = self._create_firefox_driver()
            else:
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

            # Логин
            el = wait.until(EC.element_to_be_clickable((By.ID, "login")))
            el.click(); time.sleep(0.3); el.clear(); el.send_keys(self.username)

            # Пароль
            el = wait.until(EC.element_to_be_clickable((By.ID, "password")))
            el.click(); time.sleep(0.3); el.clear(); el.send_keys(self.password)

            # Кнопка
            submit = wait.until(EC.element_to_be_clickable((By.ID, "bind")))
            submit.click()
            time.sleep(3)

            # 2FA
            if "methods2" in driver.current_url:
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
                    otp_input.click()
                    otp_input.send_keys(code)
                    time.sleep(3)
                else:
                    end = time.time() + 300
                    while time.time() < end and "login.mos.ru" in driver.current_url:
                        time.sleep(1)
                    if "login.mos.ru" in driver.current_url:
                        raise Exception("Таймаут ожидания ручного ввода SMS")

            # Ждём редирект
            end = time.time() + 60
            while time.time() < end:
                if "school.mos.ru" in driver.current_url and "/auth/callback" not in driver.current_url:
                    break
                time.sleep(1)
            time.sleep(3)

            # Собираем cookies с фильтрацией
            all_cookies = {}
            try:
                result = driver.execute_cdp_cmd("Network.getAllCookies", {})
                for c in result.get("cookies", []):
                    name = c.get("name", "")
                    value = c.get("value", "")
                    domain = c.get("domain", "")
                    if not name or not value:
                        continue
                    if any(d in domain for d in ("dnevnik.mos.ru", "school.mos.ru", ".mos.ru")):
                        all_cookies[name] = value
            except Exception as e:
                self._log(f"[!] CDP getAllCookies: {e}")

            # Токен
            auth_token = None
            try:
                auth_token = driver.execute_script("""
                    return window.sessionStorage.getItem('auth_token')
                        || window.localStorage.getItem('auth_token')
                        || window.sessionStorage.getItem('token')
                        || window.localStorage.getItem('token')
                        || null;
                """)
            except Exception:
                pass

            profile_id = None
            try:
                profile_id = driver.execute_script("""
                    return window.sessionStorage.getItem('profile_id')
                        || window.localStorage.getItem('profile_id')
                        || null;
                """)
            except Exception:
                pass

            if not auth_token:
                for c in driver.get_cookies():
                    if c.get("name") in ("auth_token", "token", "access_token"):
                        auth_token = c.get("value")
                        break

            self._log(f"[i] auth_token={'✅' if auth_token else '❌'}, "
                      f"profile_id={profile_id or '—'}, cookies={len(all_cookies)}")

            # Session
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/152.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            })
            for name, value in all_cookies.items():
                for dom in ("dnevnik.mos.ru", "school.mos.ru"):
                    session.cookies.set(name, value, domain=dom)

            if auth_token:
                session.headers["Auth-Token"] = auth_token
                session.headers["Authorization"] = f"Bearer {auth_token}"
            if profile_id:
                session.headers["Profile-Id"] = str(profile_id)

            # Проверка
            resp = session.get("https://dnevnik.mos.ru/core/api/schools", timeout=20)
            self._log(f"[i] HTTP {resp.status_code}")
            if resp.status_code != 200:
                self.finished_err.emit(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return

            data = resp.json()
            if not data:
                self.finished_err.emit("Пустой ответ API")
                return

            school_name = data[0].get("name", "?")
            self._log(f"[+] Авторизация успешна! Школа: {school_name}")

            # Сохраняем
            self.save_session(session)
            try:
                with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "auth_token": auth_token,
                        "aupd_token": auth_token,
                        "profile_id": str(profile_id or ""),
                        "school_id": str(data[0].get("id", "")),
                    }, f, ensure_ascii=False, indent=2)
                self._log(f"[+] auth_data.json сохранён")
            except Exception as e:
                self._log(f"[!] auth_data.json: {e}")

            save_credentials(self.username, self.password, self.totp_key)
            self.finished_ok.emit(f"Школа: {school_name}")

        except Exception as e:
            self._log(f"[!] Исключение: {e}")
            self._log(traceback.format_exc())
            self.finished_err.emit(f"Ошибка авторизации:\n{e}")
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            self._log("=== Завершение работы ===")