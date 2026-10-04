# -*- coding: utf-8 -*-
"""
save_tokens_to_session.py

Сохраняет auth_token (и опционально другие cookies) в ~/.zavuch2/.
Проверяет через разные API-эндпоинты, какой из них принимает токен.

Как пользоваться:
  1. Запустите: python save_tokens_to_session.py --token "ВСТАВЬТЕ_ТОКЕН"
     Или вставьте токен в clipboard и запустите без --token.
  2. Скрипт попробует несколько API и скажет, что работает.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import requests


from paths import SESSION_FILE, AUTH_DATA_FILE


def log(msg):
    print(msg, flush=True)


def get_from_clipboard() -> str:
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        try:
            text = r.clipboard_get()
        except Exception:
            text = ""
        r.destroy()
        return (text or "").strip()
    except Exception as e:
        log(f"[clipboard] {e}")
        return ""


def try_decode_jwt(token: str) -> dict:
    """Декодирует payload JWT без проверки подписи (только для чтения полей)."""
    import base64
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1]
        # Дополняем padding
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        log(f"[jwt] Не удалось декодировать: {e}")
        return {}


def probe_endpoints(token: str, profile_id: str = "") -> dict:
    """
    Пробует разные API с одним и тем же токеном.
    Возвращает dict: {endpoint: (status, school_name_or_error)}
    """
    endpoints = [
        ("dnevnik-core", "https://dnevnik.mos.ru/core/api/schools",
         {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}),
        ("dnevnik-profile", "https://dnevnik.mos.ru/core/api/profile",
         {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}),
        ("school-api", "https://school.mos.ru/api/ej/acl/v1/mod-acl/users/me",
         {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}),
    ]

    results = {}
    for name, url, base_headers in endpoints:
        headers = dict(base_headers)
        headers["Auth-Token"] = token
        headers["Authorization"] = f"Bearer {token}"
        if profile_id:
            headers["Profile-Id"] = str(profile_id)

        try:
            r = requests.get(url, headers=headers, timeout=15)
            results[name] = (r.status_code, r.text[:200])
        except Exception as e:
            results[name] = ("ERR", str(e))
    return results


def fetch_school_name(token: str, profile_id: str = "") -> tuple:
    """Пробует получить информацию о школе. Возвращает (ok, school_name, sid)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/152.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Auth-Token": token,
        "Authorization": f"Bearer {token}",
    }
    if profile_id:
        headers["Profile-Id"] = str(profile_id)

    try:
        r = requests.get("https://dnevnik.mos.ru/core/api/schools",
                         headers=headers, timeout=15)
    except Exception as e:
        return False, f"ошибка: {e}", ""

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:150]}", ""

    try:
        data = r.json()
    except Exception:
        return False, "не JSON", ""

    if not data:
        return False, "пустой ответ", ""

    return True, data[0].get("name", "?"), str(data[0].get("id", ""))


def save_tokens(token: str, aupd_token: str = "", profile_id: str = "",
                extra_cookies: dict = None) -> bool:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/152.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Auth-Token": token,
        "Authorization": f"Bearer {token}",
    })
    if profile_id:
        session.headers["Profile-Id"] = str(profile_id)

    # Кладём токены в cookies
    for domain in ("dnevnik.mos.ru", "school.mos.ru"):
        session.cookies.set("auth_token", token, domain=domain)
        if aupd_token:
            session.cookies.set("aupd_token", aupd_token, domain=domain)
        if profile_id:
            session.cookies.set("profile_id", str(profile_id), domain=domain)

    # Дополнительные cookies (если пользователь их даст)
    if extra_cookies:
        for name, value in extra_cookies.items():
            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                session.cookies.set(name, value, domain=domain)

    # Проверяем API
    ok, info, sid = fetch_school_name(token, profile_id)

    if ok:
        log(f"[+] API принял токен: {info} (id={sid})")
    else:
        log(f"[!] API dnevnik.mos.ru отклонил токен: {info}")
        log("    Пробую другие эндпоинты для диагностики...")
        probes = probe_endpoints(token, profile_id)
        for name, (code, snippet) in probes.items():
            log(f"    - {name}: {code}")
            if isinstance(code, int) and code != 403:
                log(f"      {snippet}")

    # Всё равно сохраняем — попробуем позже
    try:
        with open(SESSION_FILE, "wb") as f:
            pickle.dump(session.cookies, f)
        with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "auth_token": token,
                "aupd_token": aupd_token,
                "profile_id": str(profile_id),
                "school_id": str(sid),
            }, f, ensure_ascii=False, indent=2)
        log(f"[+] Сохранено: {SESSION_FILE}")
        log(f"[+] Сохранено: {AUTH_DATA_FILE}")
    except Exception as e:
        log(f"[SAVE] Ошибка: {e}")
        return False

    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Сохранить auth_token в ~/.zavuch2/"
    )
    parser.add_argument("--token", default="",
                        help="auth_token (если пусто — читаем из clipboard)")
    parser.add_argument("--aupd", default="",
                        help="aupd_token (если отличается от auth_token)")
    parser.add_argument("--profile-id", default="",
                        help="profile_id (если известен)")
    args = parser.parse_args()

    log("=" * 60)
    log(" Сохранение токена в ~/.zavuch2/")
    log("=" * 60)

    token = args.token.strip()
    if not token:
        token = get_from_clipboard()
        if token:
            log(f"[clipboard] Получено {len(token)} символов")
        else:
            log("[!] Токен не передан и буфер обмена пуст.")
            log("    Запустите с --token \"...\"")
            sys.exit(1)

    if not token or len(token) < 50:
        log("[!] Слишком короткий токен — это точно не JWT.")
        sys.exit(1)

    # Декодируем payload (без проверки подписи)
    payload = try_decode_jwt(token)
    if payload:
        log("[i] Payload токена:")
        for k in ("sub", "iss", "exp", "iat", "ath"):
            if k in payload:
                log(f"    {k} = {payload[k]}")
        import datetime
        if "exp" in payload:
            try:
                exp_dt = datetime.datetime.fromtimestamp(payload["exp"])
                log(f"    exp → {exp_dt.strftime('%d.%m.%Y %H:%M:%S')}")
            except Exception:
                pass
        if payload.get("iss") == "https://school.mos.ru":
            log("    ⚠️ iss=school.mos.ru — токен выдан для school.mos.ru.")
            log("       Для dnevnik.mos.ru может понадобиться отдельный токен,")
            log("       либо API принимает общий SSO-токен.")
        if "sub" in payload and not args.profile_id:
            log(f"[i] sub={payload['sub']} — это user_id, НЕ profile_id.")

    log("")
    log("Проверяю API dnevnik.mos.ru...")

    aupd = args.aupd.strip()
    if not aupd:
        aupd = token  # по умолчанию тот же самый

    ok = save_tokens(token, aupd_token=aupd, profile_id=args.profile_id)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()