# -*- coding: utf-8 -*-
import requests


class KTPCollector:
    """Класс для сбора данных о КТП через dnevnik.mos.ru/ec/api"""

    def __init__(self, auth):
        self.auth = auth
        self.activities_cache = None
        self.groups_cache = None
        self.class_names_map = {}  # {class_unit_id: "4-А"}
        self.ec_schedule_cache = {}
        self.log_callback = None

    def _log(self, text):
        if self.log_callback:
            self.log_callback(text)
        else:
            print(text)

    def _fetch_raw(self, url, params=None):
        """Запрос через dnevnik.mos.ru"""
        try:
            if url.startswith('http'):
                full_url = url
            else:
                full_url = "https://dnevnik.mos.ru/" + url.lstrip('/')

            self._log(f"[KTP] Запрос: {full_url}")
            self._log(f"[KTP] Параметры: {params}")

            if not self.auth or not self.auth.session:
                return False, "Нет активной сессии"

            response = self.auth.session.get(full_url, params=params, timeout=30)
            self._log(f"[KTP] Статус: {response.status_code}")

            if response.status_code == 400:
                return False, f"400: {response.text[:200]}"
            if response.status_code == 401:
                return False, "401 Unauthorized"
            if response.status_code == 403:
                return False, "403 Forbidden"
            if response.status_code == 404:
                return False, f"404: {full_url}"
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"

            return True, response.json()

        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _extract_list(self, result):
        """Извлекает список из разных форматов ответа"""
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ['data', 'results', 'items', 'groups', 'activities']:
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    def get_all_activities(self):
        """Загрузка всех активностей с пагинацией"""
        if self.activities_cache is not None:
            return self.activities_cache

        all_activities = []
        page = 1
        per_page = 50

        while True:
            success, result = self._fetch_raw(
                "https://dnevnik.mos.ru/ec/api/ec_activity",
                {'page': page, 'per_page': per_page, 'pid': self.auth.pid}
            )

            if not success:
                self._log(f"[KTP] ❌ Ошибка: {result}")
                break

            items = self._extract_list(result)
            if not items:
                break

            all_activities.extend(items)
            self._log(f"[KTP] Активности стр.{page}: {len(items)}")

            if len(items) < per_page:
                break
            page += 1

        self._log(f"[KTP] ✅ Всего активностей: {len(all_activities)}")
        self.activities_cache = all_activities
        return all_activities

    def _build_class_names_map(self):
        """Строит карту {class_unit_id: class_name} из всех активностей"""
        if self.class_names_map:
            return self.class_names_map

        activities = self.get_all_activities()

        for activity in activities:
            for cu in activity.get('class_units', []):
                if isinstance(cu, dict):
                    cu_id = cu.get('id')
                    cu_name = cu.get('name', '')
                    if cu_id and cu_name:
                        self.class_names_map[cu_id] = cu_name

        self._log(f"[KTP] 📚 Карта классов: {len(self.class_names_map)} записей")
        return self.class_names_map

    def get_class_name(self, class_unit_id):
        """Получение названия класса по ID"""
        return self.class_names_map.get(class_unit_id, f"ID:{class_unit_id}")

    def get_all_groups(self):
        """
        Загрузка ВСЕХ групп через ec_groups с ec_activity_ids.
        Разбиваем на порции по 25 ID (как в браузере).
        """
        if self.groups_cache is not None:
            return self.groups_cache

        # 1. Загружаем активности
        activities = self.get_all_activities()
        if not activities:
            return []

        # Строим карту активностей
        activities_map = {a.get('id'): a for a in activities}

        # Строим карту классов
        self._build_class_names_map()

        # 2. Загружаем группы порциями по 25 активностей
        activity_ids = [str(a.get('id')) for a in activities if a.get('id')]
        batch_size = 25
        all_groups = []

        total_batches = (len(activity_ids) + batch_size - 1) // batch_size
        for batch_num, i in enumerate(range(0, len(activity_ids), batch_size), start=1):
            batch = activity_ids[i:i + batch_size]
            ids_param = ','.join(batch)

            self._log(f"[KTP] Группы: партия {batch_num}/{total_batches} ({len(batch)} активностей)")

            # ПРАВИЛЬНЫЙ URL — через dnevnik.mos.ru
            success, result = self._fetch_raw(
                "https://dnevnik.mos.ru/ec/api/ec_groups",
                {
                    'ec_activity_ids': ids_param,
                    'per_page': 300,
                    'pid': self.auth.pid
                }
            )

            if success:
                items = self._extract_list(result)
                all_groups.extend(items)
                self._log(f"[KTP] Получено групп: {len(items)}")
            else:
                self._log(f"[KTP] ❌ Ошибка: {result}")

        # 3. Обогащаем группы названиями классов и данными активности
        for group in all_groups:
            activity_id = group.get('ec_activity_id')
            activity = activities_map.get(activity_id, {})

            # Названия классов
            class_unit_ids = group.get('class_unit_ids', [])
            class_names = [self.get_class_name(cu_id) for cu_id in class_unit_ids]

            group['class_unit_names'] = class_names
            group['activity_name'] = activity.get('name', '')
            group['activity_short_name'] = activity.get('short_name', '')
            group['ec_form_name'] = activity.get('ec_form_name', '')
            group['ec_field_name'] = activity.get('ec_field_name', '')

        self._log(f"[KTP] ✅ Всего групп: {len(all_groups)}")
        self.groups_cache = all_groups
        return all_groups

    def get_ec_schedule_items(self, ec_group_id, academic_year_id=14):
        """Получение КТП для группы"""
        cache_key = f"{ec_group_id}_{academic_year_id}"
        if cache_key in self.ec_schedule_cache:
            return self.ec_schedule_cache[cache_key]

        url = "https://dnevnik.mos.ru/ec/api/ec_schedule_items"
        params = {
            'academic_year_id': academic_year_id,
            'ec_group_ids': ec_group_id,
            'page': 1,
            'per_page': 50,
            'pid': self.auth.pid
        }

        success, result = self._fetch_raw(url, params)

        if success:
            items = self._extract_list(result)
            self.ec_schedule_cache[cache_key] = items
            return items

        self.ec_schedule_cache[cache_key] = []
        return []

    def has_ktp(self, ec_group_id, academic_year_id=14):
        """Проверка наличия КТП"""
        schedule_items = self.get_ec_schedule_items(ec_group_id, academic_year_id)

        if not schedule_items:
            return False, 0, 0

        total_lessons = len(schedule_items)
        lessons_with_names = 0

        for item in schedule_items:
            lesson_name = item.get('ec_course_calendar_lesson_name') or ''
            lesson_name = str(lesson_name).strip()
            if lesson_name:
                lessons_with_names += 1

        return lessons_with_names > 0, lessons_with_names, total_lessons