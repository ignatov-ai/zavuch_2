# -*- coding: utf-8 -*-
from datetime import datetime


class AcademicCalendar:
    """Класс для работы с датами учебного года"""

    @staticmethod
    def get_academic_year(date=None):
        """
        Определяет учебный год для даты.
        Возвращает (start_year, end_year)
        """
        if date is None:
            date = datetime.now()

        if date.month >= 9:
            return date.year, date.year + 1
        else:
            return date.year - 1, date.year

    @staticmethod
    def get_academic_year_dates():
        """Возвращает даты начала и конца учебного года"""
        start_year, end_year = AcademicCalendar.get_academic_year()
        start_date = datetime(start_year, 9, 1)
        end_date = datetime(end_year, 8, 31)
        return start_date, end_date

    @staticmethod
    def parse_date(day, month, year=None):
        """
        Преобразует день и месяц в datetime с учётом учебного года.
        Для дат из журнала (без года) определяет год автоматически.
        """
        if year is not None:
            return datetime(year, month, day)

        if month >= 9:
            year, _ = AcademicCalendar.get_academic_year()
            return datetime(year, month, day)
        else:
            _, year = AcademicCalendar.get_academic_year()
            return datetime(year, month, day)

    @staticmethod
    def parse_custom_date(date_str):
        """Парсит дату из строки в формате ДД.ММ.ГГГГ"""
        try:
            parts = date_str.split('.')
            if len(parts) == 3:
                day, month, year = parts
                return datetime(int(year), int(month), int(day))
        except:
            pass
        return None

    @staticmethod
    def get_period_dates(period_type, start_date_str=None, end_date_str=None):
        """
        Возвращает даты начала и конца периода.
        period_type: 'Т1', 'Т2', 'Т3', 'П1', 'П2', 'custom'
        """
        periods = {
            'Т1': {'start': (1, 9), 'end': (30, 11), 'name': 'Триместр 1'},
            'Т2': {'start': (1, 12), 'end': (28, 2), 'name': 'Триместр 2'},
            'Т3': {'start': (1, 3), 'end': (31, 5), 'name': 'Триместр 3'},
            'П1': {'start': (1, 9), 'end': (31, 12), 'name': 'Полугодие 1'},
            'П2': {'start': (1, 1), 'end': (31, 5), 'name': 'Полугодие 2'},
        }

        if period_type == 'custom':
            if not start_date_str or not end_date_str:
                return None, None, ""
            start = AcademicCalendar.parse_custom_date(start_date_str)
            end = AcademicCalendar.parse_custom_date(end_date_str)
            return start, end, f"{start_date_str} - {end_date_str}"

        period = periods.get(period_type)
        if not period:
            return None, None, ""

        start_year, end_year = AcademicCalendar.get_academic_year()
        start_day, start_month = period['start']
        end_day, end_month = period['end']

        if start_month >= 9:
            start_date = datetime(start_year, start_month, start_day)
        else:
            start_date = datetime(end_year, start_month, start_day)

        if end_month >= 9:
            end_date = datetime(start_year, end_month, end_day)
        else:
            end_date = datetime(end_year, end_month, end_day)

        return start_date, end_date, period['name']