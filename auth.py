# -*- coding: utf-8 -*-
"""
Класс dn_Auth — авторизация в ЭЖД МЭШ.

Основной способ: Selenium + webdriver-manager + CDP с фильтрацией cookies.
Резервный: cookies браузера через browser_cookie3.

Все файлы сессии — в <папка проекта>/sessions/ (см. paths.py).
"""
import requests
from urllib.parse import urljoin
import pickle
import json
import time
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

from paths import (
    SESSIONS_DIR,
    SESSION_FILE,
    AUTH_DATA_FILE,
    PDOU_TOKEN_FILE,
)


# Домены и приоритеты при фильтрации cookies
DOMAIN_PRIORITY = {
    "dnevnik.mos.ru": 4,
    "school.mos.ru":  3,
    ".mos.ru":        2,
    "mos.ru":         1,
}

KEEP_COOKIES = {
    "auth_token", "aupd_token", "profile_id",
    "JSESSIONID", "session-cookie", "spa_id",
    "sessionid", "session_id", "_identity",
    "csrf_token", "XSRF-TOKEN",
}


def _build_cookie(name, value, domain):
    """Создаёт чистый http.cookiejar.Cookie."""
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


def _copy_to_clean_jar(source) -> CookieJar:
    """
    Копирует cookies из любого итерируемого источника
    в ЧИСТЫЙ http.cookiejar.CookieJar без RLock.
    """
    clean = CookieJar()
    try:
        for c in source:
            try:
                clean.set_cookie(c)
            except Exception:
                pass
    except Exception:
        pass
    return clean


class dn_Auth:
    """Класс для авторизации в ЭЖД с поддержкой разных методов"""

    def __init__(self, dn="work", timeout=30, conn_tm=10):
        self.timeout = timeout
        self.conn_tm = conn_tm
        self.domain = "dnevnik.mos.ru"
        self.base = "https://dnevnik.mos.ru/"
        self.session = None
        self.pid = ""
        self.sid = ""
        self.aid = "14"
        self.curr_aid = "14"

        self.auth_token = ""
        self.profile_id = ""

        self.session_dir = SESSIONS_DIR
        self.session_file = SESSION_FILE
        self.auth_data_file = AUTH_DATA_FILE
        self.pdou_token_file = PDOU_TOKEN_FILE

    # ================================================================
    #  СОХРАНЕНИЕ / ЗАГРУЗКА СЕССИИ
    # ================================================================
    def _save_auth_data(self):
        try:
            data = {
                "auth_token": self.auth_token or "",
                "profile_id": str(self.profile_id or self.pid or ""),
                "school_id": str(self.sid or ""),
            }
            with open(self.auth_data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _load_auth_data(self):
        try:
            if not self.auth_data_file.exists():
                return False
            with open(self.auth_data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.auth_token = data.get("auth_token") or ""
            self.profile_id = str(data.get("profile_id") or "")
            self.pid = self.profile_id or self.pid
            if data.get("school_id"):
                sid_val = data["school_id"]
                self.sid = int(sid_val) if str(sid_val).isdigit() else sid_val
            return bool(self.auth_token)
        except Exception:
            return False

    def save_session(self):
        """Сохраняет cookies в session.pkl как список словарей (без RLock)."""
        if not self.session:
            return False
        try:
            # Собираем cookies как простые dict'ы — 100% безопасно для pickle
            cookies_list = []
            for c in self.session.cookies:
                cookies_list.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                    "secure": bool(c.secure),
                    "expires": c.expires,
                })

            # Гарантируем auth_token и profile_id
            names_present = {item["name"] for item in cookies_list}

            if self.auth_token and "auth_token" not in names_present:
                cookies_list.append({
                    "name": "auth_token", "value": self.auth_token,
                    "domain": "dnevnik.mos.ru", "path": "/",
                    "secure": False, "expires": None,
                })
            pid_val = self.profile_id or self.pid
            if pid_val and "profile_id" not in names_present:
                cookies_list.append({
                    "name": "profile_id", "value": str(pid_val),
                    "domain": "dnevnik.mos.ru", "path": "/",
                    "secure": False, "expires": None,
                })

            with open(self.session_file, 'wb') as f:
                pickle.dump(cookies_list, f)

            self._save_auth_data()
            return True
        except Exception as e:
            print(f"[save_session] Ошибка: {e}", flush=True)
            return False

    def load_session(self):
        try:
            if not self.session_file.exists():
                return False

            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            })

            # Читаем pickle
            with open(self.session_file, 'rb') as f:
                loaded = pickle.load(f)

            # Два варианта: список dict'ов (новый) или CookieJar (старый)
            if isinstance(loaded, list):
                for item in loaded:
                    try:
                        self.session.cookies.set(
                            item.get("name", ""),
                            item.get("value", ""),
                            domain=item.get("domain", "") or "dnevnik.mos.ru",
                            path=item.get("path", "/"),
                        )
                    except Exception:
                        pass
            else:
                # Старый формат: CookieJar или что-то итерируемое
                try:
                    for c in loaded:
                        self.session.cookies.set_cookie(c)
                except Exception:
                    pass

            cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)

            auth_token = cookies_dict.get("auth_token")
            profile_id = cookies_dict.get("profile_id")

            if not auth_token:
                if self._load_auth_data():
                    auth_token = self.auth_token
                    profile_id = profile_id or self.profile_id

            if not auth_token:
                return False

            self.auth_token = auth_token
            self.profile_id = str(profile_id or "")
            self.pid = self.profile_id

            self.session.cookies.set("auth_token", auth_token,
                                     domain="dnevnik.mos.ru")
            if self.profile_id:
                self.session.cookies.set("profile_id", self.profile_id,
                                         domain="dnevnik.mos.ru")

            self.session.headers.update({
                'Auth-Token': auth_token,
                'Authorization': f'Bearer {auth_token}',
            })
            if self.profile_id:
                self.session.headers.update({'Profile-Id': self.profile_id})

            response = self.session.get(
                urljoin(self.base, "core/api/schools"),
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if data:
                    self.sid = data[0]["id"]
                    return True
            return False

        except Exception as e:
            print(f"[load_session] Ошибка: {e}", flush=True)
            return False

    # ================================================================
    #  ПДОУ-токен
    # ================================================================
    def _save_pdou_token_if_free(self, auth_token_from_profile: str,
                                 user_name: str, log=None) -> bool:
        try:
            existing = {}
            if self.pdou_token_file.exists():
                try:
                    existing = json.loads(
                        self.pdou_token_file.read_text(encoding="utf-8")
                    )
                except Exception:
                    existing = {}

            existing_user = (existing.get("user_name") or "").strip()
            current_user = (user_name or "").strip()

            if existing.get("aupd_token") and existing_user and existing_user != current_user:
                if log:
                    log(f"[i] pdou_token.json — токен от '{existing_user}', не трогаю.")
                return False

            self.pdou_token_file.write_text(
                json.dumps({
                    "aupd_token": auth_token_from_profile,
                    "user_name": current_user,
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "selenium",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if log:
                log(f"[+] authentication_token сохранён в {self.pdou_token_file}")
            return True
        except Exception as e:
            if log:
                log(f"[!] Не удалось сохранить pdou_token.json: {e}")
            return False

    # ================================================================
    #  Selenium-авторизация
    # ================================================================
    def login_with_selenium_advanced(self, username, password,
                                     totp_key=None, browser='chrome',
                                     log_callback=None,
                                     gui_confirm_callback=None,
                                     pdou_mode=False):
        import tempfile
        import traceback

        def log(msg):
            if log_callback:
                log_callback(msg)
            else:
                print(msg, flush=True)

        driver = None
        keep_browser_open = False

        try:
            log("=== Начало авторизации через Selenium ===")
            log(f"[i] Логин: {username}")
            log(f"[i] 2FA: {'TOTP' if totp_key else 'SMS вручную'}")
            log(f"[i] Режим: {'ПДОУ' if pdou_mode else 'ЭЖД'}")
            log(f"[i] Папка сессий: {SESSIONS_DIR}")

            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            if browser == 'firefox':
                from selenium.webdriver.firefox.options import Options as FirefoxOptions
                from selenium.webdriver.firefox.service import Service as FirefoxService
                from webdriver_manager.firefox import GeckoDriverManager
                options = FirefoxOptions()
                driver_path = GeckoDriverManager().install()
                service = FirefoxService(executable_path=driver_path)
                driver = webdriver.Firefox(service=service, options=options)
            else:
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
                log("[i] Скачиваю ChromeDriver...")
                driver_path = ChromeDriverManager().install()
                log(f"[+] ChromeDriver: {driver_path}")
                service = ChromeService(executable_path=driver_path)
                driver = webdriver.Chrome(service=service, options=options)
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
                )
            log("[+] Браузер запущен")

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
            log("[i] Открываю страницу входа...")
            driver.get(login_url)
            wait = WebDriverWait(driver, 30)
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(2)
            log("[+] Страница загружена")

            # Логин
            log("[i] Ввожу логин...")
            time.sleep(1.5)
            login_el = wait.until(EC.element_to_be_clickable((By.ID, "login")))
            login_el.click()
            time.sleep(0.5)
            login_el.clear()
            login_el.send_keys(username)
            log("[+] Логин введён")

            # Пароль
            log("[i] Ввожу пароль...")
            time.sleep(1.5)
            pass_el = wait.until(EC.element_to_be_clickable((By.ID, "password")))
            pass_el.click()
            time.sleep(0.5)
            pass_el.clear()
            pass_el.send_keys(password)
            log("[+] Пароль введён")

            # Кнопка «Войти»
            log("[i] Ищу кнопку 'Войти'...")
            time.sleep(1.5)
            submit = None
            for by, value in [
                (By.ID, "bind"),
                (By.CSS_SELECTOR, "button.bc-form-btn"),
                (By.XPATH, "//button[contains(., 'Войти')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ]:
                try:
                    submit = wait.until(EC.element_to_be_clickable((by, value)))
                    log(f"[+] Кнопка найдена: {by}={value}")
                    break
                except Exception:
                    continue

            if submit is None:
                raise Exception("Не удалось найти кнопку 'Войти'")

            submit.click()
            log("[+] Кнопка нажата")
            time.sleep(3)

            # 2FA
            if "methods2" in driver.current_url:
                log("[+] Требуется 2FA")
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

                if totp_key:
                    import pyotp
                    code = pyotp.TOTP(totp_key).now()
                    log(f"[+] TOTP-код: {code}")
                    time.sleep(1)
                    otp_input.click()
                    otp_input.send_keys(code)
                    log("[+] TOTP-код введён")
                    time.sleep(3)
                else:
                    log("[!] Введите SMS-код вручную в браузере (5 минут).")
                    end = time.time() + 300
                    while time.time() < end and "login.mos.ru" in driver.current_url:
                        time.sleep(1)
                    if "login.mos.ru" in driver.current_url:
                        raise Exception("Таймаут ожидания ручного ввода SMS")
                    log("[+] Вход выполнен вручную")

            # Ждём редирект
            log("[i] Жду редирект на school.mos.ru...")
            end = time.time() + 60
            while time.time() < end:
                if ("school.mos.ru" in driver.current_url
                        and "/auth/callback" not in driver.current_url):
                    break
                time.sleep(1)
            log(f"[+] Текущий URL: {driver.current_url}")
            time.sleep(3)

            # Переходим на dnevnik
            log("[i] Перехожу на dnevnik.mos.ru...")
            try:
                driver.get("https://dnevnik.mos.ru/")
                end = time.time() + 20
                opened = False
                while time.time() < end:
                    if "dnevnik.mos.ru" in driver.current_url:
                        log(f"[+] Открыт dnevnik.mos.ru: {driver.current_url}")
                        opened = True
                        break
                    time.sleep(1)
                if not opened:
                    log(f"[!] Не удалось открыть dnevnik.mos.ru. URL: {driver.current_url}")
                    try:
                        driver.get("https://dnevnik.mos.ru/diary")
                        time.sleep(5)
                    except Exception as e:
                        log(f"[!] /diary тоже не открылся: {e}")
                time.sleep(5)
                log(f"[+] Финальный URL: {driver.current_url}")
            except Exception as e:
                log(f"[!] Не удалось перейти: {e}")

            # ============================================================
            #  СОБИРАЕМ COOKIES С ФИЛЬТРАЦИЕЙ
            # ============================================================
            log("[i] Собираю cookies (с фильтрацией по домену)...")

            best_cookies = {}
            raw_count = 0

            try:
                result = driver.execute_cdp_cmd("Network.getAllCookies", {})
                raw_cookies = result.get("cookies", [])
                raw_count = len(raw_cookies)
                for c in raw_cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    domain = c.get("domain", "")
                    if not name or not value:
                        continue
                    priority = 0
                    for d, p in DOMAIN_PRIORITY.items():
                        if d in domain:
                            priority = p
                            break
                    if priority == 0:
                        continue
                    is_important = name in KEEP_COOKIES
                    is_our_domain = ("dnevnik.mos.ru" in domain
                                     or "school.mos.ru" in domain)
                    if not (is_important or is_our_domain):
                        continue
                    old = best_cookies.get(name)
                    if old is None or priority > old[0]:
                        best_cookies[name] = (priority, value, domain)
                log(f"[i] CDP: отобрано {len(best_cookies)} cookies из {raw_count}")
            except Exception as e:
                log(f"[!] CDP getAllCookies: {e}")

            # Дополнительно — driver.get_cookies()
            try:
                for c in driver.get_cookies():
                    name = c.get("name")
                    value = c.get("value")
                    domain = c.get("domain", "")
                    if not name or not value:
                        continue
                    old = best_cookies.get(name)
                    if old is None or 5 > old[0]:
                        best_cookies[name] = (5, value, domain)
            except Exception as e:
                log(f"[!] driver.get_cookies: {e}")

            all_cookies = {name: v[1] for name, v in best_cookies.items()}
            cookie_domains = {name: v[2] for name, v in best_cookies.items()}

            log(f"[i] Итог: cookies={len(all_cookies)}")
            for name, domain in sorted(cookie_domains.items()):
                log(f"    - {name}  ({domain})")

            # Токен из storage
            token_from_storage = None
            try:
                token_from_storage = driver.execute_script("""
                    return window.sessionStorage.getItem('auth_token')
                        || window.localStorage.getItem('auth_token')
                        || window.sessionStorage.getItem('token')
                        || window.localStorage.getItem('token')
                        || window.sessionStorage.getItem('access_token')
                        || window.localStorage.getItem('access_token')
                        || null;
                """)
            except Exception as e:
                log(f"[!] localStorage/sessionStorage: {e}")

            if token_from_storage:
                log(f"[+] auth_token найден в storage: {str(token_from_storage)[:30]}...")
                all_cookies["auth_token"] = token_from_storage
                cookie_domains["auth_token"] = "storage"

            profile_id = None
            try:
                profile_id = driver.execute_script("""
                    return window.sessionStorage.getItem('profile_id')
                        || window.localStorage.getItem('profile_id')
                        || null;
                """)
            except Exception:
                pass
            if not profile_id:
                profile_id = all_cookies.get("profile_id")

            log(f"[i] auth_token={'✅' if 'auth_token' in all_cookies else '❌'}, "
                f"profile_id={profile_id or '❌'}")

            if not all_cookies:
                log("[!] Не удалось получить ни одной cookies")
                return False

            # ============================================================
            #  СОЗДАЁМ СЕССИЮ
            # ============================================================
            log(f"[i] Создаю requests.Session с {len(all_cookies)} cookies...")
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/152.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            })

            for name, value in all_cookies.items():
                domain = cookie_domains.get(name, "")
                if "school.mos.ru" in domain:
                    self.session.cookies.set(name, value, domain="school.mos.ru")
                else:
                    self.session.cookies.set(name, value, domain="dnevnik.mos.ru")

            if "auth_token" in all_cookies:
                self.auth_token = all_cookies["auth_token"]
                self.profile_id = str(profile_id or all_cookies.get("profile_id", "") or "")
                self.pid = self.profile_id
                self.session.headers.update({
                    "Auth-Token": self.auth_token,
                    "Authorization": f"Bearer {self.auth_token}",
                })
                if self.pid:
                    self.session.headers.update({"Profile-Id": self.pid})
                log(f"[+] Auth-Token установлен, profile_id={self.pid}")
            else:
                log("[!] auth_token отсутствует — API вернёт 403")

            # Проверка API
            log("[i] Проверяю авторизацию: GET core/api/schools")
            api_ok = False
            try:
                response = self.session.get(
                    urljoin(self.base, "core/api/schools"),
                    timeout=self.timeout
                )
                log(f"[i] HTTP {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        self.sid = data[0]["id"]
                        log(f"[+] Авторизация успешна! Школа: {data[0].get('name')}")
                        api_ok = True
                else:
                    log(f"[!] HTTP {response.status_code}: {response.text[:200]}")
            except Exception as e:
                log(f"[!] Ошибка запроса: {e}")

            # Профиль для ПДОУ-токена
            authentication_token = ""
            user_name = ""
            try:
                prof_resp = self.session.get(
                    urljoin(self.base, "core/api/profile"),
                    timeout=self.timeout
                )
                if prof_resp.status_code == 200:
                    pdata = prof_resp.json()
                    authentication_token = pdata.get("authentication_token") or ""
                    last = pdata.get("last_name", "")
                    first = pdata.get("first_name", "")
                    user_name = f"{last} {first}".strip()
                    log(f"[i] Профиль: {user_name}, "
                        f"authentication_token={'✅' if authentication_token else '❌'}")
            except Exception as e:
                log(f"[!] Не удалось получить /core/api/profile: {e}")

            # Режим ПДОУ
            if pdou_mode:
                if not authentication_token:
                    log("[!] Нет authentication_token — нечего сохранять")
                    return False
                try:
                    self.pdou_token_file.write_text(
                        json.dumps({
                            "aupd_token": authentication_token,
                            "user_name": user_name,
                            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "source": "selenium_pdou_mode",
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    log(f"[+] ПДОУ-токен сохранён в {self.pdou_token_file}")
                except Exception as e:
                    log(f"[!] Не удалось сохранить pdou_token.json: {e}")
                    return False
                log("[i] ЭЖД-сессия не изменена (режим ПДОУ).")
            else:
                if api_ok:
                    self.save_session()
                    log(f"[+] Сессия сохранена: {self.session_file}")
                if authentication_token:
                    self._save_pdou_token_if_free(
                        authentication_token, user_name, log=log
                    )

            # GUI: попап
            if gui_confirm_callback is not None:
                keep_browser_open = True
                try:
                    gui_confirm_callback(driver, self)
                except Exception as e:
                    log(f"[!] GUI callback error: {e}")
                    keep_browser_open = False
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None

            return api_ok or ("auth_token" in all_cookies)

        except Exception as e:
            log(f"[!] Ошибка Selenium-авторизации: {e}")
            log(traceback.format_exc())
            return False
        finally:
            if driver is not None and not keep_browser_open:
                try:
                    driver.quit()
                    log("[i] Браузер закрыт (finally)")
                except Exception:
                    pass

    # ================================================================
    #  Резерв: cookies из браузера
    # ================================================================
    def login_from_browser(self, browser='auto'):
        import browser_cookie3

        try:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            })

            cookies = None
            browsers_to_try = []
            if browser == 'auto':
                browsers_to_try = [
                    ('firefox', browser_cookie3.firefox),
                    ('chrome', browser_cookie3.chrome),
                    ('edge', browser_cookie3.edge),
                    ('opera', browser_cookie3.opera),
                    ('brave', browser_cookie3.brave)
                ]
            else:
                browser_map = {
                    'firefox': browser_cookie3.firefox,
                    'chrome': browser_cookie3.chrome,
                    'edge': browser_cookie3.edge,
                    'opera': browser_cookie3.opera,
                    'brave': browser_cookie3.brave
                }
                if browser in browser_map:
                    browsers_to_try = [(browser, browser_map[browser])]

            for browser_name, browser_func in browsers_to_try:
                try:
                    cookies = browser_func(domain_name=self.domain)
                    break
                except Exception:
                    continue

            if not cookies:
                return False

            for cookie in cookies:
                if cookie.name and cookie.value:
                    self.session.cookies.set(cookie.name, cookie.value,
                                              domain=self.domain)

            cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)
            if "profile_id" not in cookies_dict:
                return False

            self.pid = cookies_dict["profile_id"]
            self.profile_id = self.pid
            self.auth_token = cookies_dict.get("auth_token", "")

            if "auth_token" in cookies_dict:
                self.session.headers.update({
                    'Auth-Token': cookies_dict["auth_token"],
                    'Authorization': f'Bearer {cookies_dict["auth_token"]}',
                    'Profile-Id': self.pid
                })

            response = self.session.get(
                urljoin(self.base, "core/api/schools"),
                timeout=self.timeout
            )

            if response.status_code != 200:
                return False

            data = response.json()
            if not data:
                return False

            self.sid = data[0]["id"]
            self.save_session()
            return True

        except Exception:
            return False

    # ================================================================
    #  FETCH
    # ================================================================
    def fetch(self, url, params=None):
        if not self.session:
            return None
        try:
            full_url = url if url.startswith('http') else urljoin(self.base, url)
            response = self.session.get(full_url, params=params, timeout=self.timeout)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None

    def fetch_paginated(self, url, params=None, page_size=1000):
        if not self.session:
            return None
        if params is None:
            params = {}
        all_data = []
        page = 1
        while True:
            params['page'] = page
            data = self.fetch(url, params)
            if not data:
                break
            all_data.extend(data)
            if len(data) < page_size:
                break
            page += 1
        return all_data