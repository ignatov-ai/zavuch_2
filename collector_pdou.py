# -*- coding: utf-8 -*-
"""
Коллектор групп ПДОУ (кружки и секции).
Работает через esz.mos.ru с отдельным токеном (aupdToken),
отдельным esztoken (JWT HS256 из Local Storage) и набором cookies.

Файлы в ~/.zavuch2/:
  • pdou_token.json    — aupd_token, esztoken, user_name, user_roles
  • pdou_cookies.json  — session-cookie, Ltpatoken2, mos_id, obr_id, ...
"""
import base64
import json
import re
import time
from pathlib import Path

import requests


# ==== Хранилища ====
DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)
PDOU_TOKEN_FILE = DATA_DIR / "pdou_token.json"
PDOU_COOKIES_FILE = DATA_DIR / "pdou_cookies.json"


class PDOUToken:
    """Управление токенами ПДОУ (aupd_token + esztoken)."""

    @staticmethod
    def load() -> dict:
        if not PDOU_TOKEN_FILE.exists():
            return {}
        try:
            with open(PDOU_TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save(aupd_token: str, user_name: str = "", user_roles=None,
             esztoken: str = "") -> bool:
        try:
            data = {
                "aupd_token": aupd_token.strip(),
                "esztoken": esztoken.strip(),
                "user_name": user_name.strip(),
                "user_roles": list(user_roles or []),
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(PDOU_TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def clear():
        try:
            if PDOU_TOKEN_FILE.exists():
                PDOU_TOKEN_FILE.unlink()
        except Exception:
            pass


class PDOUCookies:
    """Хранилище cookies ПДОУ."""

    SKIP_NAMES = {
        "_ym_d", "_ym_isad", "_ym_uid",
        "tmr_lvid", "tmr_lvidTS",
        "yabm", "GPT_INIT", "sbp_sid",
    }

    @staticmethod
    def load() -> dict:
        if not PDOU_COOKIES_FILE.exists():
            return {}
        try:
            with open(PDOU_COOKIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save(cookies: dict) -> bool:
        try:
            with open(PDOU_COOKIES_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def clear():
        try:
            if PDOU_COOKIES_FILE.exists():
                PDOU_COOKIES_FILE.unlink()
        except Exception:
            pass

    @staticmethod
    def parse_cookie_string(cookie_str: str) -> dict:
        result = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            if name in PDOUCookies.SKIP_NAMES:
                continue
            result[name] = value
        return result


class PDOUCollector:
    """Класс для сбора данных о группах ПДОУ (ЕСЗ)."""

    BASE_URL = "https://esz.mos.ru/Services/Data.Service/ServiceClass/Search"
    USER_URL = "https://esz.mos.ru/Services/AuthorizationService/User/CurrentUser"

    # Организация по умолчанию (можно менять)
    ORG_ID = 67556
    ORG_NAME = "ГАОУ Школа № 548"
    VEDOMSTVO_ID = 1
    EDUCATION_TYPE_ID = 1
    EDUCATION_TYPE_NAME = "Детские объединения департамента образования"

    def __init__(self, aupd_token: str, esztoken: str = ""):
        self.token = aupd_token.strip()      # aupd_token (JWT RS256)
        self.esztoken = esztoken.strip()      # esztoken (JWT HS256)
        self.groups_cache = None
        self.log_callback = None
        self.obr_id = ""
        self.user_name = ""
        self.user_roles = []
        self.extra_cookies = PDOUCookies.load() or {}

    def _log(self, text):
        if self.log_callback:
            self.log_callback(text)
        else:
            print(text)

    # ================================================================
    #  Разбор JWT
    # ================================================================
    @staticmethod
    def _decode_jwt_payload(token: str) -> dict:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return {}
            b64 = parts[1]
            pad = "=" * (-len(b64) % 4)
            decoded = base64.urlsafe_b64decode(b64 + pad).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return {}

    # ================================================================
    #  Создание сессии
    # ================================================================
    def _build_session(self):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/154.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://esz.mos.ru",
            "Referer": "https://esz.mos.ru/serviceClasses",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })

        # Cookies
        if self.extra_cookies:
            self._log(f"[ПДОУ] Cookies из файла: {list(self.extra_cookies.keys())}")
            for name, value in self.extra_cookies.items():
                session.cookies.set(name, value, domain="esz.mos.ru")
                session.cookies.set(name, value, domain=".mos.ru")

        # Предварительный визит
        try:
            session.get("https://esz.mos.ru/", timeout=15)
            session.get("https://esz.mos.ru/serviceClasses", timeout=15)
        except Exception:
            pass

        # Диагностика
        final = list(set(session.cookies.keys()))
        self._log(f"[ПДОУ] Cookies в сессии: {len(final)}")
        critical = ["session-cookie", "Ltpatoken2", "mos_id", "aupd_token",
                    "obr_id", "subsystem_id", "aupd_current_role", "auth_flag"]
        missing = [c for c in critical if c not in final]
        if missing:
            self._log(f"[ПДОУ] ⚠️ Отсутствуют: {missing}")
        else:
            self._log(f"[ПДОУ] ✅ Все критичные cookies на месте")

        return session

    # ================================================================
    #  Проверка токена
    # ================================================================
    def check_token(self):
        """Проверяет aupd_token через /User/CurrentUser."""
        if not self.token:
            return False, "", [], "Токен пустой"

        session = self._build_session()
        try:
            self._apply_auth(session)
        except ValueError as e:
            return False, "", [], str(e)

        self._log("[ПДОУ] GET /User/CurrentUser")
        try:
            r = session.get(self.USER_URL, timeout=20)
        except Exception as e:
            return False, "", [], f"Ошибка сети: {e}"

        self._log(f"[ПДОУ] HTTP {r.status_code}")

        if r.status_code != 200:
            body = r.text[:300]
            self._log(f"[ПДОУ] Тело: {body}")
            return False, "", [], f"HTTP {r.status_code}: {body}"

        try:
            data = r.json()
        except Exception:
            return False, "", [], "Ответ не JSON"

        user_name = (
            data.get("userName")
            or (data.get("fullName") or {}).get("lastName", "")
            or data.get("login", "")
        )
        full = data.get("fullName") or {}
        if full:
            parts = [
                full.get("lastName", ""),
                full.get("firstName", ""),
                full.get("middleName", ""),
            ]
            user_name = " ".join(p for p in parts if p) or user_name

        self.obr_id = str(data.get("id") or self.obr_id or "")

        roles = []
        for role in (data.get("roles") or []):
            if isinstance(role, dict):
                roles.append(role.get("name") or f"id {role.get('id')}")
            else:
                roles.append(str(role))

        self.user_name = user_name
        self.user_roles = roles

        self._log(f"[ПДОУ] ✅ {user_name}, роли={roles}")
        return True, user_name, roles, "OK"

    # ================================================================
    #  Установка заголовков авторизации
    # ================================================================
    def _apply_auth(self, session):
        """Ставит Authorization: Bearer и esztoken."""
        if not self.token:
            return

        # Проверки aupd_token
        if "…" in self.token:
            raise ValueError("aupd_token содержит «…» — скопируйте полностью.")
        if len(self.token) < 800:
            raise ValueError(f"aupd_token слишком короткий ({len(self.token)}).")
        if len(self.token.split(".")) != 3:
            raise ValueError("aupd_token не является JWT.")

        payload = self._decode_jwt_payload(self.token)
        sub = str(payload.get("sub", "") or "")
        if sub and not self.obr_id:
            self.obr_id = sub

        # Cookies
        existing = set(session.cookies.keys())
        if "aupd_token" not in existing:
            session.cookies.set("aupd_token", self.token, domain="esz.mos.ru")
        if "aupd_current_role" not in existing:
            session.cookies.set("aupd_current_role", "28:19", domain="esz.mos.ru")
        if "subsystem_id" not in existing:
            session.cookies.set("subsystem_id", "28", domain="esz.mos.ru")
        if "auth_flag" not in existing:
            session.cookies.set("auth_flag", "main", domain="esz.mos.ru")
        if "user_login" not in existing:
            session.cookies.set("user_login", "", domain="esz.mos.ru")
        if self.obr_id and "obr_id" not in existing:
            session.cookies.set("obr_id", self.obr_id, domain="esz.mos.ru")

        # Заголовки
        session.headers["Authorization"] = f"Bearer {self.token}"
        session.headers["x-mes-subsystem"] = "headerweb"
        session.headers["x-mes-hostId"] = "28"

        # esztoken — для /ServiceClass/Search
        if self.esztoken:
            if "…" in self.esztoken:
                raise ValueError("esztoken содержит «…» — скопируйте полностью.")
            if len(self.esztoken) < 200:
                raise ValueError(f"esztoken слишком короткий ({len(self.esztoken)}).")
            session.headers["esztoken"] = self.esztoken
            self._log(f"[ПДОУ] esztoken установлен ({len(self.esztoken)} символов)")
        else:
            self._log("[ПДОУ] ⚠️ esztoken НЕ задан — /ServiceClass/Search вернёт 401")

    # ================================================================
    #  Загрузка групп
    # ================================================================
    def _fetch_page(self, session, page_number=1, page_size=10):
        """POST /ServiceClass/Search с телом как в браузере."""
        payload = {
            "usedCapacityFilter": 0,
            "showArchive": False,
            "educationTypeId": self.EDUCATION_TYPE_ID,
            "vedomstvoId": self.VEDOMSTVO_ID,
            "organizationName": self.ORG_NAME,
            "organizationId": self.ORG_ID,
            "educationTypeName": self.EDUCATION_TYPE_NAME,
            "pageSize": page_size,
            "pageNumber": page_number,
        }

        try:
            self._log(f"[ПДОУ] POST {self.BASE_URL} pageNumber={page_number}")
            r = session.post(self.BASE_URL, json=payload, timeout=30)
            self._log(f"[ПДОУ] ← HTTP {r.status_code}")

            if r.status_code == 200:
                try:
                    return True, r.json()
                except Exception as e:
                    return False, f"Не JSON: {e}"

            self._log(f"[ПДОУ] Тело: {r.text[:300]}")
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"POST ошибка: {e}"

    def get_all_groups(self):
        """Загружает все группы ПДОУ с пагинацией."""
        if self.groups_cache is not None:
            return self.groups_cache

        if not self.token:
            self._log("[ПДОУ] ❌ aupd_token не задан")
            return []
        if not self.esztoken:
            self._log("[ПДОУ] ❌ esztoken не задан — загрузка невозможна")
            return []

        session = self._build_session()
        try:
            self._apply_auth(session)
        except ValueError as e:
            self._log(f"[ПДОУ] ❌ {e}")
            return []

        all_groups = []
        page_number = 1
        page_size = 50
        total = None

        while True:
            ok, result = self._fetch_page(session, page_number, page_size)
            if not ok:
                self._log(f"[ПДОУ] ❌ Страница {page_number}: {result}")
                break

            items = result.get("items") if isinstance(result, dict) else None
            if items is None:
                # возможно, формат другой — вывод всего ответа
                self._log(f"[ПДОУ] Неожиданный формат: {str(result)[:300]}")
                break

            if total is None:
                total = result.get("total")
                self._log(f"[ПДОУ] Всего по серверу: {total}")

            if not items:
                break

            all_groups.extend(items)
            self._log(f"[ПДОУ] Страница {page_number}: +{len(items)} (итого {len(all_groups)})")

            if total is not None and len(all_groups) >= total:
                break
            if len(items) < page_size:
                break

            page_number += 1
            if page_number > 100:
                break
            time.sleep(0.15)

        self._log(f"[ПДОУ] ✅ Всего загружено: {len(all_groups)}")
        self.groups_cache = all_groups
        return all_groups

    # ================================================================
    #  Вспомогательные
    # ================================================================
    @staticmethod
    def get_status_text(status_code):
        mapping = {
            1: "Активна",
            2: "Идёт обучение",
            3: "Завершена",
            0: "Неизвестно",
        }
        try:
            return mapping.get(int(status_code), f"Статус {status_code}")
        except (ValueError, TypeError):
            return "Неизвестно"