# -*- coding: utf-8 -*-
"""
session_monitor.py — мониторинг появления auth_token в Chrome через CDP.

Работает по сценарию B: пользователь сам залогинен в обычном Chrome,
запущенном с флагом --remote-debugging-port=9222.

Что делает:
  1. Каждые N секунд подключается к Chrome (порт 9222).
  2. Читает sessionStorage / localStorage / cookies во всех вкладках mos.ru.
  3. Как только находит auth_token — проверяет через API dnevnik.mos.ru.
  4. Если ок — сохраняет session.pkl + auth_data.json в ~/.zavuch2/.
  5. НЕ закрывает браузер пользователя (это ключевое!).

Запуск:
    python session_monitor.py

Опции:
    --interval 3     Интервал опроса (сек)
    --timeout 1800   Общий таймаут (сек)
    --port 9222      Порт CDP
    --continuous     Не останавливаться после первой удачной сессии
"""
import argparse
import json
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
AUTH_DATA_FILE = DATA_DIR / "auth_data.json"

TARGET_DOMAINS = ("dnevnik.mos.ru", "school.mos.ru", "mos.ru")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ============================================================
#  CDP: подключение и чтение
# ============================================================
def connect_cdp(port: int):
    """
    Подключается к запущенному Chrome через CDP.
    Возвращает webdriver-объект или None.

    ВАЖНО: мы НЕ закрываем этот Chrome. Он принадлежит пользователю.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as e:
        log(f"[CDP] Не установлены selenium/webdriver-manager: {e}")
        return None

    try:
        options = Options()
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")

        service = Service(executable_path=ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        log(f"[CDP] Не удалось подключиться к Chrome на порту {port}: {e}")
        log(f"[CDP] Убедитесь, что Chrome запущен с --remote-debugging-port={port}")
        return None


def read_storage_from_tabs(driver) -> dict:
    """
    Обходит все вкладки, читает storage на тех, где открыт mos.ru.
    Возвращает dict: {"auth_token": ..., "profile_id": ..., "cookies": {...}}
    """
    result = {"auth_token": None, "profile_id": None, "cookies": {}}

    # 1. Cookies со всех доменов
    try:
        res = driver.execute_cdp_cmd("Network.getAllCookies", {})
        for c in res.get("cookies", []):
            name = c.get("name")
            value = c.get("value")
            domain = c.get("domain", "")
            if name and value and any(d in domain for d in TARGET_DOMAINS):
                result["cookies"][name] = value
    except Exception as e:
        log(f"[CDP] getAllCookies ошибка: {e}")

    # 2. Storage по вкладкам
    original_window = None
    try:
        original_window = driver.current_window_handle
    except Exception:
        pass

    for win in driver.window_handles:
        try:
            driver.switch_to.window(win)
            url = driver.current_url or ""
            if "mos.ru" not in url:
                continue

            # Читаем sessionStorage и localStorage
            storage_data = driver.execute_script("""
                function getStorage(s) {
                    var out = {};
                    for (var i = 0; i < s.length; i++) {
                        var k = s.key(i);
                        out[k] = s.getItem(k);
                    }
                    return out;
                }
                return {
                    ss: getStorage(window.sessionStorage),
                    ls: getStorage(window.localStorage)
                };
            """)

            if not storage_data:
                continue

            ss = storage_data.get("ss", {}) or {}
            ls = storage_data.get("ls", {}) or {}

            # Ищем auth_token
            token_candidates = [
                ss.get("auth_token"), ss.get("token"), ss.get("access_token"),
                ls.get("auth_token"), ls.get("token"), ls.get("access_token"),
            ]
            for t in token_candidates:
                if t and len(str(t)) > 10:
                    result["auth_token"] = t
                    log(f"[CDP] auth_token найден в {url[:70]}")
                    break

            # Ищем profile_id
            pid_candidates = [
                ss.get("profile_id"), ss.get("pid"),
                ls.get("profile_id"), ls.get("pid"),
            ]
            for p in pid_candidates:
                if p:
                    result["profile_id"] = p
                    break

            if result["auth_token"] and result["profile_id"]:
                break
        except Exception:
            continue

    # 3. Возвращаемся на исходную вкладку (чтобы не мешать пользователю)
    try:
        if original_window:
            driver.switch_to.window(original_window)
    except Exception:
        pass

    # 4. Фолбэк: если токен не в storage — может, в cookies
    if not result["auth_token"]:
        result["auth_token"] = result["cookies"].get("auth_token")
    if not result["profile_id"]:
        result["profile_id"] = result["cookies"].get("profile_id")

    return result


def detach_driver(driver):
    """
    Отключается от Chrome БЕЗ закрытия браузера.
    Просто завершает сессию chromedriver, оставляя Chrome живым.
    """
    if driver is None:
        return
    try:
        # Отключаем сервис — Chrome остаётся работать, т.к. это не наш Chrome.
        driver.service.stop()
    except Exception:
        pass


# ============================================================
#  Проверка и сохранение
# ============================================================
def verify_and_save(source: dict) -> bool:
    if not source or not source.get("auth_token"):
        return False

    auth_token = source["auth_token"]
    profile_id = source.get("profile_id") or ""
    cookies = source.get("cookies", {})

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/152.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Auth-Token": auth_token,
        "Authorization": f"Bearer {auth_token}",
    })
    if profile_id:
        session.headers["Profile-Id"] = str(profile_id)

    for name, value in cookies.items():
        session.cookies.set(name, value, domain="dnevnik.mos.ru")
        session.cookies.set(name, value, domain="school.mos.ru")
    session.cookies.set("auth_token", auth_token, domain="dnevnik.mos.ru")
    if profile_id:
        session.cookies.set("profile_id", str(profile_id), domain="dnevnik.mos.ru")

    try:
        resp = session.get("https://dnevnik.mos.ru/core/api/schools", timeout=15)
    except Exception as e:
        log(f"[API] Ошибка запроса: {e}")
        return False

    if resp.status_code != 200:
        log(f"[API] HTTP {resp.status_code} — токен не принят")
        log(f"[API] Тело: {resp.text[:200]}")
        return False

    try:
        data = resp.json()
    except Exception:
        log("[API] Не JSON в ответе")
        return False

    if not data:
        log("[API] Пустой ответ")
        return False

    school_name = data[0].get("name", "?")
    sid = data[0].get("id", "")

    try:
        with open(SESSION_FILE, "wb") as f:
            pickle.dump(session.cookies, f)
        with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "auth_token": auth_token,
                "profile_id": str(profile_id),
                "school_id": str(sid),
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[SAVE] Ошибка сохранения: {e}")
        return False

    log(f"✅ Сессия сохранена. Школа: {school_name}")
    log(f"   📄 {SESSION_FILE}")
    log(f"   📄 {AUTH_DATA_FILE}")
    return True


# ============================================================
#  Главный цикл
# ============================================================
def monitor(interval: float = 3.0,
            timeout: float = 1800.0,
            port: int = 9222,
            continuous: bool = False) -> bool:

    log("=" * 60)
    log(" Монитор сессии zavuch 2")
    log("=" * 60)
    log(f" CDP-порт: {port}")
    log(f" Интервал: {interval} сек")
    log(f" Таймаут:  {timeout} сек")
    log(f" Режим:    {'continuous' if continuous else 'single-shot'}")
    log("")
    log(" ⚠️  Убедитесь, что Chrome запущен с флагом:")
    log(f"     --remote-debugging-port={port}")
    log("")
    log(" Ходите по dnevnik.mos.ru — я слежу за появлением токена.")
    log("=" * 60)
    log("")

    start = time.time()
    attempt = 0
    found = False

    while time.time() - start < timeout:
        attempt += 1

        driver = connect_cdp(port)
        if driver is None:
            log(f"[#{attempt}] Chrome недоступен. Жду {interval} сек...")
            time.sleep(interval)
            continue

        try:
            source = read_storage_from_tabs(driver)

            has_token = bool(source.get("auth_token"))
            has_pid = bool(source.get("profile_id"))
            n_cookies = len(source.get("cookies", {}))

            log(f"[#{attempt}] cookies={n_cookies} "
                f"auth_token={'✅' if has_token else '❌'} "
                f"profile_id={'✅' if has_pid else '❌'}")

            if has_token:
                if verify_and_save(source):
                    found = True
                    if not continuous:
                        log("🛑 Токен получен и сохранён. Завершаю работу.")
                        return True
                    else:
                        log("🔁 continuous: продолжаю следить.")
                else:
                    log("[!] Токен есть, но API не принял — жду дальше.")
        finally:
            detach_driver(driver)

        time.sleep(interval)

    log("")
    if found:
        log("⏰ Таймаут после успешного сохранения.")
    else:
        log("⏰ Таймаут. Токен не найден.")
    return found


# ============================================================
#  CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Мониторинг auth_token в Chrome через CDP"
    )
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Интервал опроса (сек)")
    parser.add_argument("--timeout", type=float, default=1800.0,
                        help="Общий таймаут (сек)")
    parser.add_argument("--port", type=int, default=9222,
                        help="Порт CDP Chrome")
    parser.add_argument("--continuous", action="store_true",
                        help="Не останавливаться после первой удачи")
    args = parser.parse_args()

    ok = monitor(
        interval=args.interval,
        timeout=args.timeout,
        port=args.port,
        continuous=args.continuous,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()