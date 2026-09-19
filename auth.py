# -*- coding: utf-8 -*-
"""
Класс dn_Auth — авторизация в ЭЖД МЭШ.

Основной способ: Selenium + webdriver-manager + CDP.
Резервный: cookies браузера через browser_cookie3.
"""
import requests
from urllib.parse import urljoin
import pickle
from pathlib import Path
import time


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
        self.aid = "13"  # ID учебного года 2025-2026
        self.curr_aid = "13"

        # Директория для сохранения сессий
        self.session_dir = Path.home() / '.ejd_checker'
        self.session_dir.mkdir(exist_ok=True)
        self.session_file = self.session_dir / 'session.pkl'

    # ================================================================
    #  СОХРАНЕНИЕ / ЗАГРУЗКА СЕССИИ
    # ================================================================
    def save_session(self):
        """Сохраняет сессию для повторного использования"""
        if self.session:
            try:
                with open(self.session_file, 'wb') as f:
                    pickle.dump(self.session.cookies, f)
                return True
            except Exception:
                return False
        return False

    def load_session(self):
        """Загружает сохраненную сессию и проверяет её через API"""
        try:
            if self.session_file.exists():
                self.session = requests.Session()
                self.session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                })

                with open(self.session_file, 'rb') as f:
                    cookies = pickle.load(f)
                    self.session.cookies.update(cookies)

                # Проверяем, работает ли сессия
                response = self.session.get(
                    urljoin(self.base, "core/api/schools"),
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    data = response.json()
                    if data:
                        self.sid = data[0]["id"]
                        cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)
                        self.pid = cookies_dict.get("profile_id", "")

                        if "auth_token" in cookies_dict:
                            self.session.headers.update({
                                'Auth-Token': cookies_dict["auth_token"],
                                'Profile-Id': self.pid
                            })
                        return True
        except Exception:
            pass
        return False

    # ================================================================
    #  АВТОРИЗАЦИЯ ЧЕРЕЗ SELENIUM (ОСНОВНОЙ СПОСОБ)
    # ================================================================
    def login_with_selenium_advanced(self, username, password,
                                     totp_key=None, browser='chrome',
                                     log_callback=None):
        """
        Продвинутая авторизация через Selenium с поддержкой 2FA
        и получением cookies dnevnik.mos.ru.

        Args:
            username: логин (телефон, email, СНИЛС)
            password: пароль
            totp_key: TOTP-ключ (если 2FA через приложение)
            browser: 'chrome' или 'firefox'
            log_callback: функция для логирования

        Returns:
            bool — успех авторизации
        """
        import tempfile
        import traceback

        def log(msg):
            if log_callback:
                log_callback(msg)
            else:
                print(msg, flush=True)

        driver = None
        try:
            log("=== Начало авторизации через Selenium ===")
            log(f"[i] Логин: {username}")
            log(f"[i] 2FA: {'TOTP' if totp_key else 'SMS вручную'}")

            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            # --- Создаём драйвер ---
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

                log("[i] Скачиваю ChromeDriver...")
                driver_path = ChromeDriverManager().install()
                log(f"[+] ChromeDriver: {driver_path}")

                service = ChromeService(executable_path=driver_path)
                driver = webdriver.Chrome(service=service, options=options)

                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": "Object.defineProperty(navigator, 'webdriver', "
                               "{get: () => undefined})"},
                )

            log("[+] Браузер запущен")

            # ============================================================
            #  ШАГ 1: Открываем страницу входа
            # ============================================================
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

            # ============================================================
            #  ШАГ 2: Вводим логин
            # ============================================================
            log("[i] Ввожу логин...")
            time.sleep(1.5)
            login_el = wait.until(EC.element_to_be_clickable((By.ID, "login")))
            login_el.click()
            time.sleep(0.5)
            login_el.clear()
            login_el.send_keys(username)
            log("[+] Логин введён")

            # ============================================================
            #  ШАГ 3: Вводим пароль
            # ============================================================
            log("[i] Ввожу пароль...")
            time.sleep(1.5)
            pass_el = wait.until(EC.element_to_be_clickable((By.ID, "password")))
            pass_el.click()
            time.sleep(0.5)
            pass_el.clear()
            pass_el.send_keys(password)
            log("[+] Пароль введён")

            # ============================================================
            #  ШАГ 4: Нажимаем кнопку «Войти»
            # ============================================================
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

            # ============================================================
            #  ШАГ 5: 2FA
            # ============================================================
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

            # ============================================================
            #  ШАГ 6: Ждём редирект на school.mos.ru
            # ============================================================
            log("[i] Жду редирект на school.mos.ru...")
            end = time.time() + 60
            while time.time() < end:
                if "school.mos.ru" in driver.current_url and "/auth/callback" not in driver.current_url:
                    break
                time.sleep(1)
            log(f"[+] Текущий URL: {driver.current_url}")
            time.sleep(3)  # даём приложению school.mos.ru загрузиться

            # ============================================================
            #  ШАГ 7: Переход на dnevnik.mos.ru
            # ============================================================
            log("[i] Перехожу на dnevnik.mos.ru для получения cookies...")
            try:
                driver.get("https://dnevnik.mos.ru/")

                # Ждём до 15 секунд, пока URL действительно станет dnevnik.mos.ru
                end = time.time() + 15
                dnevnik_opened = False
                while time.time() < end:
                    current = driver.current_url
                    if "dnevnik.mos.ru" in current:
                        log(f"[+] Открыт dnevnik.mos.ru: {current}")
                        dnevnik_opened = True
                        break
                    time.sleep(1)

                if not dnevnik_opened:
                    log(f"[!] Не удалось открыть dnevnik.mos.ru. Текущий URL: {driver.current_url}")
                    log("[i] Пробую открыть напрямую /diary...")
                    driver.get("https://dnevnik.mos.ru/diary")
                    time.sleep(5)

                # Даём время на установку cookies
                time.sleep(5)
                log(f"[+] Финальный URL: {driver.current_url}")
            except Exception as e:
                log(f"[!] Не удалось перейти: {e}")

            # ============================================================
            #  ШАГ 8: Сбор cookies ВСЕХ доменов через CDP
            # ============================================================
            log("[i] Собираю cookies всех доменов через CDP...")
            all_cookies = {}
            school_cookies = {}
            dnevnik_cookies = {}

            try:
                result = driver.execute_cdp_cmd("Network.getAllCookies", {})
                total = len(result.get("cookies", []))
                log(f"[i] Всего cookies (все домены): {total}")

                for c in result.get("cookies", []):
                    domain = c.get("domain", "")
                    name = c.get("name", "")
                    value = c.get("value", "")

                    # Логируем важные cookies
                    if name in ("auth_token", "profile_id", "is_auth",
                                "session-cookie", "spa_id", "aid", "aupd_token"):
                        log(f"    [{domain}] {name} = {str(value)[:40]}...")

                    if "dnevnik.mos.ru" in domain:
                        dnevnik_cookies[name] = value
                    if "school.mos.ru" in domain:
                        school_cookies[name] = value

                log(f"[+] Cookies dnevnik.mos.ru: {len(dnevnik_cookies)}")
                log(f"[+] Cookies school.mos.ru: {len(school_cookies)}")

                # Приоритет: сначала school.mos.ru, потом dnevnik.mos.ru
                all_cookies.update(school_cookies)
                all_cookies.update(dnevnik_cookies)

            except Exception as e:
                log(f"[!] CDP getAllCookies не сработал: {e}")
                log("[i] Fallback — беру только текущий домен")
                for c in driver.get_cookies():
                    all_cookies[c["name"]] = c["value"]

            # ============================================================
            #  ШАГ 9: Если auth_token не найден — повторный переход
            # ============================================================
            if "auth_token" not in all_cookies:
                log("[!] auth_token не найден ни в одном домене!")
                log("[i] Пробую ещё раз перейти на dnevnik.mos.ru/diary...")
                try:
                    driver.get("https://dnevnik.mos.ru/diary")
                    time.sleep(8)
                    log(f"[+] Текущий URL: {driver.current_url}")

                    result = driver.execute_cdp_cmd("Network.getAllCookies", {})
                    for c in result.get("cookies", []):
                        domain = c.get("domain", "")
                        name = c.get("name", "")
                        value = c.get("value", "")
                        if "dnevnik.mos.ru" in domain:
                            dnevnik_cookies[name] = value
                            all_cookies[name] = value

                    log(f"[+] После повторного перехода cookies dnevnik.mos.ru: {len(dnevnik_cookies)}")
                    if "auth_token" in dnevnik_cookies:
                        log("[+] auth_token найден!")
                    else:
                        log("[!] auth_token всё ещё отсутствует")
                except Exception as e:
                    log(f"[!] Повторный переход не удался: {e}")

            # ============================================================
            #  ШАГ 10: Создаём сессию с cookies
            # ============================================================
            if not all_cookies:
                log("[!] Не удалось получить ни одной cookies")
                return False

            log(f"[i] Создаю requests.Session с {len(all_cookies)} cookies...")
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            })

            # Ставим cookies сразу для обоих доменов
            for name, value in all_cookies.items():
                self.session.cookies.set(name, value, domain="dnevnik.mos.ru")
                self.session.cookies.set(name, value, domain="school.mos.ru")

            cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)
            log(f"[i] Cookies в сессии: {list(cookies_dict.keys())}")

            # Устанавливаем заголовки
            if "auth_token" in cookies_dict:
                self.session.headers.update({
                    'Auth-Token': cookies_dict["auth_token"],
                    'Profile-Id': cookies_dict.get("profile_id", ""),
                })
                self.pid = cookies_dict.get("profile_id", "")
                log(f"[+] Auth-Token установлен, profile_id = {self.pid}")
            else:
                log("[!] auth_token отсутствует — API вернёт 403")

            # ============================================================
            #  ШАГ 11: Проверяем API
            # ============================================================
            log("[i] Проверяю авторизацию: GET core/api/schools")
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
                        self.save_session()
                        log(f"[+] Сессия сохранена: {self.session_file}")
                        return True
                    else:
                        log("[!] Пустой ответ API")
                elif response.status_code == 403:
                    log("[!] 403 Forbidden — cookies не подходят для API")
                    log("[i] Текст ответа: " + response.text[:200])
                else:
                    log(f"[!] Неожиданный HTTP {response.status_code}")
                    log(f"[i] Текст: {response.text[:200]}")
            except Exception as e:
                log(f"[!] Ошибка запроса к API: {e}")

            return False

        except Exception as e:
            log(f"[!] Ошибка Selenium-авторизации: {e}")
            log(traceback.format_exc())
            return False
        finally:
            if driver is not None:
                try:
                    driver.quit()
                    log("[i] Браузер закрыт")
                except Exception:
                    pass

    # ================================================================
    #  РЕЗЕРВНЫЙ СПОСОБ: АВТОРИЗАЦИЯ ЧЕРЕЗ COOKIES БРАУЗЕРА
    # ================================================================
    def login_from_browser(self, browser='auto'):
        """
        Авторизация через куки браузера (резервный способ).
        Работает, если пользователь уже авторизован в Firefox/Chrome/Edge
        на dnevnik.mos.ru.
        """
        import browser_cookie3

        try:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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
                    for cookie in cookies:
                        if cookie.name == "is_auth" and cookie.value == "true":
                            break
                    break
                except Exception:
                    continue

            if not cookies:
                return False

            for cookie in cookies:
                if cookie.name and cookie.value:
                    self.session.cookies.set(cookie.name, cookie.value, domain=self.domain)

            cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)
            if "profile_id" not in cookies_dict:
                return False

            self.pid = cookies_dict["profile_id"]

            if "auth_token" in cookies_dict:
                self.session.headers.update({
                    'Auth-Token': cookies_dict["auth_token"],
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
    #  FETCH-МЕТОДЫ
    # ================================================================
    def fetch(self, url, params=None):
        """Выполнение GET-запроса через requests"""
        if not self.session:
            return None

        try:
            if url.startswith('http'):
                full_url = url
            else:
                full_url = urljoin(self.base, url)

            response = self.session.get(full_url, params=params, timeout=self.timeout)

            if response.status_code != 200:
                return None

            return response.json()
        except Exception:
            return None

    def fetch_paginated(self, url, params=None, page_size=1000):
        """Выполнение запроса с пагинацией"""
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