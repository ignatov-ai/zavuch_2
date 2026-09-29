# -*- coding: utf-8 -*-
"""
Коллектор групп ПДОУ (кружки и секции).
Работает через esz.mos.ru/Services/Data.Service/ServiceClass/Search.

Авторизация: используется существующая сессия dn_Auth (self.auth.session)
с теми же cookies и заголовками, что и для dnevnik.mos.ru.
Если esz.mos.ru начнёт возвращать 401/403 — потребуется отдельный токен,
тогда добавим его в auth_data.json и будем брать отсюда.
"""
import json
import time

import requests


class PDOUCollector:
    """Класс для сбора данных о группах ПДОУ"""

    BASE_URL = "https://esz.mos.ru/Services/Data.Service/ServiceClass/Search"

    def __init__(self, auth):
        self.auth = auth
        self.groups_cache = None
        self.log_callback = None

    def _log(self, text):
        if self.log_callback:
            self.log_callback(text)
        else:
            print(text)

    # ================================================================
    #  HTTP
    # ================================================================
    def _build_session(self):
        """
        Создаёт requests.Session на основе cookies/заголовков существующей авторизации.
        Копируем cookies и ключевые заголовки из self.auth.session.
        """
        session = requests.Session()

        # Копируем cookies (все, что есть — некоторые могут пригодиться и для esz)
        try:
            for cookie in self.auth.session.cookies:
                session.cookies.set(cookie.name, cookie.value)
        except Exception:
            pass

        # Копируем заголовки
        for k in ("User-Agent", "Accept", "Accept-Language"):
            v = self.auth.session.headers.get(k)
            if v:
                session.headers[k] = v

        # Добавляем от себя
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://esz.mos.ru",
            "Referer": "https://esz.mos.ru/",
        })

        # Если в auth есть auth_token — прокидываем заголовком (может пригодиться)
        try:
            token = getattr(self.auth, "auth_token", "") or self.auth.session.headers.get("Auth-Token", "")
            if token:
                session.headers["Auth-Token"] = token
                session.headers["Authorization"] = f"Bearer {token}"
        except Exception:
            pass

        # Profile-Id — тоже прокидываем
        try:
            pid = getattr(self.auth, "pid", "") or self.auth.session.headers.get("Profile-Id", "")
            if pid:
                session.headers["Profile-Id"] = str(pid)
        except Exception:
            pass

        return session

    def _fetch_page(self, session, page=1, per_page=50, extra_payload=None):
        """
        Запрос одной страницы.
        Пробуем POST, если сервер не принял — пробуем GET.
        Возвращает (ok, result_or_error).
        """
        payload = {
            "page": page,
            "perPage": per_page,
            # фильтр по учебному году может быть пустым — сервер вернёт всё
        }
        if extra_payload:
            payload.update(extra_payload)

        # --- Попытка 1: POST с JSON ---
        try:
            self._log(f"[ПДОУ] POST {self.BASE_URL} page={page} perPage={per_page}")
            r = session.post(self.BASE_URL, json=payload, timeout=30)
            self._log(f"[ПДОУ] ← HTTP {r.status_code}")

            if r.status_code == 200:
                try:
                    return True, r.json()
                except Exception as e:
                    return False, f"Не JSON: {e}"
            elif r.status_code in (401, 403):
                self._log(f"[ПДОУ] {r.status_code} на POST — пробую GET")
            else:
                # Пробуем GET ниже
                self._log(f"[ПДОУ] Неожиданный код {r.status_code}, тело: {r.text[:200]}")
        except Exception as e:
            self._log(f"[ПДОУ] POST ошибка: {e}")

        # --- Попытка 2: GET с query-параметрами ---
        try:
            self._log(f"[ПДОУ] GET {self.BASE_URL} page={page} perPage={per_page}")
            r = session.get(self.BASE_URL, params=payload, timeout=30)
            self._log(f"[ПДОУ] ← HTTP {r.status_code}")

            if r.status_code == 200:
                try:
                    return True, r.json()
                except Exception as e:
                    return False, f"Не JSON: {e}"
            else:
                return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"GET ошибка: {e}"

    # ================================================================
    #  ПУБЛИЧНЫЙ API
    # ================================================================
    def get_all_groups(self, extra_payload=None):
        """
        Загружает все группы ПДОУ через пагинацию.
        Возвращает список словарей:
            {id, code, name, supervisorPerson, serviceName,
             trainDates, capacity, included, serviceClassStatus,
             serviceId, educationTypeId, shiftPeriod, ...}
        """
        if self.groups_cache is not None:
            return self.groups_cache

        session = self._build_session()

        all_groups = []
        page = 1
        per_page = 50
        total = None

        while True:
            ok, result = self._fetch_page(
                session, page=page, per_page=per_page, extra_payload=extra_payload
            )
            if not ok:
                self._log(f"[ПДОУ] ❌ Ошибка на странице {page}: {result}")
                break

            if not isinstance(result, dict):
                self._log(f"[ПДОУ] ❌ Ответ не словарь: {type(result)}")
                break

            items = result.get("items") or []
            if total is None:
                total = result.get("total")
                self._log(f"[ПДОУ] Всего групп по данным сервера: {total}")

            if not items:
                break

            all_groups.extend(items)
            self._log(f"[ПДОУ] Страница {page}: +{len(items)} (итого {len(all_groups)})")

            # Условия завершения
            if total is not None and len(all_groups) >= total:
                break
            if len(items) < per_page:
                break

            page += 1
            if page > 100:  # защита от бесконечного цикла
                self._log("[ПДОУ] Достигнут предел в 100 страниц")
                break

            time.sleep(0.15)  # вежливая пауза между запросами

        self._log(f"[ПДОУ] ✅ Всего загружено групп: {len(all_groups)}")
        self.groups_cache = all_groups
        return all_groups

    # ================================================================
    #  ВСПОМОГАТЕЛЬНЫЕ
    # ================================================================
    @staticmethod
    def get_status_text(status_code):
        """Человекочитаемый статус группы."""
        mapping = {
            1: "Активна",
            2: "Завершена",
            3: "Отменена",
            0: "Неизвестно",
        }
        try:
            return mapping.get(int(status_code), f"Статус {status_code}")
        except (ValueError, TypeError):
            return "Неизвестно"