# -*- coding: utf-8 -*-
"""
Единое место для путей проекта zavuch 2.

Все сессии и настройки хранятся в <папка проекта>/sessions/.
Это удобно:
  • всё лежит рядом с кодом;
  • легко сделать бэкап;
  • можно переносить проект вместе с сессиями.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SESSIONS_DIR = PROJECT_ROOT / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# ==== ЭЖД ====
SESSION_FILE      = SESSIONS_DIR / "session.pkl"
AUTH_DATA_FILE    = SESSIONS_DIR / "auth_data.json"
CREDENTIALS_FILE  = SESSIONS_DIR / "credentials.json"

# ==== ПДОУ ====
PDOU_TOKEN_FILE   = SESSIONS_DIR / "pdou_token.json"
PDOU_COOKIES_FILE = SESSIONS_DIR / "pdou_cookies.json"

# ==== Общее ====
SETTINGS_FILE     = SESSIONS_DIR / "settings.json"

# ==== Списки файлов для экспорта / импорта ====
EJD_FILES  = ["session.pkl", "auth_data.json", "credentials.json"]
PDOU_FILES = ["pdou_token.json", "pdou_cookies.json"]