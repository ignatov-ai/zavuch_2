# -*- coding: utf-8 -*-
"""
Коллектор для проверки КТП в основном расписании (ОЧ+ФЧ).
Использует API dnevnik.mos.ru (старый, рабочий).
"""
from datetime import datetime, timedelta


class KTPMainCollector:
    """Класс для сбора данных о КТП основного расписания (ОЧ+ФЧ)"""

    def __init__(self, auth):
        self.auth = auth
        self.groups_cache = None
        self.ktp_cache = {}  # {group_id: (has_ktp, lessons_with_names, total_lessons)}
        self.log_callback = None

    def _log(self, text):
        if self.log_callback:
            self.log_callback(text)
        else:
            print(text)

    def _extract_list(self, result):
        """Извлекает список из разных форматов ответа"""
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ['data', 'results', 'items', 'groups']:
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    def get_all_groups(self):
        """
        Загрузка ВСЕХ групп основного расписания через dnevnik.mos.ru/jersey/api/groups.
        Проходим по всем параллелям 1-11.
        Пропускаем предмет "Математика" для 7-11 классов
        (в ЭЖД вместо неё: Алгебра, Геометрия, Вероятность и статистика).
        """
        if self.groups_cache is not None:
            return self.groups_cache

        all_groups = []

        # Проходим по параллелям 1-11
        for class_level in range(1, 12):
            self._log(f"[KTP-MAIN] Загрузка групп для параллели {class_level}...")

            params = {
                'academic_year_id': self.auth.aid,
                'class_level_id': class_level,
                'pid': self.auth.pid,
                'with_lessons_only': 'false'
            }

            data = self.auth.fetch(
                "https://dnevnik.mos.ru/jersey/api/groups",
                params=params
            )

            if not data:
                self._log(f"[KTP-MAIN] ⚠️ Нет данных для параллели {class_level}")
                continue

            items = self._extract_list(data)
            self._log(f"[KTP-MAIN] Параллель {class_level}: {len(items)} групп")

            # Флаг: нужно ли пропускать "Математику" для этой параллели
            skip_math = 7 <= class_level <= 11

            for group in items:
                subject_name = group.get('subject_name', '') or ''
                subject_lower = subject_name.strip().lower()

                # Пропускаем "Математику" для 7-11 классов
                if skip_math and subject_lower == 'математика':
                    self._log(f"[KTP-MAIN]   ⏭️ Пропуск: {group.get('name', '')} (Математика {class_level} кл.)")
                    continue

                # Обогащаем группу информацией
                group['_class_level'] = class_level

                # Имя активности/предмета для отображения
                group['activity_name'] = subject_name
                group['activity_short_name'] = group.get('short_name', '')

                # Формируем список классов
                cu_name = group.get('class_unit_name')
                if cu_name:
                    group['class_unit_names'] = [cu_name]
                else:
                    group['class_unit_names'] = []

                all_groups.append(group)

        self._log(f"[KTP-MAIN] ✅ Всего групп: {len(all_groups)}")
        self.groups_cache = all_groups
        return all_groups

    def has_ktp(self, group_id, academic_year_id=14):
        """
        Проверка наличия КТП для группы основного расписания.
        Использует jersey/api/schedule_items.
        Возвращает (has_ktp, lessons_with_names, total_lessons).
        """
        cache_key = f"{group_id}_{academic_year_id}"
        if cache_key in self.ktp_cache:
            return self.ktp_cache[cache_key]

        try:
            # Определяем диапазон дат учебного года
            now = datetime.now()
            if now.month >= 9:
                start_date = f"{now.year}-09-01"
                end_date = f"{now.year + 1}-08-31"
            else:
                start_date = f"{now.year - 1}-09-01"
                end_date = f"{now.year}-08-31"

            # Запрашиваем расписание (уроки) для группы
            params = {
                'academic_year_id': academic_year_id,
                'expose': 'true',
                'from': start_date,
                'group_id': group_id,
                'page': 1,
                'per_page': 1000,
                'pid': self.auth.pid,
                'to': end_date,
                'with_course_calendar_info': 'true',
                'with_group_class_subject_info': 'true',
                'with_lesson_info': 'true'
            }

            data = self.auth.fetch(
                "https://dnevnik.mos.ru/jersey/api/schedule_items",
                params=params
            )

            if not data:
                self.ktp_cache[cache_key] = (False, 0, 0)
                return False, 0, 0

            items = self._extract_list(data)

            total_lessons = 0
            lessons_with_names = 0

            for item in items:
                total_lessons += 1

                # Проверяем название урока
                lesson_name = item.get('lesson_name') or ''
                if not lesson_name:
                    # Пробуем альтернативные поля
                    lesson_name = item.get('topic_name') or ''

                lesson_name = str(lesson_name).strip()
                if lesson_name:
                    lessons_with_names += 1

            has_ktp = lessons_with_names > 0
            self.ktp_cache[cache_key] = (has_ktp, lessons_with_names, total_lessons)
            return has_ktp, lessons_with_names, total_lessons

        except Exception as e:
            self._log(f"[KTP-MAIN] ❌ Ошибка проверки группы {group_id}: {e}")
            self.ktp_cache[cache_key] = (False, 0, 0)
            return False, 0, 0