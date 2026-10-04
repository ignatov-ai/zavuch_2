# -*- coding: utf-8 -*-
"""
Коллектор заявлений ПДОУ.

Источники:
  • POST /Services/Data.Service/Request/Search  — список заявлений.
  • GET  /Services/Data.Service/Request?id=X    — детали (имя группы).
  • GET  /Services/Data.Service/Learner/Education/List/{guid}
                                                 — класс обучения.
"""
import json
import re
import time
from pathlib import Path

import requests

from collector_pdou import PDOUCookies, PDOUCollector


from paths import SESSIONS_DIR
DATA_DIR = SESSIONS_DIR

# ============================================================
#  Класс группы — из имени группы
# ============================================================
_RE_GROUP_CLASS_PREFIX = re.compile(
    r"^\s*"
    r"(\d{1,2})"
    r"\s*"
    r"([А-Яа-яЁё](?:[,/\-][А-Яа-яЁё]+)?)?"
    r"(?:\s*-\s*\d+)?",
    re.IGNORECASE,
)

_RE_GROUP_CLASS_KL = re.compile(
    r"(\d{1,2})\s*(?:-\s*(\d{1,2}))?\s*кл(?:асс)?",
    re.IGNORECASE,
)

_RE_GROUP_CLASS_MID = re.compile(
    r"(?:^|[\s,;(\[])"
    r"(\d{1,2})\s*([А-ЯЁ])"
    r"(?=$|[\s,;)\]])",
)


def extract_class_from_group_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip()

    m = _RE_GROUP_CLASS_PREFIX.match(n)
    if m:
        num = m.group(1)
        letter = (m.group(2) or "").upper()
        letter = letter.split("-")[0]
        return f"{num}{letter}"

    m = _RE_GROUP_CLASS_KL.search(n)
    if m:
        a, b = m.group(1), m.group(2)
        if b and b != a:
            return f"{a}-{b}"
        return a

    m = _RE_GROUP_CLASS_MID.search(n)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"

    return ""


# ============================================================
#  Коллектор
# ============================================================
class PDOURequestsCollector:
    SEARCH_URL = "https://esz.mos.ru/Services/Data.Service/Request/Search"
    DETAIL_URL = "https://esz.mos.ru/Services/Data.Service/Request"
    EDUCATION_URL = ("https://esz.mos.ru/Services/Data.Service/Learner/"
                     "Education/List/{guid}")

    def __init__(self, aupd_token: str, esztoken: str = ""):
        self.token = aupd_token.strip()
        self.esztoken = esztoken.strip()
        self.log_callback = None
        self.extra_cookies = PDOUCookies.load() or {}

        self._detail_cache = {}
        self._education_cache = {}

        self._base = PDOUCollector(self.token, self.esztoken)

    def _log(self, text):
        if self.log_callback:
            self.log_callback(text)
        else:
            print(text)

    def _build_session(self):
        session = self._base._build_session()
        try:
            self._base._apply_auth(session)
        except Exception as e:
            self._log(f"[Заявления] ❌ Ошибка авторизации: {e}")
            raise

        # LTPA явно в заголовке
        cookies = self.extra_cookies or {}
        ltpa = cookies.get("Ltpatoken2")
        if ltpa:
            session.headers["LtpaToken2"] = ltpa
            session.headers["LTPA2"] = ltpa
            self._log("[Заявления] ℹ️ Ltpatoken2 передан в заголовке.")

        if "subsystem_id" not in session.cookies.keys():
            session.cookies.set("subsystem_id", "28", domain="esz.mos.ru")

        return session

    def search_requests(self, page_number: int = 1, page_size: int = 50,
                        search_text: str = "", status_id=None):
        payload = {
            "usedCapacityFilter": 0,
            "showArchive": False,
            "pageSize": page_size,
            "pageNumber": page_number,
        }
        if search_text:
            payload["searchText"] = search_text
        if status_id is not None:
            payload["requestStatusId"] = status_id

        session = self._build_session()
        try:
            r = session.post(self.SEARCH_URL, json=payload, timeout=30)
        except Exception as e:
            self._log(f"[Заявления] ❌ Ошибка сети: {e}")
            return [], 0

        if r.status_code == 403:
            self._log(
                "[Заявления] ❌ HTTP 403: нет доступа к реестру заявлений.\n"
                "   Причина: отсутствует Ltpatoken2 (или истёк), либо нет прав.\n"
                "   Решение: проверьте, открывается ли esz.mos.ru/requests "
                "в браузере. Если да — скопируйте Ltpatoken2 и session-cookie "
                "из DevTools в ~/.zavuch2/pdou_cookies.json."
            )
            return [], 0

        if r.status_code == 401:
            self._log(
                "[Заявления] ❌ HTTP 401: сессия невалидна.\n"
                "   Проверьте, что aupd_token и esztoken не просрочены."
            )
            return [], 0

        if r.status_code != 200:
            self._log(f"[Заявления] ❌ HTTP {r.status_code}: {r.text[:200]}")
            return [], 0

        try:
            data = r.json()
        except Exception as e:
            self._log(f"[Заявления] ❌ Не JSON: {e}")
            return [], 0

        items = data.get("items") or []
        total = data.get("total") or 0
        self._log(f"[Заявления] Стр.{page_number}: +{len(items)} (всего {total})")
        return items, total

    def get_request_details(self, request_id):
        key = str(request_id)
        if key in self._detail_cache:
            return self._detail_cache[key]

        session = self._build_session()
        try:
            r = session.get(self.DETAIL_URL, params={"id": request_id}, timeout=20)
            if r.status_code != 200:
                self._log(f"[Заявления] Детали {request_id}: HTTP {r.status_code}")
                return {}
            data = r.json()
        except Exception as e:
            self._log(f"[Заявления] Детали {request_id}: ошибка {e}")
            return {}

        self._detail_cache[key] = data
        return data

    def get_learner_class(self, learner_guid):
        if not learner_guid:
            return ""
        key = str(learner_guid)
        if key in self._education_cache:
            return self._education_cache[key]

        session = self._build_session()
        url = self.EDUCATION_URL.format(guid=learner_guid)
        try:
            r = session.get(url, timeout=20)
            if r.status_code != 200:
                self._education_cache[key] = ""
                return ""
            data = r.json()
        except Exception:
            self._education_cache[key] = ""
            return ""

        class_name = ""
        if isinstance(data, list) and data:
            for item in data:
                cn = item.get("className") or ""
                if cn:
                    class_name = cn
                    break
        elif isinstance(data, dict):
            class_name = data.get("className") or ""

        self._education_cache[key] = class_name
        return class_name

    def enrich_request(self, item: dict) -> dict:
        req_id = item.get("id")

        child_name = (item.get("childName") or "").strip()
        applicant_name = (item.get("applicantName") or "").strip()
        service_name = (item.get("serviceName") or "").strip()
        service_class_code = (item.get("serviceClassCode") or "").strip()

        status_name = (item.get("requestStatusName") or "").strip()
        status_id = item.get("requestStatusId")

        from collector_pdou import extract_building_from_program
        building = extract_building_from_program(service_name)

        group_name = ""
        group_class = ""
        learner_guid = ""

        try:
            details = self.get_request_details(req_id)
            if details:
                tg = details.get("trainingGroup") or {}
                sc = tg.get("serviceClass") or {}
                group_name = (sc.get("name") or "").strip()

                learner_guid = (
                    details.get("learnerGuid")
                    or details.get("childGuid")
                    or details.get("learnerId")
                    or ""
                )
                if not learner_guid:
                    for k in ("learners", "childs", "children"):
                        lst = details.get(k)
                        if isinstance(lst, list) and lst:
                            learner_guid = (
                                lst[0].get("guid")
                                or lst[0].get("id")
                                or ""
                            )
                            if learner_guid:
                                break
        except Exception as e:
            self._log(f"[Заявления] enrich {req_id}: {e}")

        group_class = extract_class_from_group_name(group_name)

        learner_class = ""
        if learner_guid:
            learner_class = self.get_learner_class(learner_guid)

        return {
            "id": req_id,
            "request_number": item.get("requestNumber", ""),
            "child_name": child_name,
            "applicant_name": applicant_name,
            "applicant_phone": item.get("applicantPhone", ""),
            "building": building,
            "service_name": service_name,
            "service_class_code": service_class_code,
            "group_name": group_name,
            "group_class": group_class,
            "learner_class": learner_class,
            "status_name": status_name,
            "status_id": status_id,
            "contract_number": item.get("contractNumber", ""),
            "contract_status": item.get("contractStatus", ""),
            "request_date": item.get("requestDate", ""),
            "enrollment_date": item.get("enrollmentDate", ""),
        }

    def load_page(self, page_number: int = 1, page_size: int = 50,
                  search_text: str = "", status_id=None,
                  progress_callback=None):
        items, total = self.search_requests(page_number, page_size,
                                            search_text, status_id)
        if not items:
            return [], total

        enriched = []
        for i, item in enumerate(items):
            enriched.append(self.enrich_request(item))
            if progress_callback:
                progress_callback(i + 1, len(items))

        return enriched, total

    def load_all(self, page_size: int = 50, max_pages: int = 200,
                 search_text: str = "", status_id=None,
                 progress_callback=None):
        all_items = []
        page = 1
        while page <= max_pages:
            items, total = self.search_requests(page, page_size,
                                                search_text, status_id)
            if not items:
                break
            for item in items:
                all_items.append(self.enrich_request(item))
                if progress_callback:
                    progress_callback(len(all_items), total)
            if len(items) < page_size:
                break
            page += 1
            time.sleep(0.15)
        return all_items, len(all_items)