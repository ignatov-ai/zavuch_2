# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import datetime, timedelta


class MarksDataCollector:
	"""Класс для сбора данных об отметках"""

	def __init__(self, auth):
		self.auth = auth
		self.teacher_cache = {}  # Кэш: {teacher_id: "Имя учителя"}
		self.group_teacher_cache = {}  # Кэш: {group_id: "Имя учителя"}
		self.periods_cache = {}
		self.periods_mapping = {}
		self.lesson_plans_cache = {}  # Кэш для КТП: {group_id: lessons_by_date}
		self.medical_cache = {}  # Кэш для данных о болезни: {student_id: {date: type}}
		self.class_level_cache = {}  # Кэш для уровня класса

	def _load_and_map_periods(self):
		"""
        Загружает расписание периодов и создает маппинг ID -> номер триместра.
        Использует фиксированные ID для надежности.
        """
		if self.periods_mapping:
			return self.periods_mapping

		try:
			# Фиксированные ID триместров
			self.periods_mapping = {
				83558: 1,  # Триместр 1
				83559: 2,  # Триместр 2
				83560: 3  # Триместр 3
			}

			# Для информации пытаемся получить названия периодов из API
			data = self.auth.fetch(
				"core/api/attestation_periods_schedules",
				params={
					'school_id': self.auth.sid,
					'academic_year_id': self.auth.aid
				}
			)

			if data and len(data) > 0:
				schedule = data[0]
				all_periods = schedule.get('periods', [])

				# Заполняем кэш периодов
				for period in all_periods:
					period_id = period.get('id')
					if period_id in self.periods_mapping:
						trimester_num = self.periods_mapping[period_id]
						self.periods_cache[period_id] = {
							'id': period_id,
							'name': period.get('name'),
							'begin_date': period.get('begin_date'),
							'end_date': period.get('end_date'),
							'trimester': trimester_num
						}

			return self.periods_mapping

		except Exception as e:
			# Возвращаем фиксированный маппинг даже при ошибке
			self.periods_mapping = {
				83558: 1,
				83559: 2,
				83560: 3
			}
			return self.periods_mapping

	def get_attestation_periods(self):
		"""Возвращает кэшированные периоды аттестации."""
		if not self.periods_cache:
			self._load_and_map_periods()
		return self.periods_cache

	def get_lesson_plans(self, group_id):
		"""
        Получение календарно-тематического планирования для группы
        через API calendar_plans.
        Возвращает словарь {date_key: количество_уроков}
        """
		try:
			# Проверяем кэш
			if group_id in self.lesson_plans_cache:
				return self.lesson_plans_cache[group_id]

			params = {
				'group_id': group_id,
				'pid': self.auth.pid
			}

			data = self.auth.fetch(
				"https://dnevnik.mos.ru/jersey/api/calendar_plans",
				params=params
			)

			lessons_by_date = defaultdict(int)

			if not data or len(data) == 0:
				self.lesson_plans_cache[group_id] = lessons_by_date
				return lessons_by_date

			# Проходим по всем планам (обычно один)
			for plan in data:
				lessons = plan.get('lessons', [])
				for lesson in lessons:
					date_array = lesson.get('date')
					if date_array and len(date_array) == 3:
						# Формат даты из API: [год, месяц, день]
						year, month, day = date_array
						date_key = f"{day:02d}.{month:02d}.{year}"
						lessons_by_date[date_key] += 1

			# Сохраняем в кэш
			self.lesson_plans_cache[group_id] = lessons_by_date
			return lessons_by_date

		except Exception as e:
			print(f"Ошибка получения КТП: {e}")
			return defaultdict(int)

	def get_medical_recommendations(self, student_ids, start_date=None, end_date=None):
		"""
        Получение медицинских рекомендаций (болезни) для списка учеников
        Возвращает словарь {student_id: {date: type}}
        """
		try:
			if not student_ids:
				return {}

			# Определяем учебный год
			now = datetime.now()
			if now.month >= 9:
				start = f"{now.year}-09-01"
				end = f"{now.year + 1}-08-31"
			else:
				start = f"{now.year - 1}-09-01"
				end = f"{now.year}-08-31"

			if start_date:
				start = start_date
			if end_date:
				end = end_date

			all_recommendations = {}

			# Разбиваем на порции по 50 ID (ограничение API)
			for i in range(0, len(student_ids), 50):
				batch_ids = student_ids[i:i + 50]
				ids_param = ','.join(str(pid) for pid in batch_ids)

				params = {
					'start_date': start,
					'end_date': end,
					'pid': self.auth.pid,
					'student_profile_ids': ids_param,
					'per_page': 1000,
					'page': 1
				}

				# Получаем все страницы
				page = 1
				while True:
					params['page'] = page
					data = self.auth.fetch(
						"https://dnevnik.mos.ru/core/api/emias_medical_recommendations",
						params=params
					)

					if not data:
						break

					for rec in data:
						student_id = rec.get('student_profile_id')
						rec_date = rec.get('date')
						rec_type = rec.get('type')

						if student_id and rec_date:
							if student_id not in all_recommendations:
								all_recommendations[student_id] = {}

							# Сохраняем тип (SICK, SICK_WITH_INFECTION, EXEMPT)
							all_recommendations[student_id][rec_date] = rec_type

					if len(data) < 1000:
						break
					page += 1

			return all_recommendations

		except Exception as e:
			print(f"Ошибка получения медицинских рекомендаций: {e}")
			return {}

	def get_classes(self):
		"""Получение списка всех классов школы (только 1-11 классы)"""
		try:
			data = self.auth.fetch(
				"core/api/class_units",
				params={
					'with_home_based': 'true',
					'academic_year_id': self.auth.aid
				}
			)

			if not data:
				return []

			classes = []
			for cl in data:
				class_name = cl.get("name", "").upper()
				class_level = cl.get("class_level_id", 0)

				# Оставляем только классы с 1 по 11
				if not class_level or class_level < 1 or class_level > 11:
					continue

				classes.append({
					"id": cl.get("id"),
					"name": class_name,
					"level": class_level,
					"student_count": cl.get("student_count", 0),
				})

			return classes

		except Exception as e:
			return []

	def get_groups_for_class(self, class_id):
		"""
        Получение групп (предметов) для класса.
        Сохраняет информацию об учителях для каждой группы.
        """
		try:
			# Используем новый эндпоинт для получения групп с учителями
			params = {
				'academic_year_id': self.auth.aid,
				'class_unit_ids': class_id,
				'with_teacher_loads': 'true',
				'with_lessons_only': 'false',
				'with_periods_schedule_id': 'true'
			}

			# Пробуем новый API
			data = self.auth.fetch(
				"https://school.mos.ru/api/ej/plan/teacher/v1/groups",
				params=params
			)

			if data:
				# Проходим по всем группам и кэшируем учителей
				for group in data:
					group_id = group.get('id')
					teachers_data = group.get('teachers', [])

					if teachers_data and len(teachers_data) > 0:
						# Берем первого учителя (обычно он один)
						teacher_info = teachers_data[0]
						teacher_id = teacher_info.get('id')

						# Формируем полное имя учителя
						last_name = teacher_info.get('last_name', '')
						first_name = teacher_info.get('first_name', '')
						middle_name = teacher_info.get('middle_name', '')
						full_name = teacher_info.get('full_name', '')

						if not full_name:
							name_parts = []
							if last_name:
								name_parts.append(last_name)
							if first_name:
								name_parts.append(first_name)
							if middle_name:
								name_parts.append(middle_name)
							full_name = ' '.join(name_parts).strip()

						if full_name:
							# Очищаем имя от лишних пробелов
							full_name = ' '.join(full_name.split())

							# Кэшируем по ID учителя
							if teacher_id:
								self.teacher_cache[str(teacher_id)] = full_name

							# Кэшируем по ID группы (самый надежный способ)
							if group_id:
								self.group_teacher_cache[str(group_id)] = full_name

				return data

		except Exception as e:
			pass

		# Если новый метод не сработал, пробуем старый
		try:
			data = self.auth.fetch_paginated(
				"jersey/api/groups",
				params={
					'class_unit_id': class_id,
					'academic_year_id': self.auth.aid,
					'with_lessons_only': 'true'
				}
			) or []

			return data

		except Exception as e:
			return []

	def get_students_for_group(self, group_id, class_id):
		"""Получение списка учеников для группы с итоговыми отметками и ГПА"""
		try:
			# Получаем уровень класса (если ещё не знаем)
			if class_id not in self.class_level_cache:
				class_data = self.auth.fetch(
					"core/api/class_units",
					params={'ids': class_id}
				)
				if class_data and len(class_data) > 0:
					self.class_level_cache[class_id] = class_data[0].get('class_level_id', 0)
				else:
					self.class_level_cache[class_id] = 0

			data = self.auth.fetch(
				"core/api/student_profiles",
				params={
					'academic_year_id': self.auth.aid,
					'class_unit_ids': class_id,
					'group_ids': group_id,
					'per_page': 1000,
					'pid': self.auth.pid,
					'with_archived_groups': 'true',
					'with_deleted': 'true',
					'with_final_marks': 'true',
					'with_groups': 'true',
					'with_home_based': 'true'
				}
			) or []

			# Собираем ID учеников
			student_ids = []
			# Обработка итоговых отметок (в зависимости от класса)
			# Обработка итоговых отметок (в зависимости от класса)
			for student in data:
				# Получаем уровень класса
				student_class_level = self.class_level_cache.get(class_id, 0)

				# Определяем маппинг периодов в зависимости от класса
				if student_class_level in [5, 6, 7, 8, 9]:
					# Для 5-9 классов: триместры
					PERIOD_MAPPING = {
						83558: 'Т1',  # Триместр 1
						83559: 'Т2',  # Триместр 2
						83560: 'Т3',  # Триместр 3
					}
				else:
					# Для 10-11 классов: полугодия
					PERIOD_MAPPING = {
						83561: 'П1',  # Полугодие 1
						83562: 'П2',  # Полугодие 2
					}

				final_marks_by_period = {}
				gpa_mark = ''  # Отметка за промежуточную аттестацию (ГПА)
				attestation_mark = ''  # Аттестационная отметка (для 9 и 11)

				for mark in student.get('final_marks', []):
					period_id = mark.get('attestation_period_id')
					value_obj = mark.get('value', {})
					mark_type = mark.get('mark_type', '')

					# Получаем значение отметки
					if isinstance(value_obj, dict):
						value = value_obj.get('parsedValue') or value_obj.get('source')
					else:
						value = value_obj

					# Обработка "А/З" (академическая задолженность)
					if value == 'А/З' or (isinstance(value, str) and 'А/З' in value):
						mark_value = 'А/З'
					elif value is not None:
						try:
							if isinstance(value, (int, float)) or (
									isinstance(value, str) and value.replace('.', '').isdigit()):
								mark_value = str(int(float(value)))
							else:
								mark_value = str(value)
						except:
							mark_value = str(value)
					else:
						continue

					# Если это ГПА (промежуточная аттестация)
					if mark_type == 'intermediate_attestation':
						gpa_mark = mark_value
						continue

					# Если это аттестационная отметка (для 9 и 11)
					if mark_type in ['attestation', 'final', 'final_attestation']:
						attestation_mark = mark_value
						continue

					# Если есть period_id и он известен (триместр или полугодие)
					if period_id and period_id in PERIOD_MAPPING:
						period_name = PERIOD_MAPPING[period_id]
						final_marks_by_period[period_name] = mark_value

					# Проверяем, является ли отметка годовой (ВАЖНО!)
					if mark.get('is_year_mark'):
						final_marks_by_period['Год'] = mark_value

				student['final_marks_by_period'] = final_marks_by_period
				student['gpa_mark'] = gpa_mark
				student['attestation_mark'] = attestation_mark

			return data

		except Exception as e:
			print(f"Ошибка получения учеников: {e}")
			return []

	def get_marks_for_group(self, group_id):
		"""
        Получение всех отметок и пропусков для группы.
        Сохраняет все отметки за одну дату (через запятую в одной ячейке).
        Если на дату есть и пропуск, и отметка(и), в ячейке будет: н,5(1) или б,5(2),4(1)
        """
		try:
			all_records = []  # Общий список для отметок и пропусков
			now = datetime.now()

			# Определяем учебный год
			if now.month >= 9:
				start_date = f"01.09.{now.year}"
				end_date = f"31.08.{now.year + 1}"
			else:
				start_date = f"01.09.{now.year - 1}"
				end_date = f"31.08.{now.year}"

			# 1. ЗАПРАШИВАЕМ ОТМЕТКИ
			page = 1
			per_page = 1000

			while True:
				params = {
					'created_at_from': start_date,
					'created_at_to': end_date,
					'group_ids': group_id,
					'per_page': per_page,
					'page': page,
					'pid': self.auth.pid
				}

				page_data = self.auth.fetch("core/api/marks", params=params)

				if not page_data:
					break

				# Добавляем флаг, что это отметка
				for record in page_data:
					record['record_type'] = 'mark'

				all_records.extend(page_data)

				if len(page_data) < per_page:
					break

				page += 1

			# 2. ЗАПРАШИВАЕМ ПРОПУСКИ
			possible_endpoints = [
				("core/api/absences", {'group_ids': group_id}),
				("core/api/attendances", {'group_ids': group_id}),
				("core/api/student_absences", {'group_ids': group_id}),
			]

			for endpoint, base_params in possible_endpoints:
				try:
					params = base_params.copy()
					params.update({
						'date_from': start_date,
						'date_to': end_date,
						'per_page': 1000,
						'pid': self.auth.pid
					})

					if 'academic_year_id' not in params and hasattr(self.auth, 'aid'):
						params['academic_year_id'] = self.auth.aid

					absences_data = self.auth.fetch(endpoint, params=params)

					if absences_data:
						for record in absences_data:
							record['record_type'] = 'absence'

							student_id = (record.get('student_id') or
										  record.get('student_profile_id') or
										  record.get('person_id'))

							absence_date = (record.get('date') or
											record.get('absence_date') or
											record.get('lesson_date'))

							if student_id and absence_date:
								record['student_profile_id'] = student_id
								record['date'] = absence_date
								record['name'] = 'н'
								record['weight'] = 0
								all_records.append(record)

						# Если нашли пропуски, прекращаем поиск
						break

				except Exception:
					continue

			# 3. ГРУППИРУЕМ ЗАПИСИ ПО УЧЕНИКУ И ДАТЕ
			grouped_by_student_date = defaultdict(list)

			for record in all_records:
				student_id = record.get('student_profile_id')
				date = record.get('date')

				if student_id is not None and date:
					student_id_str = str(student_id)
					key = f"{student_id_str}_{date}"
					grouped_by_student_date[key].append(record)

			# 4. СОЗДАЕМ ИТОГОВЫЕ ЗАПИСИ - ОДНА ЗАПИСЬ НА ДАТУ С ТЕКСТОМ
			final_marks = []

			for key, records in grouped_by_student_date.items():
				if not records:
					continue

				# Разбираем ключ
				parts = key.split('_', 1)
				if len(parts) != 2:
					continue

				student_id_str, date = parts

				# Анализируем все записи для этой даты
				mark_values = []  # Список всех отметок
				has_absence = False
				has_sickness = False
				is_control = False
				teacher_id = None

				# Собираем информацию о пропусках и болезнях
				absence_types = set()

				for record in records:
					record_type = record.get('record_type', 'mark')
					teacher_id = teacher_id or record.get('teacher_id')

					if record_type == 'absence':
						absence_type = record.get('name', 'н')
						if absence_type == 'н':
							absence_types.add('н')
							has_absence = True
						elif absence_type == 'б':
							absence_types.add('б')
							has_sickness = True
							has_absence = True
					else:  # это отметка
						val = record.get('name') or record.get('value') or record.get('mark')
						if val is not None:
							mark_value = str(val)
						else:
							continue

						weight = record.get('weight') or record.get('coefficient') or 1
						try:
							weight = int(weight)
						except:
							weight = 1

						# Проверяем, контрольная ли это работа
						mark_type = record.get('type', '')
						work_type = record.get('work_type', '')
						comment = record.get('comment', '')

						is_control = is_control or (
								'контрольн' in str(mark_type).lower() or
								'контрольн' in str(work_type).lower() or
								'контрольн' in str(comment).lower()
						)

						# Добавляем отметку в список
						mark_values.append({
							'value': mark_value,
							'weight': weight
						})

				# ФОРМИРУЕМ ТЕКСТ ДЛЯ ЯЧЕЙКИ
				cell_text_parts = []

				# Сначала добавляем пропуски и болезни (в порядке: н, затем б)
				if 'н' in absence_types:
					cell_text_parts.append('н')
				if 'б' in absence_types:
					cell_text_parts.append('б')

				# Затем добавляем все отметки с весами
				for mv in mark_values:
					if is_control:
						cell_text_parts.append(f"{mv['value']}({mv['weight']}К)")
					else:
						cell_text_parts.append(f"{mv['value']}({mv['weight']})")

				# Объединяем всё через запятую
				cell_text = ','.join(cell_text_parts) if cell_text_parts else ''

				new_record = {
					'student_profile_id': int(student_id_str) if student_id_str.isdigit() else student_id_str,
					'date': date,
					'cell_text': cell_text,
					'has_absence': has_absence,
					'has_sickness': has_sickness,
					'teacher_id': teacher_id,
				}

				final_marks.append(new_record)

			return final_marks

		except Exception as e:
			print(f"Ошибка в get_marks_for_group: {e}")
			return []

	def get_teacher_name(self, teacher_id=None, group_id=None):
		"""
        Получение имени учителя по ID учителя или ID группы.
        """
		# 1. Если есть group_id, сначала ищем в кэше групп
		if group_id:
			group_id_str = str(group_id)
			if group_id_str in self.group_teacher_cache:
				teacher_name = self.group_teacher_cache[group_id_str]
				if teacher_id and str(teacher_id) not in self.teacher_cache:
					self.teacher_cache[str(teacher_id)] = teacher_name
				return teacher_name

		# 2. Если есть teacher_id, ищем в кэше учителей
		if teacher_id:
			teacher_id_str = str(teacher_id)
			if teacher_id_str in self.teacher_cache:
				return self.teacher_cache[teacher_id_str]

			# 3. Если не нашли в кэше, пробуем получить через API teacher_profiles
			try:
				params = {
					'ids': teacher_id,
					'pid': self.auth.pid
				}

				if hasattr(self.auth, 'aid') and self.auth.aid:
					params['academic_year_id'] = self.auth.aid

				data = self.auth.fetch("core/api/teacher_profiles", params)

				if data and len(data) > 0:
					teacher_data = data[0]

					name = (teacher_data.get('short_name') or
							teacher_data.get('name') or
							teacher_data.get('full_name') or
							teacher_data.get('display_name'))

					if not name:
						last_name = teacher_data.get('last_name', '')
						first_name = teacher_data.get('first_name', '')
						middle_name = teacher_data.get('middle_name', '')

						name_parts = []
						if last_name:
							name_parts.append(last_name)
						if first_name:
							name_parts.append(first_name)
						if middle_name:
							name_parts.append(middle_name)
						name = ' '.join(name_parts).strip()

					if name:
						name = ' '.join(name.split())
						self.teacher_cache[teacher_id_str] = name
						return name

			except Exception:
				pass

		# 4. Пробуем получить учителя из группы через старый API
		if group_id:
			try:
				data = self.auth.fetch("jersey/api/groups", {
					'ids': group_id,
					'pid': self.auth.pid,
					'academic_year_id': self.auth.aid
				})

				if data and isinstance(data, list) and len(data) > 0:
					group = data[0]

					found_teacher_id = (group.get('teacher_id') or
										group.get('main_teacher_id') or
										group.get('responsible_teacher_id'))

					if found_teacher_id:
						return self.get_teacher_name(found_teacher_id, group_id)

					teacher_name = (group.get('teacher_name') or
									group.get('main_teacher_name') or
									group.get('responsible_teacher_name'))

					if teacher_name:
						teacher_name = ' '.join(teacher_name.split())
						if group_id:
							self.group_teacher_cache[str(group_id)] = teacher_name
						return teacher_name

			except Exception:
				pass

		# Если ничего не найдено
		return "Не указан"