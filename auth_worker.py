# -*- coding: utf-8 -*-
"""
Логика авторизации в ЭЖД МЭШ через Selenium + webdriver-manager.
Поддерживает 2FA через SMS (ручной ввод) и TOTP (pyotp).
Извлекает auth_token из sessionStorage/localStorage после полной загрузки приложения.
"""
import io
import sys
import json
import time
import pickle
import logging
import tempfile
import traceback
from pathlib import Path

import requests
from urllib.parse import urljoin

from PySide6.QtCore import QThread, Signal

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

DATA_DIR = Path.home() / ".ejd_checker"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"


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

    def __init__(self, username: str, password: str, totp_key: str = None, browser: str = "chrome"):
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
        try:
            with open(SESSION_FILE, "wb") as f:
                pickle.dump(session.cookies, f)
            self._log(f"[+] Сессия сохранена: {SESSION_FILE}")
            return True
        except Exception as e:
            self._log(f"[!] Не удалось сохранить сессию: {e}")
            return False

    def _save_debug(self, driver, name: str):
        debug_dir = Path(__file__).parent / "debug"
        debug_dir.mkdir(exist_ok=True)
        try:
            driver.save_screenshot(str(debug_dir / f"{name}.png"))
            with open(debug_dir / f"{name}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            self._log(f"[!] Отладка: {debug_dir / (name + '.png')}")
        except Exception as e:
            self._log(f"[!] Не удалось сохранить отладку: {e}")

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
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        return driver

    def _create_firefox_driver(self):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        from selenium.webdriver.firefox.service import Service as FirefoxService
        from webdriver_manager.firefox import GeckoDriverManager
        options = FirefoxOptions()
        self._log("[i] Проверяю/скачиваю geckodriver...")
        driver_path = GeckoDriverManager().install()
        self._log(f"[+] geckodriver: {driver_path}")
        service = FirefoxService(executable_path=driver_path)
        driver = webdriver.Firefox(service=service, options=options)
        return driver

    def _find_and_fill(self, driver, wait, by, value, text, label):
        from selenium.webdriver.support import expected_conditions as EC
        self._log(f"[i] Жду появления поля '{label}' ({by}={value})...")
        el = wait.until(EC.element_to_be_clickable((by, value)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        time.sleep(0.3)
        el.click()
        el.clear()
        el.send_keys(text)
        self._log(f"[+] {label} введён")
        return el

    def _find_submit_button(self, driver, wait):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        variants = [
            (By.ID, "bind"),
            (By.CSS_SELECTOR, "button.bc-form-btn"),
            (By.XPATH, "//button[contains(., 'Войти')]"),
            (By.XPATH, "//button[contains(., 'Вход')]"),
            (By.CSS_SELECTOR, "button.btn-primary"),
            (By.CSS_SELECTOR, "button[type='submit']"),
        ]
        for by, value in variants:
            try:
                self._log(f"[i] Пробую найти кнопку: {by}={value}")
                btn = wait.until(EC.element_to_be_clickable((by, value)))
                if btn.is_displayed():
                    self._log(f"[+] Кнопка найдена: {by}={value}")
                    return btn
            except Exception:
                continue
        return None

    def _handle_2fa(self, driver, wait) -> bool:
        from selenium.webdriver.common.by import By
        self._log("[i] Проверяю, нужен ли второй фактор (2FA)...")
        time.sleep(3)
        current_url = driver.current_url
        self._log(f"[i] Текущий URL после нажатия 'Войти': {current_url}")
        needs_2fa = ("methods2/sms" in current_url or "methods2/otp" in current_url or "methods2" in current_url)
        if not needs_2fa:
            try:
                bind_btn = driver.find_element(By.ID, "bind")
                if bind_btn.is_displayed():
                    needs_2fa = True
                    self._log("[+] Обнаружена кнопка #bind — 2FA требуется")
            except Exception:
                pass
        if not needs_2fa:
            self._log("[i] 2FA не требуется, продолжаем")
            return True

        self._log("[+] Обнаружена страница 2FA")
        otp_input = None
        for by, value in [
            (By.ID, "otp"), (By.ID, "code"), (By.ID, "sms_code"),
            (By.NAME, "otp"), (By.NAME, "code"),
            (By.CSS_SELECTOR, "input[autocomplete='one-time-code']"),
            (By.CSS_SELECTOR, "input[type='tel']"),
            (By.CSS_SELECTOR, "input[type='text']"),
            (By.CSS_SELECTOR, "input.form-control"),
        ]:
            try:
                el = driver.find_element(by, value)
                if el.is_displayed():
                    otp_input = el
                    self._log(f"[+] Найдено поле для кода 2FA: {by}={value}")
                    break
            except Exception:
                continue

        if otp_input is None:
            self._log("[!] Поле для кода 2FA не найдено. Сохраняю HTML...")
            self._save_debug(driver, "2fa_no_input")
            return False

        def _find_confirm_button():
            for by, value in [
                (By.ID, "bind"),
                (By.CSS_SELECTOR, "button.bc-form-btn"),
                (By.CSS_SELECTOR, "button.btn-primary"),
                (By.XPATH, "//button[contains(., 'Подтвердить')]"),
                (By.XPATH, "//button[contains(., 'Войти')]"),
                (By.XPATH, "//button[contains(., 'Продолжить')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ]:
                try:
                    btn = driver.find_element(by, value)
                    if btn.is_displayed():
                        self._log(f"[+] Кнопка подтверждения: {by}={value}")
                        return btn
                except Exception:
                    continue
            return None

        if self.totp_key:
            try:
                import pyotp
            except ImportError:
                self._log("[!] Библиотека pyotp не установлена. Выполните: pip install pyotp")
                return False
            totp = pyotp.TOTP(self.totp_key)
            code = totp.now()
            self._log(f"[+] Сгенерирован TOTP-код: {code}")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", otp_input)
            time.sleep(0.3)
            otp_input.click()
            otp_input.clear()
            otp_input.send_keys(code)
            self._log("[+] TOTP-код введён")
            confirm_btn = _find_confirm_button()
            if confirm_btn:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", confirm_btn)
                time.sleep(0.3)
                confirm_btn.click()
                self._log("[+] Кнопка подтверждения нажата")
            else:
                self._log("[!] Кнопка не найдена — нажмите Enter вручную")
            time.sleep(3)
            return True

        self._log("[!] TOTP-ключ не задан. Ожидаю ручного ввода кода из СМС.")
        self._log(f"[!] У вас 300 секунд. Введите код в браузере и нажмите 'Войти'.")
        end_time = time.time() + 300
        last_url = driver.current_url
        last_log_time = 0
        while time.time() < end_time:
            try:
                current = driver.current_url
                if current != last_url:
                    self._log(f"[i] URL изменился: {current}")
                    last_url = current
                if "login.mos.ru" not in current:
                    self._log("[+] Вход выполнен вручную (URL изменился).")
                    time.sleep(3)
                    return True
                now = time.time()
                if now - last_log_time > 30:
                    remaining = int(end_time - now)
                    self._log(f"[i] Ожидание ручного ввода... осталось {remaining} сек.")
                    last_log_time = now
            except Exception:
                pass
            time.sleep(1)
        self._log("[!] Таймаут ожидания ручного ввода (300 сек).")
        self._save_debug(driver, "2fa_timeout")
        return False

    def run(self):
        driver = None
        try:
            self._log("=== Начало авторизации ===")
            self._log(f"[i] Логин: {self.username}")
            self._log(f"[i] Браузер: {self.browser}")
            self._log(f"[i] 2FA: {'включена (TOTP)' if self.totp_key else 'выключена / SMS вручную'}")

            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait

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
            self._log("[i] Открываю страницу входа...")
            driver.get(login_url)
            wait = WebDriverWait(driver, 30)
            self._log("[i] Жду document.readyState == 'complete'...")
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            self._log("[+] Документ загружен")
            time.sleep(1.5)

            self._find_and_fill(driver, wait, By.ID, "login", self.username, "логин")
            self._find_and_fill(driver, wait, By.ID, "password", self.password, "пароль")

            self._log("[i] Ищу кнопку 'Войти'...")
            submit_button = self._find_submit_button(driver, wait)
            if submit_button is None:
                self._save_debug(driver, "no_submit_btn")
                raise Exception("Не удалось найти кнопку 'Войти'")
            submit_button.click()
            self._log("[+] Кнопка нажата")

            if not self._handle_2fa(driver, wait):
                self._save_debug(driver, "2fa_failed")
                self.finished_err.emit(
                    "Не удалось пройти двухфакторную аутентификацию.\n"
                    "Проверьте TOTP-ключ или введите код вручную в браузере."
                )
                return

            # --- ЖДЁМ РЕДИРЕКТ НА ОСНОВНОЙ ДОМЕН ---
            self._log("[i] Жду редирект на school.mos.ru ...")
            try:
                wait.until(
                    lambda d: "school.mos.ru" in d.current_url
                    and "/auth/callback" not in d.current_url
                )
                self._log(f"[+] Редирект выполнен: {driver.current_url}")
            except Exception as e:
                self._log(f"[!] Редирект не выполнен: {e}")
                self._log(f"[!] Текущий URL: {driver.current_url}")
                self._save_debug(driver, "after_submit")
                self.finished_err.emit(
                    "Не удалось завершить вход.\n"
                    f"Текущий URL: {driver.current_url}"
                )
                return

            # --- ЖДЁМ ТОКЕН (до 20 секунд) ---
            self._log("[i] Жду загрузки приложения МЭШ и появления токена (до 20 секунд)...")
            auth_token = None
            profile_id = None
            end_time = time.time() + 20

            while time.time() < end_time:
                auth_token = driver.execute_script(
                    "return window.sessionStorage.getItem('auth_token') "
                    "|| window.sessionStorage.getItem('token') "
                    "|| window.sessionStorage.getItem('access_token');"
                )
                if auth_token:
                    self._log(f"[+] auth_token найден в sessionStorage: {auth_token[:30]}...")
                    break
                auth_token = driver.execute_script(
                    "return window.localStorage.getItem('auth_token') "
                    "|| window.localStorage.getItem('token') "
                    "|| window.localStorage.getItem('access_token');"
                )
                if auth_token:
                    self._log(f"[+] auth_token найден в localStorage: {auth_token[:30]}...")
                    break
                profile_id = driver.execute_script(
                    "return window.sessionStorage.getItem('profile_id') "
                    "|| window.localStorage.getItem('profile_id');"
                )
                time.sleep(1)

            if not auth_token:
                self._log("[!] Токен не найден за 20 секунд. Сохраняю отладку...")
                self._save_debug(driver, "no_token_found")
                # Не выходим сразу — возможно, токен в куках
                for cookie in driver.get_cookies():
                    if cookie["name"] in ("auth_token", "token", "access_token"):
                        auth_token = cookie["value"]
                        self._log(f"[+] auth_token найден в cookies: {auth_token[:30]}...")
                        break

            # --- Собираем куки ---
            selenium_cookies = driver.get_cookies()
            self._log(f"[+] Получено кук: {len(selenium_cookies)}")
            for c in selenium_cookies:
                self._log(f"    - {c['name']}")

            try:
                with open(DATA_DIR / "cookies_after_login.json", "w", encoding="utf-8") as f:
                    json.dump({c["name"]: c["value"] for c in selenium_cookies}, f, ensure_ascii=False, indent=2)
                self._log(f"[+] Куки сохранены: {DATA_DIR / 'cookies_after_login.json'}")
            except Exception:
                pass

            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/152.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            })
            for cookie in selenium_cookies:
                session.cookies.set(cookie["name"], cookie["value"])

            if auth_token:
                session.headers.update({
                    "Auth-Token": auth_token,
                    "Authorization": f"Bearer {auth_token}",
                })
                self._log("[+] Заголовки Auth-Token и Authorization добавлены")
            else:
                self._log("[!] auth_token не найден — API вернёт 403")

            if profile_id:
                session.headers.update({"Profile-Id": profile_id})
                self._log(f"[+] Profile-Id: {profile_id}")

            try:
                with open(DATA_DIR / "auth_data.json", "w", encoding="utf-8") as f:
                    json.dump({"auth_token": auth_token, "profile_id": profile_id}, f, ensure_ascii=False, indent=2)
                self._log(f"[+] Auth-данные сохранены: {DATA_DIR / 'auth_data.json'}")
            except Exception:
                pass

            url = urljoin(self.base, "core/api/schools")
            self._log(f"[i] Проверяю авторизацию: GET {url}")
            resp = session.get(url, timeout=self.timeout)
            self._log(f"[i] HTTP {resp.status_code}")

            if resp.status_code != 200:
                self._save_debug(driver, "api_403")
                self.finished_err.emit(
                    f"Сервер вернул код {resp.status_code}.\n"
                    "Токен найден, но API его не принимает. Проверьте auth_data.json."
                )
                return

            data = resp.json()
            if not data:
                self._log("[!] Пустой ответ API")
                self.finished_err.emit("Пустой ответ от API.")
                return

            self._log(f"[+] Авторизация успешна! Школа: {data[0].get('name')}")
            self.save_session(session)

            if save_credentials(self.username, self.password, self.totp_key):
                self._log("[+] Учётные данные сохранены для следующего запуска")

            self.finished_ok.emit(
                f"Вы вошли!\n\nШкола: {data[0].get('name', 'неизвестно')}\n"
                f"ID школы: {data[0].get('id', '?')}"
            )

        except Exception as e:
            self._log(f"[!] Исключение: {e}")
            self._log(traceback.format_exc())
            self.finished_err.emit(f"Ошибка авторизации:\n{e}")
        finally:
            if driver is not None:
                try:
                    driver.quit()
                    self._log("[i] Браузер закрыт")
                except Exception:
                    pass
            self._log("=== Завершение работы ===")