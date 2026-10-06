# -*- coding: utf-8 -*-
"""
Единый модуль стилей приложения zavuch 2.
Палитра — Tailwind CSS.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QLabel, QPlainTextEdit, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget, QApplication,
)


# ============================================================
# Цветовая палитра (Tailwind)
# ============================================================
class C:
    SLATE_50, SLATE_100, SLATE_200, SLATE_300 = "#f8fafc", "#f1f5f9", "#e2e8f0", "#cbd5e1"
    SLATE_400, SLATE_500, SLATE_600, SLATE_700 = "#94a3b8", "#64748b", "#475569", "#334155"
    SLATE_800, SLATE_900 = "#1e293b", "#0f172a"

    BLUE_50, BLUE_100, BLUE_200 = "#eff6ff", "#dbeafe", "#bfdbfe"
    BLUE_500, BLUE_600, BLUE_700 = "#3b82f6", "#2563eb", "#1d4ed8"
    BLUE_800, BLUE_900 = "#1e40af", "#1e3a8a"

    VIOLET_50, VIOLET_100, VIOLET_200 = "#f5f3ff", "#ede9fe", "#ddd6fe"
    VIOLET_500, VIOLET_600, VIOLET_700 = "#8b5cf6", "#7c3aed", "#6d28d9"
    VIOLET_800 = "#5b21b6"

    GREEN_50, GREEN_100, GREEN_200 = "#ecfdf5", "#d1fae5", "#a7f3d0"
    GREEN_500, GREEN_600, GREEN_700 = "#10b981", "#059669", "#047857"
    GREEN_800, GREEN_900 = "#065f46", "#064e3b"

    RED_50, RED_100, RED_200 = "#fef2f2", "#fee2e2", "#fecaca"
    RED_500, RED_600, RED_700 = "#ef4444", "#dc2626", "#b91c1c"
    RED_800 = "#991b1b"

    ORANGE_50, ORANGE_200 = "#fff7ed", "#fed7aa"
    ORANGE_600, ORANGE_700, ORANGE_800 = "#ea580c", "#c2410c", "#9a3412"

    YELLOW_50, YELLOW_200 = "#fffbeb", "#fde68a"
    YELLOW_700, YELLOW_800 = "#b45309", "#92400e"

    TEAL_50, TEAL_200 = "#f0fdfa", "#99f6e4"
    TEAL_600, TEAL_700, TEAL_800 = "#0d9488", "#0f766e", "#115e59"

    INDIGO_50, INDIGO_200 = "#eef2ff", "#c7d2fe"
    INDIGO_600, INDIGO_700, INDIGO_800 = "#4f46e5", "#4338ca", "#3730a3"

    SKY_100, SKY_200, SKY_300 = "#e0f2fe", "#bae6fd", "#7dd3fc"
    SKY_500, SKY_600, SKY_700 = "#0ea5e9", "#0284c7", "#0369a1"
    SKY_800, SKY_900 = "#075985", "#0c4a6e"


# ============================================================
# Цвета параллелей и статусов
# ============================================================
LEVEL_COLORS = {
    1: C.BLUE_700, 2: C.BLUE_700, 3: C.BLUE_700, 4: C.BLUE_700,
    5: C.VIOLET_600, 6: C.VIOLET_600, 7: C.VIOLET_600, 8: C.VIOLET_600, 9: C.VIOLET_600,
    10: C.GREEN_600, 11: C.GREEN_600,
}

STATUS_COLORS = {
    "match":        (QColor(209, 250, 229), QColor(6, 95, 70)),
    "mismatch":     (QColor(254, 202, 202), QColor(153, 27, 27)),
    "missing_gpa":  (QColor(254, 240, 138), QColor(133, 77, 14)),
    "debt":         (QColor(254, 215, 170), QColor(124, 45, 18)),
    "npa":          (QColor(254, 215, 170), QColor(124, 45, 18)),
    "missing_data": (QColor(226, 232, 240), QColor(30, 41, 59)),
}

BUILDING_COLORS = {
    "Маршала Захарова":   QColor(219, 234, 254),
    "Домодедовская":      QColor(209, 250, 229),
    "Совхоз им. Ленина":  QColor(254, 249, 195),
    "ЗИЛ / Лихачёва":     QColor(237, 233, 254),
    "Елецкая":            QColor(254, 215, 170),
    "Шипиловская":        QColor(226, 232, 240),
}

ROW_COLORS = {
    "green": QColor(209, 250, 229),
    "red":   QColor(254, 202, 202),
    "gray":  QColor(241, 245, 249),
    "blue":  QColor(219, 234, 254),
}


# ============================================================
# Базовый стиль вкладок
# ============================================================
TAB_STYLE = f"""
    QWidget {{ font-size: 10pt; color: {C.SLATE_800}; }}
    QGroupBox {{
        font-size: 11pt; font-weight: 700;
        border: 1px solid {C.SLATE_300};
        border-radius: 10px; margin-top: 12px;
        padding: 18px 14px 14px 14px; background: #ffffff;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
    QLineEdit {{
        min-height: 30px; padding: 2px 8px;
        border: 1px solid {C.SLATE_300}; border-radius: 5px;
        background: #ffffff; color: {C.SLATE_800};
    }}
    QLineEdit:focus {{ border: 1px solid {C.BLUE_500}; }}
    QLineEdit:disabled {{ background: {C.SLATE_100}; color: {C.SLATE_400}; }}
    QPushButton {{
        min-height: 30px; padding: 4px 12px;
        border: 1px solid {C.SLATE_300}; border-radius: 5px;
        background: {C.SLATE_50}; color: {C.SLATE_800}; font-weight: 500;
    }}
    QPushButton:hover {{ background: {C.SLATE_200}; }}
    QPushButton:pressed {{ background: {C.SLATE_300}; }}
    QPushButton:disabled {{
        background: {C.SLATE_100}; color: {C.SLATE_400};
        border-color: {C.SLATE_200};
    }}
    QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        min-height: 30px; padding: 2px 8px;
        border: 1px solid {C.SLATE_300}; border-radius: 5px; background: #ffffff;
    }}
    QCheckBox {{ color: {C.SLATE_700}; spacing: 6px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; }}
    QScrollArea {{
        border: 1px solid {C.SLATE_200}; background: #fafafa; border-radius: 6px;
    }}
    QTableWidget {{
        border: 1px solid {C.SLATE_200}; border-radius: 6px;
        gridline-color: {C.SLATE_200}; alternate-background-color: {C.SLATE_50};
    }}
    QTableWidget::item {{ padding: 3px 6px; }}
    QHeaderView::section {{
        background: {C.SLATE_100}; color: {C.SLATE_800}; padding: 5px;
        border: none; border-right: 1px solid {C.SLATE_200};
        border-bottom: 1px solid {C.SLATE_200}; font-weight: 600;
    }}
    QProgressBar {{
        min-height: 22px; border: 1px solid {C.SLATE_300}; border-radius: 6px;
        background: {C.SLATE_50}; text-align: center;
        color: {C.SLATE_800}; font-weight: 600;
    }}
    QLabel {{ color: {C.SLATE_700}; }}
"""


# ============================================================
# Пресеты кнопок
# ============================================================
def _primary(color, hover, pressed):
    return f"""
        QPushButton {{
            background-color: {color}; color: #ffffff;
            font-weight: 700; border: none; border-radius: 7px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
        QPushButton:disabled {{ background-color: {C.SLATE_300}; color: {C.SLATE_500}; }}
    """

PRIMARY_BTN       = _primary(C.BLUE_700,   C.BLUE_800,   C.BLUE_900)
PRIMARY_PDOU_BTN  = _primary(C.VIOLET_600, C.VIOLET_700, C.VIOLET_800)
PRIMARY_GREEN_BTN = _primary(C.GREEN_600,  C.GREEN_700,  C.GREEN_800)
PRIMARY_TEAL_BTN  = _primary(C.TEAL_600,   C.TEAL_700,   C.TEAL_800)
PRIMARY_SKY_BTN   = _primary(C.SKY_700,    C.SKY_800,    C.SKY_900)
PRIMARY_INDIGO_BTN = _primary(C.INDIGO_600, C.INDIGO_700, C.INDIGO_800)
PRIMARY_ORANGE_BTN = _primary(C.ORANGE_600, C.ORANGE_700, C.ORANGE_800)

SUCCESS_BTN = PRIMARY_GREEN_BTN
WARNING_BTN = PRIMARY_ORANGE_BTN

DANGER_BTN = f"""
    QPushButton {{
        background-color: {C.RED_50}; color: {C.RED_700};
        border: 1px solid {C.RED_200}; font-weight: 600;
    }}
    QPushButton:hover {{ background-color: {C.RED_100}; }}
    QPushButton:disabled {{
        background: {C.SLATE_100}; color: {C.SLATE_400}; border-color: {C.SLATE_200};
    }}
"""


def _ghost(bg, color, border, hover_bg):
    return f"""
        QPushButton {{
            background: {bg}; color: {color};
            border: 1px solid {border}; font-weight: 600;
        }}
        QPushButton:hover {{ background: {hover_bg}; }}
    """

GHOST_BTN       = _ghost(C.BLUE_50,    C.BLUE_700,   C.BLUE_200,   C.BLUE_100)
GHOST_PDOU_BTN  = _ghost(C.VIOLET_50,  C.VIOLET_600, C.VIOLET_200, C.VIOLET_100)
GHOST_GREEN_BTN = _ghost(C.GREEN_50,   C.GREEN_600,  C.GREEN_200,  C.GREEN_100)
GHOST_TEAL_BTN  = _ghost(C.TEAL_50,    C.TEAL_600,   C.TEAL_200,   C.TEAL_100)
GHOST_SKY_BTN   = _ghost(C.SKY_100,    C.SKY_700,    C.SKY_200,    C.SKY_200)


# ============================================================
# Стили групп с цветовыми акцентами
# ============================================================
def groupbox_style(color, border):
    return f"""
        QGroupBox {{
            font-size: 11pt; font-weight: 700; color: {color};
            border: 1px solid {border}; border-radius: 10px;
            margin-top: 12px; padding: 18px 14px 14px 14px; background: #ffffff;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
    """

GROUPBOX_BLUE    = groupbox_style(C.BLUE_700,   C.BLUE_200)
GROUPBOX_VIOLET  = groupbox_style(C.VIOLET_600, C.VIOLET_200)
GROUPBOX_GREEN   = groupbox_style(C.GREEN_600,  C.GREEN_200)
GROUPBOX_SKY     = groupbox_style(C.SKY_700,    C.SKY_300)
GROUPBOX_ORANGE  = groupbox_style(C.ORANGE_700, "#fdba74")
GROUPBOX_INDIGO  = groupbox_style(C.INDIGO_600, C.INDIGO_200)
GROUPBOX_TEAL    = groupbox_style(C.TEAL_600,   C.TEAL_200)
GROUPBOX_SLATE   = groupbox_style(C.SLATE_600,  C.SLATE_300)
GROUPBOX_FILTER  = groupbox_style(C.SKY_700,    C.SKY_300)


# ============================================================
# Стили статусных «пилюль»
# ============================================================
def pill_style(color, bg, border):
    return (f"color: {color}; background: {bg}; border: 1px solid {border}; "
            f"border-radius: 6px; padding: 7px 10px; font-weight: 600;")

PILL_OK      = pill_style(C.GREEN_800,  C.GREEN_50,  C.GREEN_200)
PILL_ERROR   = pill_style(C.RED_800,    C.RED_50,    C.RED_200)
PILL_WARN    = pill_style(C.YELLOW_800, C.YELLOW_50, C.YELLOW_200)
PILL_INFO    = pill_style(C.BLUE_800,   C.BLUE_50,   C.BLUE_200)
PILL_VIOLET  = pill_style(C.VIOLET_700, C.VIOLET_50, C.VIOLET_200)
PILL_TEAL    = pill_style(C.TEAL_800,   C.TEAL_50,   C.TEAL_200)


# ============================================================
# Консоль
# ============================================================
CONSOLE_STYLE = f"""
    QPlainTextEdit, QTextEdit {{
        font-family: Consolas, "Courier New", monospace;
        font-size: 9.5pt;
        background-color: {C.SLATE_900}; color: {C.SLATE_200};
        border: 1px solid {C.SLATE_700}; border-radius: 6px; padding: 6px;
        selection-background-color: {C.BLUE_800}; selection-color: #ffffff;
    }}
"""


# ============================================================
# Фабрики UI
# ============================================================
def make_title(text, size_pt=16, color=C.SLATE_900):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: {size_pt}pt; font-weight: 700; "
        f"color: {color}; padding: 2px 0 6px 0;"
    )
    return lbl


def make_subtitle(text):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {C.SLATE_500}; margin-bottom: 4px;")
    return lbl


def make_hint(text, color=C.SLATE_600, bg=C.SLATE_50, border=C.SLATE_200):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color: {color}; background-color: {bg}; border: 1px solid {border}; "
        f"padding: 10px; border-radius: 6px; font-size: 9.5pt;"
    )
    return lbl


def make_warning(text):
    return make_hint(text, C.YELLOW_700, C.YELLOW_50, C.YELLOW_200)


def make_log_view(min_h=140, max_h=220):
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setMaximumBlockCount(3000)
    view.setMinimumHeight(min_h)
    view.setMaximumHeight(max_h)
    view.setStyleSheet(CONSOLE_STYLE)
    return view


def make_separator():
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(
        f"color: {C.SLATE_200}; background: {C.SLATE_200}; max-height: 1px;"
    )
    return sep


def make_status_pill(text, style):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(style)
    return lbl


def get_from_clipboard():
    try:
        return (QApplication.clipboard().text() or "").strip()
    except Exception:
        return ""


# ============================================================
# Сворачиваемый блок
# ============================================================
class CollapsibleGroupBox(QWidget):
    """Сворачиваемый блок с заголовком-кнопкой (▶ / ▼)."""

    def __init__(self, title, parent=None, collapsed=True,
                 accent_color=C.VIOLET_600, accent_border=C.VIOLET_200,
                 accent_bg=C.VIOLET_50, accent_hover=C.VIOLET_100,
                 accent_dark=C.VIOLET_700):
        super().__init__(parent)
        self._title_text = title
        self._status_suffix = ""
        self._collapsed = collapsed

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._header_btn = QToolButton()
        self._header_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._header_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(not collapsed)
        self._header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_btn.clicked.connect(self._on_header_clicked)
        self._header_btn.setStyleSheet(f"""
            QToolButton {{
                border: 1px solid {accent_border}; border-radius: 8px;
                background-color: {accent_bg}; padding: 9px 14px;
                font-weight: 700; font-size: 11pt; color: {accent_dark};
                text-align: left;
            }}
            QToolButton:hover {{ background-color: {accent_hover}; color: {accent_color}; }}
            QToolButton:checked {{
                border-bottom-left-radius: 0px; border-bottom-right-radius: 0px;
                border-bottom: none; background-color: {accent_hover};
            }}
        """)
        main_layout.addWidget(self._header_btn)

        self._content = QWidget()
        self._content.setObjectName("CollapsibleContent")
        self._content.setStyleSheet(f"""
            QWidget#CollapsibleContent {{
                background-color: #ffffff;
                border: 1px solid {accent_border}; border-top: none;
                border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;
            }}
        """)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(14, 12, 14, 14)
        self._content_layout.setSpacing(8)
        main_layout.addWidget(self._content)

        self._apply_collapsed_state()
        self._update_header_text()

    def _on_header_clicked(self):
        self._collapsed = not self._header_btn.isChecked()
        self._apply_collapsed_state()
        self._update_header_text()

    def _apply_collapsed_state(self):
        if self._collapsed:
            self._content.setVisible(False)
            self._header_btn.setArrowType(Qt.ArrowType.RightArrow)
        else:
            self._content.setVisible(True)
            self._header_btn.setArrowType(Qt.ArrowType.DownArrow)

    def _update_header_text(self):
        arrow = "▶" if self._collapsed else "▼"
        suffix = f"  —  {self._status_suffix}" if self._status_suffix else ""
        self._header_btn.setText(f"{arrow}  {self._title_text}{suffix}")

    def set_title(self, title):
        self._title_text = title
        self._update_header_text()

    def set_collapsed(self, collapsed):
        self._collapsed = collapsed
        self._header_btn.setChecked(not collapsed)
        self._apply_collapsed_state()
        self._update_header_text()

    def is_collapsed(self):
        return self._collapsed

    def content_layout(self):
        return self._content_layout

    def set_status_suffix(self, text):
        self._status_suffix = text or ""
        self._update_header_text()