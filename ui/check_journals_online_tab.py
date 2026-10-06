# -*- coding: utf-8 -*-
"""
Вкладка «🔍 Проверка журналов Online».
Онлайн-проверка накопляемости, средних баллов, КР и пропусков
без скачивания Excel-журналов.

Расположена сразу после «🔍 Проверка журналов».

Логика:
  • Отметки — /core/api/marks по group_ids класса (включая метагруппы).
  • Пропуски — /core/api/attendances (absence_reason_id 1=н, 2=б),
    резолв к предмету через /jersey/api/schedule_items.
  • Уроки/нед — teachers[0].max_hours, fallback — учебный план.
  • КР — по КТП (/jersey/api/lesson_plans): is_test_planned=true
    и «Контрольная работа» в названии. Fallback — флаги отметки.
  • «Математика» для 7-11 не показывается (номинальный предмет).
  • Колонка «Кол-во отметок для аттестации»:
        1 ур/нед → 3
        2 ур/нед → 5
        ≥3 ур/нед → 7
  • Произвольный период: старт = 1 сентября текущего учебного года.
"""
import json
import os
from collections import defaultdict
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QProgressBar, QComboBox, QFileDialog, QCheckBox, QRadioButton,
    QButtonGroup, QDateEdit, QScrollArea, QApplication,
    QSpinBox, QDoubleSpinBox,
)
from PySide6.QtCore import QThread, Signal, Qt, QDate
from PySide6.QtGui import QColor
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from paths import SETTINGS_FILE


# ============================================================
# Утилиты
# ============================================================
def load_project_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_curriculum_from_file(path: str) -> dict:
    """Загружает УП из xlsx (fallback для уроков/нед)."""
    data = {}
    if not path or not os.path.exists(path):
        return data
    try:
        wb = load_workbook(path, data_only=True)
        for sheet in wb.worksheets:
            max_row = sheet.max_row
            max_col = sheet.max_column
            classes_in_sheet = []
            for col in range(2, max_col + 1):
                cell_value = sheet.cell(row=1, column=col).value
                if cell_value:
                    class_name = str(cell_value)
                    if len(class_name) > 1 and class_name[1].isalpha():
                        class_name = f"{class_name[0]}-{class_name[1:]}"
                    class_name = class_name.upper()
                    classes_in_sheet.append(class_name)
            for row in range(2, max_row + 1):
                subject = sheet.cell(row=row, column=1).value
                if not subject:
                    continue
                subject = str(subject).strip()
                for col_idx, class_name in enumerate(classes_in_sheet, start=2):
                    hours = sheet.cell(row=row, column=col_idx).value
                    if hours and isinstance(hours, (int, float)):
                        if class_name not in data:
                            data[class_name] = {}
                        data[class_name][subject] = int(hours)
        wb.close()
    except Exception as e:
        print(f"[УП] Ошибка загрузки: {e}")
    return data


def get_min_marks_required(lessons_per_week: int) -> int:
    """1→3, 2→5, ≥3→7."""
    if lessons_per_week <= 0:
        return 0
    if lessons_per_week == 1:
        return 3
    if lessons_per_week == 2:
        return 5
    return 7


def parse_date_str(date_str):
    if not date_str:
        return None
    try:
        d, m, y = date_str.split(".")
        return datetime(int(y), int(m), int(d))
    except Exception:
        return None


def _normalize_lesson_name(name: str) -> str:
    """Убирает \\n, лишние пробелы, приводит к одной строке."""
    if not name:
        return ""
    return " ".join(str(name).replace("\n", " ").split()).strip()


def is_control_work_by_mark(mark: dict) -> bool:
    """Fallback: КР по флагам самой отметки."""
    if not isinstance(mark, dict):
        return False
    if mark.get("is_exam"):
        return True
    if mark.get("is_control_once"):
        return True
    mt = mark.get("mark_type_id")
    if mt is not None and mt not in (1,):
        return True
    return False


def is_control_work_by_name(course_lesson_name: str,
                             ktp_control_names: set) -> bool:
    """
    КР по названию урока. Сначала точное совпадение с КТП,
    потом — эвристика по подстроке «контрольная работа».
    """
    if not course_lesson_name:
        return False
    norm = _normalize_lesson_name(course_lesson_name)
    if norm in ktp_control_names:
        return True
    if "контрольная работа" in norm.lower():
        return True
    return False


def mark_value_to_int(mark: dict):
    if not isinstance(mark, dict):
        return None
    val = mark.get("name")
    if val is None:
        values = mark.get("values") or []
        if values and isinstance(values[0], dict):
            grade = values[0].get("grade") or {}
            if isinstance(grade, dict):
                val = grade.get("origin") or grade.get("five")
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", ".")))
    except Exception:
        return None


def get_academic_year_start() -> int:
    """Возвращает год начала текущего учебного года."""
    today = datetime.now()
    if today.month >= 9:
        return today.year
    return today.year - 1


# ============================================================
# Поток: загрузка классов
# ============================================================
class OnlineClassesLoadThread(QThread):
    finished = Signal(list)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, auth):
        super().__init__()
        self.auth = auth

    def run(self):
        try:
            from collector import MarksDataCollector
            collector = MarksDataCollector(self.auth)
            self.log.emit("[Online] Загружаю список классов...")
            classes = collector.get_classes() or []
            classes = [c for c in classes if 5 <= c.get("level", 0) <= 11]
            self.log.emit(f"[Online] Получено классов: {len(classes)}")
            self.finished.emit(classes)
        except Exception as e:
            import traceback
            self.error.emit(f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")
            self.finished.emit([])


# ============================================================
# Поток: проверка выбранных классов
# ============================================================
class OnlineCheckJournalsThread(QThread):
    progress = Signal(int, int, str)
    row_ready = Signal(dict)
    finished = Signal(int)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, auth, selected_classes, period_start, period_end,
                 curriculum_data, academic_year_id):
        super().__init__()
        self.auth = auth
        self.selected_classes = selected_classes
        self.period_start = period_start
        self.period_end = period_end
        self.curriculum_data = curriculum_data
        self.academic_year_id = academic_year_id
        self._is_running = True

    def stop(self):
        self._is_running = False

    # ------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------
    def _fetch_marks(self, group_ids, start_str, end_str):
        ids_param = ",".join(str(g) for g in group_ids)
        all_marks = []
        page = 1
        per_page = 1000
        while True:
            params = {
                "created_at_from": start_str,
                "created_at_to": end_str,
                "group_ids": ids_param,
                "page": page,
                "per_page": per_page,
                "pid": self.auth.pid,
            }
            try:
                data = self.auth.fetch("core/api/marks", params=params) or []
            except Exception as e:
                self.log.emit(f"[Online] ❌ /core/api/marks: {e}")
                break
            if not data:
                break
            all_marks.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return all_marks

    def _fetch_attendances(self, group_ids, class_level_id,
                           start_str, end_str):
        """Пропуски через /core/api/attendances."""
        ids_param = ",".join(str(g) for g in group_ids)
        all_attendances = []
        page = 1
        per_page = 1000
        while True:
            params = {
                "academic_year_id": self.academic_year_id,
                "class_level_id": class_level_id,
                "group_ids": ids_param,
                "start_at": start_str,
                "stop_at": end_str,
                "page": page,
                "per_page": per_page,
                "pid": self.auth.pid,
            }
            try:
                data = self.auth.fetch("core/api/attendances",
                                       params=params) or []
            except Exception as e:
                self.log.emit(f"[Online] ❌ /core/api/attendances: {e}")
                break
            if not data:
                break
            all_attendances.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return all_attendances

    def _fetch_schedule_items(self, group_ids, start_str, end_str):
        """Маппинг schedule_lesson_id → group_id."""
        try:
            s_dt = datetime.strptime(start_str, "%d.%m.%Y")
            e_dt = datetime.strptime(end_str, "%d.%m.%Y")
            from_iso = s_dt.strftime("%Y-%m-%d")
            to_iso = e_dt.strftime("%Y-%m-%d")
        except Exception:
            from_iso = start_str
            to_iso = end_str

        ids_param = ",".join(str(g) for g in group_ids)
        all_items = []
        page = 1
        per_page = 1000
        while True:
            params = {
                "academic_year_id": self.academic_year_id,
                "group_ids": ids_param,
                "from": from_iso,
                "to": to_iso,
                "page": page,
                "per_page": per_page,
                "pid": self.auth.pid,
                "with_lesson_info": "true",
                "with_group_class_subject_info": "true",
            }
            try:
                data = self.auth.fetch(
                    "jersey/api/schedule_items", params=params
                ) or []
            except Exception as e:
                self.log.emit(f"[Online] ❌ /jersey/api/schedule_items: {e}")
                break
            if not data:
                break
            if isinstance(data, dict):
                data = data.get("items") or []
            all_items.extend(data)
            if len(data) < per_page:
                break
            page += 1

        mapping = {}
        for item in all_items:
            if not isinstance(item, dict):
                continue
            lid = item.get("id")
            gid = item.get("group_id")
            if lid is not None and gid is not None:
                mapping[lid] = gid
        return mapping

    def _fetch_lesson_plans(self, group_ids):
        """
        Загружает КТП и собирает set названий контрольных работ
        по каждой группе.
        Возвращает {group_id: {название_КР, ...}}.
        """
        ids_param = ",".join(str(g) for g in group_ids)
        all_plans = []
        page = 1
        per_page = 1000
        while True:
            params = {
                "group_ids": ids_param,
                "ignore_owner": "true",
                "per_page": per_page,
                "page": page,
                "pid": self.auth.pid,
                "status": "for_calendar_plan",
                "with_lessons": "true",
                "with_module_dates": "true",
                "with_modules": "true",
                "with_topics": "true",
            }
            try:
                data = self.auth.fetch(
                    "jersey/api/lesson_plans", params=params
                ) or []
            except Exception as e:
                self.log.emit(f"[Online] ❌ /jersey/api/lesson_plans: {e}")
                break
            if not data:
                break
            if isinstance(data, dict):
                data = data.get("items") or []
            all_plans.extend(data)
            if len(data) < per_page:
                break
            page += 1

        ktp_map = defaultdict(set)
        for plan in all_plans:
            if not isinstance(plan, dict):
                continue
            gid_raw = plan.get("group_id")
            gids = plan.get("group_ids")
            if gid_raw is not None:
                group_id_list = [gid_raw]
            elif isinstance(gids, list):
                group_id_list = gids
            else:
                group_id_list = []

            control_names = set()
            for module in (plan.get("modules") or []):
                for topic in (module.get("topics") or []):
                    for lesson in (topic.get("lessons") or []):
                        name = lesson.get("name") or ""
                        is_test = bool(lesson.get("is_test_planned"))
                        norm = _normalize_lesson_name(name)
                        if not norm:
                            continue
                        if is_test and "контрольная работа" in norm.lower():
                            control_names.add(norm)

            for gid in group_id_list:
                ktp_map[gid].update(control_names)

        return ktp_map

    # ------------------------------------------------------------
    # Основной цикл
    # ------------------------------------------------------------
    def run(self):
        try:
            from collector import MarksDataCollector
            collector = MarksDataCollector(self.auth)
            collector.auth.aid = str(self.academic_year_id)
            collector.auth.curr_aid = str(self.academic_year_id)

            total = len(self.selected_classes)
            rows = 0

            start_str = self.period_start.strftime("%d.%m.%Y")
            end_str = self.period_end.strftime("%d.%m.%Y")

            for idx, class_info in enumerate(self.selected_classes):
                if not self._is_running:
                    self.log.emit("[Online] ⏹ Остановка проверки.")
                    break

                class_name = class_info.get("name", "")
                class_id = class_info.get("id")
                class_level = class_info.get("level", 0)
                self.progress.emit(idx + 1, total, class_name)

                try:
                    groups = collector.get_groups_for_class(class_id) or []
                except Exception as e:
                    self.log.emit(f"[Online] ❌ {class_name}: группы — {e}")
                    continue

                valid_groups = []
                for g in groups:
                    if not g.get("id"):
                        continue
                    if g.get("is_metagroup"):
                        continue
                    if g.get("is_ndo"):
                        continue
                    valid_groups.append(g)

                if not valid_groups:
                    continue

                request_group_ids = set()
                subgroup_scope = {}
                for g in valid_groups:
                    gid = g["id"]
                    meta_ids = g.get("meta_group_ids") or []
                    scope = [gid] + [m for m in meta_ids if m]
                    request_group_ids.update(scope)
                    subgroup_scope[gid] = set(scope)

                request_group_ids = list(request_group_ids)

                marks = self._fetch_marks(request_group_ids,
                                          start_str, end_str)
                attendances = self._fetch_attendances(
                    request_group_ids, class_level, start_str, end_str
                )
                lesson_map = self._fetch_schedule_items(
                    request_group_ids, start_str, end_str
                )
                ktp_map = self._fetch_lesson_plans(request_group_ids)

                self.log.emit(
                    f"[Online] {class_name}: групп={len(valid_groups)}, "
                    f"отметок={len(marks)}, пропусков={len(attendances)}, "
                    f"расписание={len(lesson_map)}, КТП-групп={len(ktp_map)}"
                )

                for group in valid_groups:
                    if not self._is_running:
                        break
                    try:
                        rows += self._process_group(
                            collector, class_name, class_level,
                            class_id, group, marks, attendances,
                            lesson_map, ktp_map, subgroup_scope
                        )
                    except Exception as e:
                        self.log.emit(
                            f"[Online] ❌ {class_name} / "
                            f"{group.get('subject_name', '?')}: {e}"
                        )
                        continue

            self.finished.emit(rows)

        except Exception as e:
            import traceback
            self.error.emit(
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            )
            self.finished.emit(0)

    # ------------------------------------------------------------
    # Обработка одной группы
    # ------------------------------------------------------------
    def _process_group(self, collector, class_name, class_level,
                       class_id, group, marks_all, attendances_all,
                       lesson_map, ktp_map, subgroup_scope):
        group_id = group.get("id")
        subject_name = (
            group.get("subject_name")
            or group.get("name", "")
            or ""
        )
        if not group_id:
            return 0

        # --- Пропуск «Математика» для 7-11 ---
        # В ЭЖД «Математика» есть номинально (для отчётов).
        # Реальные отметки идут в «Алгебру», «Геометрию»,
        # «Вероятность и статистику».
        if class_level >= 7 and subject_name.strip().lower() == "математика":
            self.log.emit(
                f"[Online] ⏭ Пропуск «Математика» "
                f"({class_name}, {class_level} кл.)"
            )
            return 0

        # Учитель и часы в неделю
        teacher_name = collector.get_teacher_name(None, group_id) or "Не указан"
        lessons_per_week = 0
        teachers = group.get("teachers") or []
        if teachers:
            try:
                lessons_per_week = int(teachers[0].get("max_hours") or 0)
            except Exception:
                lessons_per_week = 0

        if lessons_per_week == 0:
            class_key = (class_name or "").upper()
            if class_key in self.curriculum_data:
                subj_lower = subject_name.lower()
                for curr_subj, hours in self.curriculum_data[class_key].items():
                    if (subj_lower == curr_subj.lower()
                            or subj_lower in curr_subj.lower()
                            or curr_subj.lower() in subj_lower):
                        lessons_per_week = hours
                        break
        min_marks = get_min_marks_required(lessons_per_week)

        # Ученики группы
        students = collector.get_students_for_group(group_id, class_id) or []
        if not students:
            return 0

        # Scope — id группы + её метагруппы
        scope = subgroup_scope.get(group_id, {group_id})

        # Set названий КР: объединяем по всему scope
        ktp_control_names = set()
        for gid in scope:
            ktp_control_names.update(ktp_map.get(gid, set()))

        # Отметки
        marks_group = []
        for m in marks_all:
            if not isinstance(m, dict):
                continue
            mg = m.get("group_id")
            if mg not in scope:
                continue
            dt = parse_date_str(m.get("date"))
            if not dt or not (self.period_start <= dt <= self.period_end):
                continue
            marks_group.append(m)

        marks_by_student = defaultdict(list)
        for m in marks_group:
            sid = m.get("student_profile_id")
            if sid is None:
                continue
            marks_by_student[sid].append(m)

        # Пропуски
        absences_by_student = defaultdict(list)
        for a in attendances_all:
            if not isinstance(a, dict):
                continue
            sid = a.get("student_profile_id")
            if sid is None:
                continue
            lid = a.get("schedule_lesson_id")
            gid = lesson_map.get(lid)
            if gid is None or gid not in scope:
                continue
            dt = parse_date_str(a.get("date"))
            if not dt or not (self.period_start <= dt <= self.period_end):
                continue
            absences_by_student[sid].append(a)

        rows_emitted = 0
        for student in students:
            if not self._is_running:
                break
            sid = student.get("id")
            if sid is None:
                continue
            fio = self._student_fio(student)

            marks_count = 0
            weight_sum = 0
            score_sum = 0
            kr_count = 0
            kr_marks_count = 0

            for m in marks_by_student.get(sid, []):
                mv = mark_value_to_int(m)
                if mv is None:
                    continue
                try:
                    w = int(m.get("weight") or 1)
                except Exception:
                    w = 1
                marks_count += 1
                weight_sum += w
                score_sum += mv * w

                course_lesson_name = m.get("course_lesson_name") or ""
                is_kr = is_control_work_by_name(
                    course_lesson_name, ktp_control_names
                )
                if not is_kr:
                    is_kr = is_control_work_by_mark(m)

                if is_kr:
                    kr_count += 1
                    kr_marks_count += w

            avg_mark = round(score_sum / weight_sum, 2) if weight_sum else 0.0

            abs_n = 0
            abs_b = 0
            for a in absences_by_student.get(sid, []):
                rid = a.get("absence_reason_id")
                if rid == 2:
                    abs_b += 1
                else:
                    abs_n += 1

            row = {
                "class": class_name,
                "subject": subject_name,
                "student": fio,
                "teacher": teacher_name,
                "marks_count": marks_count,
                "min_marks_required": min_marks,
                "avg_mark": avg_mark,
                "kr_count": kr_count,
                "kr_marks_count": kr_marks_count,
                "abs_n": abs_n,
                "abs_b": abs_b,
                "lessons_per_week": lessons_per_week,
            }
            self.row_ready.emit(row)
            rows_emitted += 1

        return rows_emitted

    @staticmethod
    def _student_fio(student):
        last = student.get("last_name", "")
        first = student.get("first_name", "")
        middle = student.get("middle_name", "")
        if not last and student.get("user_name"):
            parts = student.get("user_name", "").split()
            if len(parts) >= 1:
                last = parts[0]
            if len(parts) >= 2:
                first = parts[1]
            if len(parts) >= 3:
                middle = parts[2]
        parts = [p for p in (last, first, middle) if p]
        return " ".join(parts) if parts else student.get("short_name", "")


# ============================================================
# Вкладка
# ============================================================
class CheckJournalsOnlineTab(QWidget):
    """Вкладка «🔍 Проверка журналов Online»."""

    log_signal = Signal(str)

    def __init__(self, parent):
        super().__init__()
        self.main_window = parent
        self.auth = None
        self.academic_year_id = 14
        self.all_classes = []
        self.class_checkboxes = []
        self.parallel_checkboxes = {}
        self.all_results = []
        self.filtered_results = []
        self.curriculum_data = {}
        self._is_loading = False
        self.check_thread = None
        self.classes_thread = None
        self.last_export_path = None
        self.initUI()
        self.log_signal.connect(self.append_to_status)

    # ================================================================
    # UI
    # ================================================================
    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 14, 16, 14)

        title = QLabel("🔍  Проверка журналов Online")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: 700; color: #0f172a; padding: 2px 0 4px 0;"
        )
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Онлайн-проверка накопляемости, средних баллов, КР и пропусков. "
            "Данные загружаются напрямую из ЭЖД МЭШ."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #64748b; margin-bottom: 4px;")
        main_layout.addWidget(subtitle)

        # === Период ===
        period_group = QGroupBox("📅  Период проверки")
        period_layout = QVBoxLayout(period_group)

        rb_row = QHBoxLayout()
        rb_row.setSpacing(14)
        self.rb_group = QButtonGroup(self)
        for i, (code, label) in enumerate([
            ("Т1", "Триместр 1"), ("Т2", "Триместр 2"), ("Т3", "Триместр 3"),
            ("П1", "Полугодие 1"), ("П2", "Полугодие 2"), ("Год", "Год"),
            ("custom", "Произвольный"),
        ]):
            rb = QRadioButton(f"{code}  ({label})")
            rb.setProperty("period_code", code)
            self.rb_group.addButton(rb, i)
            rb_row.addWidget(rb)
            if code == "Т2":
                rb.setChecked(True)
        rb_row.addStretch()
        period_layout.addLayout(rb_row)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        custom_row.addWidget(QLabel("с:"))

        # Дефолт «Произвольного»: 1 сентября текущего учебного года
        start_year = get_academic_year_start()

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("dd.MM.yyyy")
        self.start_date_edit.setDate(QDate(start_year, 9, 1))
        self.start_date_edit.setEnabled(False)
        custom_row.addWidget(self.start_date_edit)

        custom_row.addWidget(QLabel("по:"))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("dd.MM.yyyy")
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setEnabled(False)
        custom_row.addWidget(self.end_date_edit)
        custom_row.addStretch()
        period_layout.addLayout(custom_row)

        self.rb_group.buttonToggled.connect(self._on_period_changed)
        main_layout.addWidget(period_group)

        # === Параллели и классы ===
        classes_group = QGroupBox("🎓  Параллели и классы (5-11)")
        classes_layout = QVBoxLayout(classes_group)

        top_row = QHBoxLayout()
        self.load_classes_btn = QPushButton("📋  Загрузить классы")
        self.load_classes_btn.setMinimumHeight(36)
        self.load_classes_btn.setMaximumWidth(240)
        self.load_classes_btn.setEnabled(False)
        self.load_classes_btn.setStyleSheet("""
            QPushButton {
                background: #eff6ff; color: #1d4ed8;
                border: 1px solid #bfdbfe; font-weight: 600;
            }
            QPushButton:hover { background: #dbeafe; }
            QPushButton:disabled { background: #f1f5f9; color: #94a3b8; border-color: #e2e8f0; }
        """)
        self.load_classes_btn.clicked.connect(self.load_classes)
        top_row.addWidget(self.load_classes_btn)

        self.select_all_btn = QPushButton("✓  Выбрать всё")
        self.select_all_btn.setEnabled(False)
        self.select_all_btn.clicked.connect(self.select_all_classes)
        top_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("✗  Снять всё")
        self.deselect_all_btn.setEnabled(False)
        self.deselect_all_btn.clicked.connect(self.deselect_all_classes)
        top_row.addWidget(self.deselect_all_btn)

        top_row.addStretch()
        self.selected_count_label = QLabel("Выбрано классов: 0")
        self.selected_count_label.setStyleSheet("""
            color: #1d4ed8; background: #eff6ff;
            border: 1px solid #bfdbfe; border-radius: 6px;
            padding: 5px 10px; font-weight: 700;
        """)
        top_row.addWidget(self.selected_count_label)
        classes_layout.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(160)
        scroll.setMaximumHeight(260)
        self.classes_widget = QWidget()
        self.classes_layout = QVBoxLayout(self.classes_widget)
        self.classes_layout.setSpacing(6)
        self.classes_layout.setContentsMargins(8, 8, 8, 8)
        self.classes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.classes_widget)
        classes_layout.addWidget(scroll)
        main_layout.addWidget(classes_group)

        # === Управление ===
        control_group = QGroupBox("⚙️  Управление")
        control_layout = QHBoxLayout(control_group)
        control_layout.setSpacing(10)

        self.check_btn = QPushButton("🔍  Проверить выбранные классы")
        self.check_btn.setMinimumHeight(42)
        self.check_btn.setEnabled(False)
        self.check_btn.setStyleSheet("""
            QPushButton {
                background-color: #1d4ed8; color: #ffffff;
                font-weight: 700; border: none; border-radius: 7px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #1e40af; }
            QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }
        """)
        self.check_btn.clicked.connect(self.check_selected)
        control_layout.addWidget(self.check_btn)

        self.stop_btn = QPushButton("⏹  Остановить")
        self.stop_btn.setMinimumHeight(42)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMaximumWidth(140)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #fff1f2; color: #be123c;
                border: 1px solid #fecdd3; font-weight: 600;
            }
            QPushButton:hover { background-color: #ffe4e6; }
            QPushButton:disabled { background: #f1f5f9; color: #94a3b8; border-color: #e2e8f0; }
        """)
        self.stop_btn.clicked.connect(self.stop_check)
        control_layout.addWidget(self.stop_btn)

        control_layout.addStretch()

        self.export_btn = QPushButton("📊  Экспорт в Excel")
        self.export_btn.setMinimumHeight(36)
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: #ffffff;
                font-weight: 600; border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }
        """)
        self.export_btn.clicked.connect(self.export_to_excel)
        control_layout.addWidget(self.export_btn)

        main_layout.addWidget(control_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # === Фильтры ===
        filter_group = QGroupBox("🔎  Фильтры")
        filter_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt; font-weight: 700;
                color: #0369a1; border: 1px solid #7dd3fc;
                border-radius: 10px; margin-top: 12px;
                padding: 18px 14px 14px 14px; background: #ffffff;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
        """)
        filter_layout = QGridLayout(filter_group)
        filter_layout.setVerticalSpacing(8)
        filter_layout.setHorizontalSpacing(10)

        filter_layout.addWidget(QLabel("Класс:"), 0, 0)
        self.filter_class = QLineEdit()
        self.filter_class.setPlaceholderText("напр. 5А")
        self.filter_class.setFixedWidth(100)
        self.filter_class.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_class, 0, 1)

        filter_layout.addWidget(QLabel("Предмет:"), 0, 2)
        self.filter_subject = QLineEdit()
        self.filter_subject.setPlaceholderText("напр. Математика")
        self.filter_subject.setFixedWidth(160)
        self.filter_subject.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_subject, 0, 3)

        filter_layout.addWidget(QLabel("Ученик:"), 0, 4)
        self.filter_student = QLineEdit()
        self.filter_student.setPlaceholderText("ФИО")
        self.filter_student.setFixedWidth(180)
        self.filter_student.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_student, 0, 5)

        filter_layout.addWidget(QLabel("Учитель:"), 0, 6)
        self.filter_teacher = QLineEdit()
        self.filter_teacher.setPlaceholderText("ФИО")
        self.filter_teacher.setFixedWidth(180)
        self.filter_teacher.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_teacher, 0, 7)

        self.problems_only_cb = QCheckBox("Только проблемные")
        self.problems_only_cb.setStyleSheet("font-weight: 700; color: #b91c1c;")
        self.problems_only_cb.stateChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.problems_only_cb, 1, 0, 1, 2)

        filter_layout.addWidget(QLabel("Накопляемость <"), 1, 2)
        self.filter_accumulation_spin = QSpinBox()
        self.filter_accumulation_spin.setRange(0, 100)
        self.filter_accumulation_spin.setSuffix(" %")
        self.filter_accumulation_spin.setFixedWidth(90)
        self.filter_accumulation_spin.valueChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_accumulation_spin, 1, 3)

        filter_layout.addWidget(QLabel("Средний балл <"), 1, 4)
        self.filter_avg_spin = QDoubleSpinBox()
        self.filter_avg_spin.setRange(2.0, 5.0)
        self.filter_avg_spin.setSingleStep(0.1)
        self.filter_avg_spin.setFixedWidth(90)
        self.filter_avg_spin.valueChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_avg_spin, 1, 5)

        self.clear_filters_btn = QPushButton("Очистить фильтры")
        self.clear_filters_btn.setStyleSheet("""
            QPushButton {
                background: #fff1f2; color: #be123c;
                border: 1px solid #fecdd3; font-weight: 600;
            }
            QPushButton:hover { background: #ffe4e6; }
        """)
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        filter_layout.addWidget(self.clear_filters_btn, 1, 7)

        main_layout.addWidget(filter_group)

        # === Таблица ===
        self.results_table = QTableWidget()
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setColumnCount(11)
        self.results_table.setHorizontalHeaderLabels([
            "Класс", "Предмет", "Ученик", "Учитель",
            "Кол-во отметок", "Кол-во отметок для аттестации",
            "Средний балл", "Кол-во КР", "Отметок за КР",
            "Пропуски (н)", "Пропуски (б)",
        ])
        self.results_table.verticalHeader().setDefaultSectionSize(28)
        main_layout.addWidget(self.results_table, 1)

        self.status_label = QLabel("Готов к работе")
        self.status_label.setStyleSheet("""
            color: #1e40af; background: #eff6ff;
            border-radius: 6px; padding: 7px 10px;
            font-weight: 600;
        """)
        main_layout.addWidget(self.status_label)

        self._load_settings()

    def _on_period_changed(self, btn, checked):
        if not checked:
            return
        code = btn.property("period_code")
        is_custom = (code == "custom")
        self.start_date_edit.setEnabled(is_custom)
        self.end_date_edit.setEnabled(is_custom)

        # При выборе «Произвольного» — старт = 1 сентября текущего УГ,
        # если пользователь ещё не выставил свою дату
        if is_custom:
            start_year = get_academic_year_start()
            current = self.start_date_edit.date()
            if current.month() != 9 or current.day() != 1:
                self.start_date_edit.setDate(QDate(start_year, 9, 1))

    def _load_settings(self):
        settings = load_project_settings()
        try:
            acc = int(settings.get("threshold_accumulation", 70))
            self.filter_accumulation_spin.setValue(acc)
        except Exception:
            pass
        try:
            avg = float(settings.get("threshold_avg_mark", 3.5))
            self.filter_avg_spin.setValue(avg)
        except Exception:
            pass
        cur_path = settings.get("curriculum_file", "")
        if cur_path:
            self.curriculum_data = load_curriculum_from_file(cur_path)
            print(f"[Online] УП загружен: {len(self.curriculum_data)} классов")

    def reload_settings(self):
        self._load_settings()
        self.append_to_status("Настройки перезагружены")

    # ================================================================
    # Авторизация / год
    # ================================================================
    def on_auth_updated(self, auth):
        self.auth = auth
        self.load_classes_btn.setEnabled(bool(auth))
        if auth:
            self.append_to_status("✅ Авторизация получена")
            self._load_settings()

    def on_academic_year_updated(self, aid):
        self.academic_year_id = aid
        if self.auth:
            self.auth.aid = str(aid)
            self.auth.curr_aid = str(aid)
        self.append_to_status(f"📅 Учебный год: {aid}")

    # ================================================================
    # Загрузка классов
    # ================================================================
    def load_classes(self):
        if not self.auth:
            QMessageBox.warning(self, "Ошибка", "Нет авторизации.")
            return
        self.load_classes_btn.setEnabled(False)
        self.load_classes_btn.setText("⏳ Загрузка...")
        self.classes_thread = OnlineClassesLoadThread(self.auth)
        self.classes_thread.log.connect(self.append_to_status)
        self.classes_thread.finished.connect(self.on_classes_loaded)
        self.classes_thread.error.connect(
            lambda e: QMessageBox.critical(self, "Ошибка", e)
        )
        self.classes_thread.start()

    def on_classes_loaded(self, classes):
        self.load_classes_btn.setEnabled(True)
        self.load_classes_btn.setText("📋  Загрузить классы")
        if not classes:
            QMessageBox.warning(self, "Ошибка", "Список классов пуст.")
            return
        self.all_classes = classes
        self._rebuild_classes_ui()
        self.select_all_btn.setEnabled(True)
        self.deselect_all_btn.setEnabled(True)
        self._update_check_button()
        self.append_to_status(f"✅ Загружено классов: {len(classes)}")

    def _rebuild_classes_ui(self):
        self.class_checkboxes = []
        self.parallel_checkboxes = {}
        while self.classes_layout.count() > 0:
            item = self.classes_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        by_level = defaultdict(list)
        for c in self.all_classes:
            by_level[c.get("level", 0)].append(c)

        for level in sorted(by_level.keys()):
            header = QWidget()
            hl = QHBoxLayout(header)
            hl.setContentsMargins(0, 4, 0, 4)
            hl.setSpacing(10)

            par_cb = QCheckBox(f"📌 {level} классы")
            par_cb.setStyleSheet(
                "font-weight: 700; color: #1d4ed8; font-size: 11pt;"
            )
            par_cb.setProperty("level", level)
            par_cb.stateChanged.connect(
                lambda state, lvl=level: self._on_parallel_toggled(lvl, state)
            )
            self.parallel_checkboxes[level] = par_cb
            hl.addWidget(par_cb)

            for c in sorted(by_level[level], key=lambda x: x.get("name", "")):
                cb = QCheckBox(c.get("name", "?"))
                cb.setProperty("class_data", c)
                cb.setProperty("level", level)
                cb.stateChanged.connect(self._update_check_button)
                self.class_checkboxes.append(cb)
                hl.addWidget(cb)

            hl.addStretch()
            self.classes_layout.addWidget(header)

    def _on_parallel_toggled(self, level, state):
        checked = (state == Qt.CheckState.Checked.value)
        for cb in self.class_checkboxes:
            if cb.property("level") == level:
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        self._update_check_button()

    def select_all_classes(self):
        for cb in self.class_checkboxes:
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        for cb in self.parallel_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._update_check_button()

    def deselect_all_classes(self):
        for cb in self.class_checkboxes:
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        for cb in self.parallel_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._update_check_button()

    def _get_selected_classes(self):
        return [
            cb.property("class_data")
            for cb in self.class_checkboxes
            if cb.isChecked()
        ]

    def _update_check_button(self):
        selected = self._get_selected_classes()
        self.selected_count_label.setText(f"Выбрано классов: {len(selected)}")
        self.check_btn.setEnabled(
            bool(selected) and not self._is_loading and self.auth is not None
        )

    # ================================================================
    # Проверка
    # ================================================================
    def _get_period_dates(self):
        checked_btn = self.rb_group.checkedButton()
        code = checked_btn.property("period_code") if checked_btn else "Т2"

        if code == "custom":
            s = self.start_date_edit.date()
            e = self.end_date_edit.date()
            start_dt = datetime(s.year(), s.month(), s.day())
            end_dt = datetime(e.year(), e.month(), e.day())
            if start_dt > end_dt:
                return None, None, ""
            return start_dt, end_dt, f"{s.toString('dd.MM.yyyy')}–{e.toString('dd.MM.yyyy')}"

        now = datetime.now()
        if now.month >= 9:
            y1, y2 = now.year, now.year + 1
        else:
            y1, y2 = now.year - 1, now.year

        if code == "Т1":
            return datetime(y1, 9, 1), datetime(y1, 11, 30), "Триместр 1"
        if code == "Т2":
            return datetime(y1, 12, 1), datetime(y2, 2, 28), "Триместр 2"
        if code == "Т3":
            return datetime(y2, 3, 1), datetime(y2, 5, 31), "Триместр 3"
        if code == "П1":
            return datetime(y1, 9, 1), datetime(y1, 12, 31), "Полугодие 1"
        if code == "П2":
            return datetime(y2, 1, 1), datetime(y2, 5, 31), "Полугодие 2"
        if code == "Год":
            return datetime(y1, 9, 1), datetime(y2, 5, 31), "Учебный год"
        return None, None, ""

    def check_selected(self):
        if self._is_loading:
            return
        selected = self._get_selected_classes()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один класс.")
            return
        start_dt, end_dt, period_name = self._get_period_dates()
        if not start_dt or not end_dt:
            QMessageBox.warning(self, "Ошибка", "Некорректный период.")
            return

        settings = load_project_settings()
        cur_path = settings.get("curriculum_file", "")
        if cur_path:
            self.curriculum_data = load_curriculum_from_file(cur_path)

        self._is_loading = True
        self.check_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.results_table.setRowCount(0)
        self.all_results = []
        self.filtered_results = []

        self.append_to_status(f"🚀 Запуск проверки: {len(selected)} классов")
        self.append_to_status(f"📅 Период: {period_name}")

        self.check_thread = OnlineCheckJournalsThread(
            self.auth, selected, start_dt, end_dt,
            self.curriculum_data, self.academic_year_id,
        )
        self.check_thread.progress.connect(self._on_progress)
        self.check_thread.row_ready.connect(self._on_row_ready)
        self.check_thread.finished.connect(self._on_check_finished)
        self.check_thread.error.connect(
            lambda e: QMessageBox.critical(self, "Ошибка", e)
        )
        self.check_thread.log.connect(self.append_to_status)
        self.check_thread.start()

    def _on_progress(self, current, total, name):
        if total > 0:
            pct = int(current / total * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(
                f"Проверка {current}/{total}: {name} ({pct}%)"
            )

    def _on_row_ready(self, row):
        self.all_results.append(row)

    def _on_check_finished(self, count):
        self._is_loading = False
        self.check_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self._update_check_button()

        if self.all_results:
            self.export_btn.setEnabled(True)
        self.apply_filter()
        self.append_to_status(f"✅ Проверка завершена. Строк: {count}")

    def stop_check(self):
        if self.check_thread and self.check_thread.isRunning():
            self.check_thread.stop()
            self.append_to_status("⏹ Остановка проверки...")

    # ================================================================
    # Фильтры
    # ================================================================
    def apply_filter(self):
        if not self.all_results:
            self._update_table([])
            return

        cls_f = self.filter_class.text().lower().strip()
        subj_f = self.filter_subject.text().lower().strip()
        stud_f = self.filter_student.text().lower().strip()
        teach_f = self.filter_teacher.text().lower().strip()
        only_problems = self.problems_only_cb.isChecked()
        acc_thr = self.filter_accumulation_spin.value()
        avg_thr = self.filter_avg_spin.value()

        result = []
        for r in self.all_results:
            if cls_f and cls_f not in str(r.get("class", "")).lower():
                continue
            if subj_f and subj_f not in str(r.get("subject", "")).lower():
                continue
            if stud_f and stud_f not in str(r.get("student", "")).lower():
                continue
            if teach_f and teach_f not in str(r.get("teacher", "")).lower():
                continue
            if only_problems:
                if not self._is_problem(r, acc_thr, avg_thr):
                    continue
            result.append(r)

        self.filtered_results = result
        self._update_table(result)
        self.append_to_status(
            f"Показано: {len(result)} из {len(self.all_results)}"
        )

    @staticmethod
    def _is_problem(row, acc_thr, avg_thr):
        min_req = row.get("min_marks_required", 0)
        marks_count = row.get("marks_count", 0)
        avg = row.get("avg_mark", 0.0)

        if min_req > 0 and marks_count < min_req:
            return True
        if min_req > 0:
            percentage = marks_count / min_req * 100
            if percentage < acc_thr:
                return True
        if avg and avg < avg_thr:
            return True
        if marks_count == 0:
            return True
        return False

    def clear_filters(self):
        self.filter_class.clear()
        self.filter_subject.clear()
        self.filter_student.clear()
        self.filter_teacher.clear()
        self.problems_only_cb.setChecked(False)
        self.apply_filter()

    # ================================================================
    # Таблица
    # ================================================================
    def _update_table(self, rows):
        self.results_table.setSortingEnabled(False)
        self.results_table.setUpdatesEnabled(False)
        self.results_table.setRowCount(len(rows))

        red_bg = QColor(254, 202, 202)
        yellow_bg = QColor(254, 240, 138)
        green_bg = QColor(209, 250, 229)

        for i, r in enumerate(rows):
            marks_count = r.get("marks_count", 0)
            min_marks = r.get("min_marks_required", 0)
            avg = r.get("avg_mark", 0.0)

            values = [
                r.get("class", ""),
                r.get("subject", ""),
                r.get("student", ""),
                r.get("teacher", ""),
                str(marks_count),
                str(min_marks) if min_marks > 0 else "—",
                f"{avg:.2f}" if avg else "0.00",
                str(r.get("kr_count", 0)),
                str(r.get("kr_marks_count", 0)),
                str(r.get("abs_n", 0)),
                str(r.get("abs_b", 0)),
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                if j >= 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.results_table.setItem(i, j, item)

            if min_marks > 0:
                cell = self.results_table.item(i, 4)
                if marks_count < min_marks:
                    cell.setBackground(red_bg)
                elif marks_count < int(min_marks * 1.3):
                    cell.setBackground(yellow_bg)
                else:
                    cell.setBackground(green_bg)

            avg_cell = self.results_table.item(i, 6)
            if avg and avg < 2.6:
                avg_cell.setBackground(red_bg)
            elif avg and avg < 3.5:
                avg_cell.setBackground(yellow_bg)
            elif avg and avg >= 4.5:
                avg_cell.setBackground(green_bg)

        self.results_table.setUpdatesEnabled(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.setColumnWidth(0, 70)
        self.results_table.setColumnWidth(1, 200)
        self.results_table.setColumnWidth(2, 220)
        self.results_table.setColumnWidth(3, 200)
        self.results_table.setColumnWidth(4, 110)
        self.results_table.setColumnWidth(5, 150)
        self.results_table.setColumnWidth(6, 110)
        self.results_table.setColumnWidth(7, 90)
        self.results_table.setColumnWidth(8, 110)
        self.results_table.setColumnWidth(9, 110)
        self.results_table.setColumnWidth(10, 110)

    # ================================================================
    # Экспорт
    # ================================================================
    def export_to_excel(self):
        rows = self.filtered_results or self.all_results
        if not rows:
            QMessageBox.warning(self, "Ошибка", "Нет данных для экспорта.")
            return
        _, _, period_name = self._get_period_dates()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"Проверка_журналов_online_{period_name}_{timestamp}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", default_name, "Excel files (*.xlsx)"
        )
        if not file_path:
            return
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Проверка журналов Online"
            headers = [
                "Класс", "Предмет", "Ученик", "Учитель",
                "Кол-во отметок", "Кол-во отметок для аттестации",
                "Средний балл", "Кол-во КР", "Отметок за КР",
                "Пропуски (н)", "Пропуски (б)",
                "Уроков в неделю",
            ]
            ws.append(headers)

            header_font = Font(bold=True, color="FFFFFF", size=11)
            header_fill = PatternFill(
                start_color="1D4ED8", end_color="1D4ED8", fill_type="solid"
            )
            header_align = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            for c in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=c)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

            red_fill = PatternFill(
                start_color="FECACA", end_color="FECACA", fill_type="solid"
            )
            yellow_fill = PatternFill(
                start_color="FEF08A", end_color="FEF08A", fill_type="solid"
            )

            for r in rows:
                ws.append([
                    r.get("class", ""),
                    r.get("subject", ""),
                    r.get("student", ""),
                    r.get("teacher", ""),
                    r.get("marks_count", 0),
                    r.get("min_marks_required", 0) or "",
                    round(r.get("avg_mark", 0), 2),
                    r.get("kr_count", 0),
                    r.get("kr_marks_count", 0),
                    r.get("abs_n", 0),
                    r.get("abs_b", 0),
                    r.get("lessons_per_week", 0),
                ])
                row_idx = ws.max_row
                min_req = r.get("min_marks_required", 0)
                marks = r.get("marks_count", 0)
                if min_req > 0 and marks < min_req:
                    ws.cell(row=row_idx, column=5).fill = red_fill
                elif min_req > 0 and marks < int(min_req * 1.3):
                    ws.cell(row=row_idx, column=5).fill = yellow_fill
                avg = r.get("avg_mark", 0)
                if avg and avg < 3.5:
                    ws.cell(row=row_idx, column=7).fill = yellow_fill
                if avg and avg < 2.6:
                    ws.cell(row=row_idx, column=7).fill = red_fill

            widths = {
                "A": 8, "B": 28, "C": 32, "D": 28,
                "E": 14, "F": 18, "G": 13, "H": 10,
                "I": 14, "J": 13, "K": 13, "L": 14,
            }
            for letter, w in widths.items():
                ws.column_dimensions[letter].width = w
            ws.auto_filter.ref = ws.dimensions
            ws.freeze_panes = "A2"

            wb.save(file_path)
            self.last_export_path = file_path
            self.append_to_status(f"💾 Отчёт сохранён: {file_path}")
            reply = QMessageBox.question(
                self, "Готово",
                f"Отчёт сохранён:\n{file_path}\n\nОткрыть файл?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                os.startfile(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")

    # ================================================================
    # Статус
    # ================================================================
    def append_to_status(self, text):
        if hasattr(self, "status_label") and self.status_label:
            self.status_label.setText(str(text)[:200])
            QApplication.processEvents()