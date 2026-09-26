# -*- coding: utf-8 -*-
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication
import os
import traceback
from collections import defaultdict

from auth import dn_Auth
from collector import MarksDataCollector
from excel_creator import create_class_marks_excel_file
from journal_checker import JournalChecker


class ConnectionThread(QThread):
    """Поток для проверки подключения через браузер (fallback)."""
    finished = Signal(bool, object)
    log = Signal(str)

    def __init__(self, browser='auto'):
        super().__init__()
        self.auth = None
        self.browser = browser
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            if not self._is_running:
                self.finished.emit(False, None)
                return

            self.auth = dn_Auth("work", timeout=30)

            if self.auth.load_session():
                self.finished.emit(True, self.auth)
                return

            success = self.auth.login_from_browser(self.browser)
            self.finished.emit(success, self.auth if success else None)

        except Exception:
            self.finished.emit(False, None)


class ClassesThread(QThread):
    """Поток для получения списка классов"""
    finished = Signal(list)
    log = Signal(str)

    def __init__(self, auth):
        super().__init__()
        self.auth = auth
        self.collector = MarksDataCollector(auth)

    def run(self):
        try:
            if not self.auth or not self.auth.session:
                self.finished.emit([])
                return
            classes = self.collector.get_classes()
            self.finished.emit(classes)
        except Exception:
            self.finished.emit([])


class DownloadThread(QThread):
    """Поток для скачивания журналов"""
    progress_update = Signal(int)
    log_message = Signal(str)
    finished = Signal(tuple)

    def __init__(self, auth, selected_by_level, base_output_folder):
        super().__init__()
        self.auth = auth
        self.selected_by_level = selected_by_level
        self.base_output_folder = base_output_folder
        self.collector = None
        self._is_running = True

    def stop(self):
        self._is_running = False
        self.log_message.emit("⚠️ Остановка скачивания...")

    def run(self):
        try:
            from collector import MarksDataCollector
            self.collector = MarksDataCollector(self.auth)

            total_classes = sum(len(classes) for classes in self.selected_by_level.values())
            total_subjects = 0
            processed = 0

            self.log_message.emit(f"\n🚀 Начинаем скачивание {total_classes} классов...")

            for level in sorted(self.selected_by_level.keys()):
                if not self._is_running:
                    break

                level_folder = os.path.join(self.base_output_folder, str(level))
                os.makedirs(level_folder, exist_ok=True)

                classes = self.selected_by_level[level]

                for class_info in classes:
                    if not self._is_running:
                        break

                    class_name = class_info["name"]
                    class_id = class_info["id"]

                    self.log_message.emit(f"\n📁 Обработка класса {class_name}...")

                    try:
                        groups = self.collector.get_groups_for_class(class_id)
                        if not groups:
                            self.log_message.emit(f"   ⚠️ Не удалось получить группы для класса {class_name}")
                            processed += 1
                            self.progress_update.emit(processed)
                            continue

                        self.log_message.emit(f"   Найдено групп: {len(groups)}")

                        class_groups_data = []

                        for group in groups:
                            if not self._is_running:
                                break

                            try:
                                group_id = group.get("id")
                                subject_name = group.get("subject_name", "")

                                if not group_id:
                                    continue

                                self.log_message.emit(f"   📚 Предмет: {subject_name}")

                                students = self.collector.get_students_for_group(group_id, class_id)
                                if not students:
                                    self.log_message.emit(f"      Нет учеников")
                                    continue
                                self.log_message.emit(f"      Учеников: {len(students)}")

                                marks = self.collector.get_marks_for_group(group_id)
                                if not marks:
                                    self.log_message.emit(f"      Нет отметок")
                                    marks = []

                                self.log_message.emit(f"      Отметок: {len(marks)}")

                                teacher_id = marks[0].get("teacher_id") if marks else None
                                teacher_name = self.collector.get_teacher_name(teacher_id, group_id)

                                group_data = {
                                    "group": group,
                                    "subject_name": subject_name,
                                    "students": students,
                                    "marks": marks,
                                    "teacher_id": teacher_id,
                                    "teacher_name": teacher_name
                                }
                                class_groups_data.append(group_data)
                                total_subjects += 1
                            except Exception as e:
                                self.log_message.emit(f"      ❌ Ошибка обработки группы: {str(e)}")
                                continue

                        if class_groups_data:
                            self.log_message.emit(f"   💾 Создание Excel-файла...")
                            try:
                                from excel_creator import create_class_marks_excel_file
                                create_class_marks_excel_file(
                                    class_name, class_groups_data, self.collector, level_folder,
                                    signal_callback=self.log_message.emit
                                )
                                self.log_message.emit(f"   ✅ Файл создан")
                            except Exception as e:
                                self.log_message.emit(f"   ❌ Ошибка создания файла: {str(e)}")
                                import traceback
                                traceback.print_exc()
                        else:
                            self.log_message.emit(f"   ⚠️ Нет данных для создания файла")

                    except Exception as e:
                        self.log_message.emit(f"   ❌ Ошибка обработки класса {class_name}: {str(e)}")

                    processed += 1
                    self.progress_update.emit(processed)

                    if processed % max(1, total_classes // 10) == 0 or processed == total_classes:
                        percent = int(processed / total_classes * 100) if total_classes > 0 else 0
                        self.log_message.emit(f"⏳ Прогресс: {processed}/{total_classes} ({percent}%)")

                    QApplication.processEvents()

            if not self._is_running:
                self.log_message.emit(f"\n⚠️ Скачивание прервано пользователем")
                self.finished.emit((0, 0))
            else:
                self.log_message.emit(
                    f"\n✅ Скачивание завершено! Обработано классов: {total_classes}, предметов: {total_subjects}")
                self.finished.emit((total_classes, total_subjects))

        except Exception as e:
            self.log_message.emit(f"❌ Ошибка: {str(e)}")
            import traceback
            traceback.print_exc()
            self.finished.emit((0, 0))


class CheckJournalsThread(QThread):
    """Поток для проверки журналов"""
    log_message = Signal(str)
    finished = Signal(tuple)

    def __init__(self, selected_journals, output_folder, curriculum_file, check_mode, start_date=None, end_date=None):
        super().__init__()
        self.selected_journals = selected_journals
        self.output_folder = output_folder
        self.curriculum_file = curriculum_file
        self.check_mode = check_mode
        self.start_date = start_date
        self.end_date = end_date
        self.checker = None

    def run(self):
        try:
            self.checker = JournalChecker()

            if not os.path.exists(self.curriculum_file):
                self.log_message.emit(f"❌ Файл учебного плана не найден: {self.curriculum_file}")
                self.finished.emit((0, 0))
                return

            self.log_message.emit("\n📚 Загрузка учебного плана...")
            curriculum_data = self.checker.load_curriculum_data(self.curriculum_file)

            if not curriculum_data:
                self.log_message.emit("❌ Ошибка загрузки учебного плана! Файл пуст или имеет неверный формат.")
                self.finished.emit((0, 0))
                return

            self.log_message.emit(f"✅ Учебный план загружен: {len(curriculum_data)} классов")

            sample_classes = list(curriculum_data.keys())[:5]
            self.log_message.emit(f"   Примеры классов в УП: {', '.join(sample_classes)}")

            journals_by_level = {}
            for journal in self.selected_journals:
                level = journal['level']
                if level not in journals_by_level:
                    journals_by_level[level] = []
                journals_by_level[level].append(journal)

            all_results = []
            all_stats = []
            total_files = len(self.selected_journals)
            error_files = 0

            for level, journals in journals_by_level.items():
                self.log_message.emit(f"\n📁 Проверка параллели {level}...")
                level_results = []
                level_stats = []

                for journal in journals:
                    file_path = journal['path']

                    if not os.path.exists(file_path):
                        self.log_message.emit(f"\n  ⚠️ Файл не найден: {journal['class_name']}")
                        error_files += 1
                        continue

                    self.log_message.emit(f"\n  📄 {journal['class_name']}")

                    results, stats, error = self.checker.check_journal_file(
                        file_path,
                        curriculum_data,
                        self.check_mode,
                        self.start_date,
                        self.end_date,
                        self.log_message.emit
                    )

                    if error:
                        error_files += 1
                        self.log_message.emit(f"    ⚠️ {error}")
                    else:
                        level_results.extend(results)
                        level_stats.extend(stats)
                        if results:
                            self.log_message.emit(f"    ✅ Найдено замечаний: {len(results)}")
                        if stats:
                            self.log_message.emit(f"    📊 Записей в статистике: {len(stats)}")

                if level_stats or level_results:
                    all_results.extend(level_results)
                    all_stats.extend(level_stats)

                    if self.check_mode == "custom":
                        if self.start_date and self.end_date:
                            start_clean = self.start_date.replace('.', '')
                            end_clean = self.end_date.replace('.', '')
                            period_name = f"с_{start_clean}_по_{end_clean}"
                        else:
                            period_name = "произвольный_период"
                    else:
                        period_names = {
                            "Т1": "Триместр_1",
                            "Т2": "Триместр_2",
                            "Т3": "Триместр_3",
                            "П1": "Полугодие_1",
                            "П2": "Полугодие_2"
                        }
                        period_name = period_names.get(self.check_mode, self.check_mode)

                    import re
                    period_name = re.sub(r'[\\/*?:"<>|]', '_', period_name)
                    os.makedirs(self.output_folder, exist_ok=True)

                    output_path = self.checker.save_results_to_excel(
                        level_results, level_stats, self.output_folder, level, period_name
                    )
                    self.log_message.emit(f"\n  💾 Результаты сохранены: {output_path}")
                else:
                    self.log_message.emit(f"\n  ⚠️ Нет данных для сохранения по параллели {level}")

            self.log_message.emit(f"\n📊 Итоги проверки:")
            self.log_message.emit(f"  Обработано файлов: {total_files}")
            self.log_message.emit(f"  Найдено замечаний: {len(all_results)}")
            self.log_message.emit(f"  Записей в полной статистике: {len(all_stats)}")
            self.log_message.emit(f"  Файлов с ошибками: {error_files}")

            self.finished.emit((total_files, len(all_results)))

        except Exception as e:
            self.log_message.emit(f"❌ Критическая ошибка: {str(e)}")
            import traceback
            traceback.print_exc()
            self.finished.emit((0, 0))