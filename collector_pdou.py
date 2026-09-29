# -*- coding: utf-8 -*-
"""
Коллектор групп ПДОУ (кружки и секции).
Работает через esz.mos.ru.

Использует ДВА токена + cookies:
  • aupd_token (JWT RS256 из cookie aupd_token)
  • esztoken  (JWT HS256 из Local Storage → eszToken)
  • cookies   (session-cookie, mos_id, obr_id, subsystem_id, ...)

Корпуса:
  • Определяются ТОЛЬКО по префиксу названия программы (serviceName).
  • Дополнительные запросы /ServiceClass/{id} НЕ выполняются.
  • Кэш корпусов НЕ используется — корпус считается мгновенно.
"""
import base64
import json
import time
from pathlib import Path

import requests


# ==== Хранилища ====
DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)
PDOU_TOKEN_FILE = DATA_DIR / "pdou_token.json"
PDOU_COOKIES_FILE = DATA_DIR / "pdou_cookies.json"
# pdou_buildings_cache.json больше не используется.


# ============================================================
#  Корпуса — из префикса названия программы
# ============================================================
# Маркеры: (префикс программы, короткое название корпуса).
# Сравнение регистронезависимое, ищем по началу строки.
#
# Префиксы стабильны: один и тот же код года+корпуса
# никогда не встречается у двух разных корпусов.
PROGRAM_TO_BUILDING = [
    # --- Маршала Захарова ---
    ("26МЗ",    "Маршала Захарова"),
    ("25МЗ",    "Маршала Захарова"),
    ("24МЗ",    "Маршала Захарова"),
    ("МЗ ",     "Маршала Захарова"),

    # --- Домодедовская ---
    ("26ДМД",   "Домодедовская"),
    ("25ДМД",   "Домодедовская"),
    ("24ДМД",   "Домодедовская"),
    ("ДМД ",    "Домодедовская"),

    # --- Совхоз им. Ленина ---
    ("26совх",  "Совхоз им. Ленина"),
    ("25совх",  "Совхоз им. Ленина"),
    ("24совх",  "Совхоз им. Ленина"),
    ("совх",    "Совхоз им. Ленина"),

    # --- Елецкая ---
    ("26Ел",    "Елецкая"),
    ("26ел",    "Елецкая"),
    ("25Ел",    "Елецкая"),
    ("25ел",    "Елецкая"),
    ("24Ел",    "Елецкая"),
    ("24ел",    "Елецкая"),
    ("Ел ",     "Елецкая"),

    # --- ЗИЛ / Лихачёва (Зиларт) ---
    ("Зиларт",  "ЗИЛ / Лихачёва"),

    # --- Шипиловская (Мозаика) ---
    # Общий корпус для всех ступеней, независимо от адреса
    # (Шипиловская, 7 и Шипиловская, 46к2 — один учебный корпус).
    ("Мозаика", "Шипиловская"),
]


def extract_building_from_program(program: str) -> str:
    """
    Определяет корпус по названию программы (serviceName).
    Возвращает короткое название корпуса или пустую строку.

    Логика:
      • Ищем префикс в начале строки (регистронезависимо).
      • Специальное правило для «Мозаики» — общий корпус «Шипиловская».
    """
    if not program:
        return ""

    p = program.strip()
    p_lower = p.lower()

    # Специальное правило: вся «Мозаика» → «Шипиловская»
    if p_lower.startswith("мозаика"):
        return "Шипиловская"

    for prefix, building in PROGRAM_TO_BUILDING:
        if p_lower.startswith(prefix.lower()):
            return building

    return ""


def short_address(address: str) -> str:
    """Укорачивает полный адрес до вида 'улица, дом N, корпус M'."""
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",")]
    for i, p in enumerate(parts):
        p_low = p.lower()
        if ("улица" in p_low or "проспект" in p_low or "переулок" in p_low
                or "шоссе" in p_low or "проезд" in p_low):
            return ", ".join(parts[i:i + 4])
    return address


# ============================================================
#  Хранилище токенов
# ============================================================
class PDOUToken:
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


# ============================================================
#  Хранилище cookies
# ============================================================
class PDOUCookies:
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


# ============================================================
#  Кэш корпусов — DEPRECATED, оставлен для совместимости импортов.
# ============================================================
class PDOUBuildingsCache:
    """
    DEPRECATED. Корпуса теперь определяются из префикса программы,
    кэш не нужен. Класс оставлен, чтобы не ломать импорты в старых
    версиях ui/pdou_tab.py.
    """

    @staticmethod
    def load() -> dict:
        return {}

    @staticmethod
    def save(cache: dict) -> bool:
        return True

    @staticmethod
    def clear():
        try:
            f = DATA_DIR / "pdou_buildings_cache.json"
            if f.exists():
                f.unlink()
        except Exception:
            pass


# ============================================================
#  Коллектор
# ============================================================
class PDOUCollector:
    """Класс для сбора данных о группах ПДОУ (ЕСЗ)."""

    BASE_URL = "https://esz.mos.ru/Services/Data.Service/ServiceClass/Search"
    USER_URL = "https://esz.mos.ru/Services/AuthorizationService/User/CurrentUser"

    ORG_ID = 67556
    ORG_NAME = "ГАОУ Школа № 548"
    VEDOMSTVO_ID = 1
    EDUCATION_TYPE_ID = 1
    EDUCATION_TYPE_NAME = "Детские объединения департамента образования"

    def __init__(self, aupd_token: str, esztoken: str = ""):
        self.token = aupd_token.strip()
        self.esztoken = esztoken.strip()
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

        # Cookies из файла
        if self.extra_cookies:
            for name, value in self.extra_cookies.items():
                session.cookies.set(name, value, domain="esz.mos.ru")
                session.cookies.set(name, value, domain=".mos.ru")

        # Предварительный визит — получить session-cookie
        try:
            session.get("https://esz.mos.ru/", timeout=15)
            session.get("https://esz.mos.ru/serviceClasses", timeout=15)
        except Exception:
            pass

        return session

    def _apply_auth(self, session):
        """Добавляет Authorization: Bearer + cookies от токена + esztoken."""
        if not self.token:
            return

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
            session.headers["esztoken"] = self.esztoken

    # ================================================================
    #  Проверка токена
    # ================================================================
    def check_token(self):
        """Проверяет aupd_token через /User/CurrentUser.
           Возвращает (ok, user_name, roles, reason)."""
        if not self.token:
            return False, "", [], "Токен пустой"

        session = self._build_session()
        try:
            self._apply_auth(session)
        except ValueError as e:
            return False, "", [], str(e)

        try:
            r = session.get(self.USER_URL, timeout=20)
        except Exception as e:
            return False, "", [], f"Ошибка сети: {e}"

        if r.status_code != 200:
            return False, "", [], f"HTTP {r.status_code}: {r.text[:200]}"

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

        return True, user_name, roles, "OK"

    # ================================================================
    #  Загрузка списка групп
    # ================================================================
    def _fetch_page(self, session, page_number=1, page_size=50):
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
            r = session.post(self.BASE_URL, json=payload, timeout=30)
            if r.status_code == 200:
                try:
                    return True, r.json()
                except Exception as e:
                    return False, f"Не JSON: {e}"
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"POST ошибка: {e}"

    def get_all_groups(self):
        """
        Загружает все группы ПДОУ с пагинацией.

        Корпус определяется СРАЗУ из префикса программы (serviceName).
        Никаких дополнительных запросов /ServiceClass/{id} не делается.
        """
        if self.groups_cache is not None:
            return self.groups_cache

        if not self.token:
            self._log("[ПДОУ] ❌ aupd_token не задан")
            return []
        if not self.esztoken:
            self._log("[ПДОУ] ❌ esztoken не задан")
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
                self._log(f"[ПДОУ] Неожиданный формат: {str(result)[:300]}")
                break

            if total is None:
                total = result.get("total")
                self._log(f"[ПДОУ] Всего по серверу: {total}")

            if not items:
                break

            # === ГЛАВНОЕ: корпус определяется сразу из префикса программы ===
            for g in items:
                program = (g.get("serviceName") or "").strip()
                g["building"] = extract_building_from_program(program)
                # address из /ServiceClass/Search не приходит — оставляем пустым
                g.setdefault("address", "")

            all_groups.extend(items)
            self._log(
                f"[ПДОУ] Страница {page_number}: +{len(items)} "
                f"(итого {len(all_groups)})"
            )

            if total is not None and len(all_groups) >= total:
                break
            if len(items) < page_size:
                break

            page_number += 1
            if page_number > 200:
                break
            time.sleep(0.15)

        # Итоговая статистика по корпусам
        with_b = sum(1 for g in all_groups if g.get("building"))
        without = len(all_groups) - with_b
        self._log(
            f"[ПДОУ] ✅ Всего загружено: {len(all_groups)} | "
            f"с корпусом: {with_b} | без корпуса: {without}"
        )

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