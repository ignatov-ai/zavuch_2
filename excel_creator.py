# -*- coding: utf-8 -*-
import os
from collections import defaultdict
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime


def create_class_marks_excel_file(class_name, groups_data, collector, output_folder, signal_callback=None):
	"""
	Создает Excel-файл для класса.
	КАЖДАЯ ГРУППА предмета сохраняется на отдельном листе.

	Для 5-9 классов: Т1, Т2, Т3, ГПА, Год
	Для 10-11 классов: П1, П2, ГПА, Год
	Для 9 и 11 классов дополнительно: Аттестация
	"""
	wb = Workbook()

	if "Sheet" in wb.sheetnames:
		wb.remove(wb["Sheet"])

	total_subjects = 0

	if signal_callback:
		signal_callback(class_name)

	# ОПРЕДЕЛЯЕМ ТИП КЛАССА ОДИН РАЗ ДЛЯ ВСЕГО ФАЙЛА
	is_high_school = False
	class_level = 0
	if class_name and len(class_name) >= 2:
		try:
			level_str = class_name.split('-')[0]
			class_level = int(''.join(filter(str.isdigit, level_str)))
			if class_level in [10, 11]:
				is_high_school = True
		except:
			pass

	need_attestation = (class_level in [9, 11])

	# НЕ ГРУППИРУЕМ ПРЕДМЕТЫ - ОБРАБАТЫВАЕМ КАЖДУЮ ГРУППУ ОТДЕЛЬНО
	for group_data in groups_data:
		subject_name = group_data["subject_name"]
		group = group_data["group"]
		students = group_data["students"]
		marks = group_data["marks"]
		teacher_name = group_data.get("teacher_name", "Не указан")
		group_id = group.get("id", "")
		group_name = group.get("name", "")

		if not students or len(students) == 0:
			continue

		total_subjects += 1

		if signal_callback:
			signal_callback(f"{subject_name} ({group_name})")

		# Формируем имя листа с указанием группы
		sheet_name = _get_group_sheet_name(subject_name, group_name, group_id, wb.sheetnames)
		ws = wb.create_sheet(title=sheet_name)

		# Информационные строки
		_create_info_rows(ws, subject_name, group_name, group_id, teacher_name)

		# Получаем КТП для этой группы
		lesson_plans = collector.get_lesson_plans(group_id)

		# Создаем словарь медицинских рекомендаций по ученикам
		medical_by_student = {}
		for student in students:
			student_id = student.get('id')
			if student_id:
				medical_by_student[student_id] = student.get('medical_recommendations', {})

		# Обработка текущих отметок с учетом болезни
		student_marks, lesson_dates = _process_marks_with_medical(marks, lesson_plans, medical_by_student)

		if not lesson_dates:
			wb.remove(ws)
			continue

		# Сортируем уроки
		sorted_lessons = _sort_lessons(lesson_dates)

		# Создание шапки с отдельными столбцами для каждого урока
		col_idx = _create_header_with_lessons(ws, sorted_lessons)

		# Добавляем столбцы для итоговых отметок
		if is_high_school:
			# Для 10-11 классов: П1, П2
			p1_col = col_idx
			ws.cell(row=4, column=p1_col, value="П1")
			ws.cell(row=5, column=p1_col, value="")
			ws.cell(row=6, column=p1_col, value="итог")
			col_idx += 1

			p2_col = col_idx
			ws.cell(row=4, column=p2_col, value="П2")
			ws.cell(row=5, column=p2_col, value="")
			ws.cell(row=6, column=p2_col, value="итог")
			col_idx += 1

			t1_col, t2_col, t3_col = p1_col, p2_col, None
		else:
			# Для 5-9 классов: Т1, Т2, Т3
			t1_col = col_idx
			ws.cell(row=4, column=t1_col, value="Т1")
			ws.cell(row=5, column=t1_col, value="")
			ws.cell(row=6, column=t1_col, value="итог")
			col_idx += 1

			t2_col = col_idx
			ws.cell(row=4, column=t2_col, value="Т2")
			ws.cell(row=5, column=t2_col, value="")
			ws.cell(row=6, column=t2_col, value="итог")
			col_idx += 1

			t3_col = col_idx
			ws.cell(row=4, column=t3_col, value="Т3")
			ws.cell(row=5, column=t3_col, value="")
			ws.cell(row=6, column=t3_col, value="итог")
			col_idx += 1

		# ДОБАВЛЯЕМ СТОЛБЕЦ ГПА
		gpa_col = col_idx
		ws.cell(row=4, column=gpa_col, value="ГПА")
		ws.cell(row=5, column=gpa_col, value="")
		ws.cell(row=6, column=gpa_col, value="итог")
		col_idx += 1

		# ДОБАВЛЯЕМ СТОЛБЕЦ ГОД
		year_col = col_idx
		ws.cell(row=4, column=year_col, value="Год")
		ws.cell(row=5, column=year_col, value="")
		ws.cell(row=6, column=year_col, value="итог")
		col_idx += 1

		# Добавляем столбец аттестации (только для 9 и 11 классов)
		if need_attestation:
			attestation_col = col_idx
			ws.cell(row=4, column=attestation_col, value="Аттестация")
			ws.cell(row=5, column=attestation_col, value="")
			ws.cell(row=6, column=attestation_col, value="итог")
			col_idx += 1
		else:
			attestation_col = None

		# Обработка учеников
		students_by_id = _process_students(students)
		sorted_students = sorted(students_by_id.items(), key=lambda x: x[1])

		# Заполнение данных учеников
		_fill_student_data_with_medical(ws, sorted_students, student_marks, sorted_lessons, 3)

		# Заполняем итоговые отметки
		_fill_final_marks(ws, sorted_students, students,
						  t1_col, t2_col, t3_col, is_high_school,
						  attestation_col, gpa_col, year_col)

		# Применение стилей
		_apply_styles(ws, col_idx, len(sorted_students))

		# Автоподбор ширины
		_auto_adjust_width(ws, col_idx, len(sorted_students))

		ws.freeze_panes = 'C7'

	if len(wb.sheetnames) == 0:
		return None

	safe_class = class_name.replace('-', '_').replace(' ', '_')
	filename = f"{safe_class}_журнал.xlsx"
	filepath = os.path.join(output_folder, filename)

	wb.save(filepath)
	return filepath


def _get_group_sheet_name(subject_name, group_name, group_id, existing_names):
	"""Формирует понятное имя листа для группы предмета"""
	# Очищаем от лишних символов
	clean_subject = subject_name[:25].replace('/', '_').replace('\\', '_').replace(':', '_')

	# Извлекаем тип группы из названия
	group_type = ""
	group_name_lower = group_name.lower() if group_name else ""

	if "соц-эк" in group_name_lower or "социально" in group_name_lower:
		group_type = "соц-эк"
	elif "инж" in group_name_lower or "инженер" in group_name_lower:
		group_type = "инж"
	elif "мат" in group_name_lower or "матем" in group_name_lower:
		group_type = "мат"
	elif "гум" in group_name_lower or "гуманит" in group_name_lower:
		group_type = "гум"
	elif "ест" in group_name_lower or "естеств" in group_name_lower:
		group_type = "ест"
	elif "фил" in group_name_lower or "филол" in group_name_lower:
		group_type = "фил"

	if group_type:
		sheet_name = f"{clean_subject} ({group_type})"
	else:
		# Используем последние 4 цифры ID группы как уникальный идентификатор
		short_id = str(group_id)[-4:] if group_id else ""
		if short_id:
			sheet_name = f"{clean_subject} ({short_id})"
		else:
			sheet_name = clean_subject

	# Обеспечиваем уникальность
	base = sheet_name[:31]
	counter = 1
	while sheet_name in existing_names:
		sheet_name = f"{base[:28]}_{counter}"
		counter += 1

	return sheet_name


def _get_valid_sheet_name(base_name, existing_names):
	"""Создание допустимого имени листа"""
	sheet_name = base_name[:25] if base_name else "Без названия"
	invalid_chars = [':', '\\', '/', '?', '*', '[', ']']
	for char in invalid_chars:
		sheet_name = sheet_name.replace(char, '_')

	base = sheet_name
	counter = 1
	while sheet_name in existing_names:
		sheet_name = f"{base}_{counter}"[:31]
		counter += 1

	return sheet_name


def _create_info_rows(ws, subject_name, group_name, group_id, teacher_name):
	"""Создание информационных строк"""
	ws.cell(row=1, column=1, value=f"Предмет: {subject_name}")
	ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2)
	ws.cell(row=1, column=1).font = Font(bold=True, size=12)

	ws.cell(row=2, column=1, value=f"Группа: {group_name} (ID: {group_id})")
	ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
	ws.cell(row=2, column=1).font = Font(bold=True)

	ws.cell(row=3, column=1, value=f"Учитель: {teacher_name}")
	ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=2)
	ws.cell(row=3, column=1).font = Font(bold=True, color="000080")


def _process_marks_with_medical(marks, lesson_plans, medical_by_student):
	"""
	Группировка отметок по ученикам, дате и номеру урока с учетом болезни.
	Если КТП пустое или заканчивается раньше, добавляем даты из реальных отметок.
	"""
	if not isinstance(marks, list):
		return defaultdict(dict), set()

	student_marks = defaultdict(dict)
	all_lessons = set()

	# 1. Сначала собираем все даты из реальных отметок
	dates_from_marks = set()
	for mark in marks:
		if isinstance(mark, dict):
			date = mark.get("date", "")
			if date:
				dates_from_marks.add(date)

	# 2. Пытаемся получить даты из КТП
	ktp_dates = set()
	if lesson_plans and len(lesson_plans) > 0:
		for date_key, lesson_count in lesson_plans.items():
			try:
				day, month, year = date_key.split('.')
				day_int = int(day)
				month_int = int(month)

				for lesson_num in range(lesson_count):
					lesson_id = f"{date_key}_{lesson_num}"
					all_lessons.add((month_int, day_int, date_key, lesson_num, lesson_id))
					ktp_dates.add(date_key)
			except:
				continue

	# 3. Если КТП закончилось раньше, чем есть отметки, добавляем недостающие даты
	max_ktp_date = None
	for date_str in ktp_dates:
		try:
			day, month, year = date_str.split('.')
			current = datetime(int(year), int(month), int(day))
			if max_ktp_date is None or current > max_ktp_date:
				max_ktp_date = current
		except:
			pass

	for date_str in dates_from_marks:
		try:
			day, month, year = date_str.split('.')
			current = datetime(int(year), int(month), int(day))

			if max_ktp_date is None or current > max_ktp_date:
				day_int = int(day)
				month_int = int(month)
				lesson_num = 0
				all_lessons.add((month_int, day_int, date_str, lesson_num, f"{date_str}_{lesson_num}"))
		except:
			continue

	# 4. Если КТП вообще пустое, создаём уроки на основе всех дат из отметок
	if not all_lessons and dates_from_marks:
		for date_str in dates_from_marks:
			try:
				day, month, year = date_str.split('.')
				day_int = int(day)
				month_int = int(month)
				lesson_num = 0
				all_lessons.add((month_int, day_int, date_str, lesson_num, f"{date_str}_{lesson_num}"))
			except:
				continue

	# 5. Группируем отметки по ученику и уроку
	for mark in marks:
		if not isinstance(mark, dict):
			continue

		student_id = mark.get("student_profile_id")
		date = mark.get("date", "")
		cell_text = mark.get("cell_text", "")
		has_sickness = mark.get("has_sickness", False)

		if not cell_text and has_sickness:
			cell_text = "б"

		if date and student_id:
			try:
				lesson_key = (date, 0)

				if student_id not in student_marks:
					student_marks[student_id] = {}

				student_marks[student_id][lesson_key] = {
					'cell_text': cell_text,
					'has_sickness': has_sickness
				}

			except Exception:
				continue

	return student_marks, list(all_lessons)


def _sort_lessons(lessons):
	"""Сортировка уроков по дате"""

	def lesson_sort_key(lesson):
		month, day, date_key, lesson_num, full_id = lesson
		if month >= 9:
			return (month - 9, day, lesson_num)
		else:
			return (month + 4, day, lesson_num)

	return sorted(lessons, key=lesson_sort_key)


def _create_header_with_lessons(ws, sorted_lessons):
	"""Создание шапки журнала с отдельными столбцами для каждого урока"""
	col_idx = 3

	date_lesson_count = defaultdict(int)

	for month_num, day_num, date_key, lesson_num, full_id in sorted_lessons:
		date_lesson_count[date_key] += 1
		current_lesson_num = date_lesson_count[date_key]

		ws.cell(row=4, column=col_idx, value=month_num)
		ws.cell(row=5, column=col_idx, value=day_num)
		if current_lesson_num > 1:
			ws.cell(row=6, column=col_idx, value=f"урок {current_lesson_num}")
		else:
			ws.cell(row=6, column=col_idx, value="оц")

		col_idx += 1

	return col_idx


def _process_students(students):
	"""Создание словаря учеников"""
	students_by_id = {}
	for student in students:
		student_id = student.get("id")
		if student_id:
			full_name = _get_student_full_name(student)
			students_by_id[student_id] = full_name

	return students_by_id


def _get_student_full_name(student):
	"""Формирование полного имени ученика"""
	last_name = student.get("last_name", "")
	first_name = student.get("first_name", "")
	middle_name = student.get("middle_name", "")

	if not last_name and student.get("user_name"):
		name_parts = student.get("user_name", "").split()
		if len(name_parts) >= 1:
			last_name = name_parts[0]
		if len(name_parts) >= 2:
			first_name = name_parts[1]
		if len(name_parts) >= 3:
			middle_name = name_parts[2]

	name_parts = []
	if last_name:
		name_parts.append(last_name)
	if first_name:
		name_parts.append(first_name)
	if middle_name:
		name_parts.append(middle_name)

	full_name = " ".join(name_parts).strip()
	return full_name or student.get("short_name", "")


def _fill_student_data_with_medical(ws, sorted_students, student_marks, sorted_lessons, start_col):
	"""Заполнение данных учеников - каждая отметка в своем столбце"""
	start_data_row = 7

	for row_idx, (student_id, student_name) in enumerate(sorted_students, start=start_data_row):
		ws.cell(row=row_idx, column=1, value=row_idx - start_data_row + 1)
		ws.cell(row=row_idx, column=2, value=student_name)

		student_marks_dict = student_marks.get(student_id, {})

		col = start_col
		for month_num, day_num, date_key, lesson_num, full_id in sorted_lessons:
			lesson_key = (date_key, lesson_num)

			mark_record = student_marks_dict.get(lesson_key)

			if mark_record and isinstance(mark_record, dict):
				cell_value = mark_record.get('cell_text', '')
				ws.cell(row=row_idx, column=col, value=cell_value)

			col += 1


def _fill_final_marks(ws, sorted_students, students_data,
					  period1_col, period2_col, period3_col,
					  is_high_school, attestation_col=None, gpa_col=None, year_col=None):
	"""Заполнение итоговых отметок"""
	start_data_row = 7

	students_by_id = {s.get('id'): s for s in students_data if s.get('id')}

	for row_idx, (student_id, student_name) in enumerate(sorted_students, start=start_data_row):
		student = students_by_id.get(student_id, {})
		final_marks = student.get('final_marks_by_period', {})
		attestation_mark = student.get('attestation_mark', '')
		gpa_mark = student.get('gpa_mark', '')

		if is_high_school:
			p1_value = final_marks.get('П1', '')
			p2_value = final_marks.get('П2', '')

			if period1_col:
				ws.cell(row=row_idx, column=period1_col, value=p1_value)
			if period2_col:
				ws.cell(row=row_idx, column=period2_col, value=p2_value)
		else:
			t1_value = final_marks.get('Т1', '')
			t2_value = final_marks.get('Т2', '')
			t3_value = final_marks.get('Т3', '')

			if period1_col:
				ws.cell(row=row_idx, column=period1_col, value=t1_value)
			if period2_col:
				ws.cell(row=row_idx, column=period2_col, value=t2_value)
			if period3_col:
				ws.cell(row=row_idx, column=period3_col, value=t3_value)

		if gpa_col:
			ws.cell(row=row_idx, column=gpa_col, value=gpa_mark)

		if year_col:
			year_value = final_marks.get('Год', '')
			ws.cell(row=row_idx, column=year_col, value=year_value)

		if attestation_col:
			ws.cell(row=row_idx, column=attestation_col, value=attestation_mark)


def _apply_styles(ws, col_idx, num_students):
	"""Применение стилей к ячейкам"""
	thin_border = Border(
		left=Side(style='thin'),
		right=Side(style='thin'),
		top=Side(style='thin'),
		bottom=Side(style='thin')
	)

	info_fill = PatternFill(start_color="E0E0E0", end_color="E0E0E0", fill_type="solid")

	for row in [1, 2, 3]:
		for col in range(1, 3):
			cell = ws.cell(row=row, column=col)
			cell.fill = info_fill
			cell.border = thin_border

	for row in [4, 5, 6]:
		for col in range(1, col_idx):
			cell = ws.cell(row=row, column=col)
			cell.alignment = Alignment(horizontal='center', vertical='center')
			cell.font = Font(bold=True)
			cell.border = thin_border
			if row == 4:
				cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

	start_data_row = 7
	for row in range(start_data_row, start_data_row + num_students):
		for col in range(1, col_idx):
			cell = ws.cell(row=row, column=col)
			cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
			cell.border = thin_border
			if col == 2:
				cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)


def _auto_adjust_width(ws, col_idx, num_students):
	"""Автоматическая подстройка ширины колонок"""
	ws.column_dimensions['A'].width = 5
	start_data_row = 7

	for col in range(2, col_idx):
		column_letter = get_column_letter(col)
		max_length = 0

		for row in range(1, start_data_row + num_students):
			cell = ws.cell(row=row, column=col)
			if cell.value:
				cell_value = str(cell.value)
				cell_length = len(cell_value) + (2 if col >= 3 and row >= start_data_row else 1)
				max_length = max(max_length, cell_length)

		min_width = 15 if col == 2 else 8
		ws.column_dimensions[column_letter].width = max(max_length, min_width)