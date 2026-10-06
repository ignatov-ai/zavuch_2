# -*- coding: utf-8 -*-
"""
Диалоги импорта токенов/сессий.
Содержит:
• TokenCheckWorker   — проверка ЭЖД auth_token (ручной ввод).
• EJDImportWorker    — импорт ЭЖД из ejd_session.json / auth_data.json / ejd_cookies.json.
• PDOUImportWorker   — импорт ПДОУ из pdou_session.json.
• TokenImportDialog  — диалог ручного ввода ЭЖД auth_token.
• EJDImportDialog    — диалог импорта ЭЖД-сессии из JSON.
• PDOUImportDialog   — диалог импорта ПДОУ-сессии из JSON.
"""
import base64
import datetime
import json
import pickle
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QPlainTextEdit, QMessageBox, QFormLayout,
    QFileDialog, QFrame,
)
from paths import (
    SESSIONS_DIR,
    SESSION_FILE,
    AUTH_DATA_FILE,
    PDOU_TOKEN_FILE,
    PDOU_COOKIES_FILE,
)


# ============================================================
# Утилиты
# ============================================================
def decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        b64 = parts[1]
        pad = "=" * (-len(b64) % 4)
        decoded = base64.urlsafe_b64decode(b64 + pad).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def get_from_clipboard() -> str:
    try:
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        return (cb.text() or "").strip()
    except Exception:
        return ""


def _build_cookie(name, value, domain):
    return Cookie(
        version=0, name=name, value=str(value),
        port=None, port_specified=False,
        domain=domain, domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/", path_specified=True,
        secure=False, expires=None, discard=False,
        comment=None, comment_url=None,
        rest={}, rfc2109=False,
    )


def _safe_pickle_jar(cj):
    """
    Возвращает список словарей [{name, value, domain, path, secure, expires}, ...].
    Это 100% безопасно для pickle — нет RLock.
    """
    cookies_list = []
    try:
        for c in cj:
            cookies_list.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path or "/",
                "secure": bool(c.secure),
                "expires": c.expires,
            })
    except Exception:
        try:
            for name, value in requests.utils.dict_from_cookiejar(cj).items():
                cookies_list.append({
                    "name": name, "value": value,
                    "domain": "dnevnik.mos.ru", "path": "/",
                    "secure": False, "expires": None,
                })
        except Exception:
            pass
    return cookies_list


# ============================================================
# Единые стили диалогов
# ============================================================
DIALOG_STYLE = """
    QDialog {
        background-color: #ffffff;
    }
    QWidget {
        font-size: 10pt;
        color: #1e293b;
    }
    QLabel {
        color: #334155;
    }
    QLineEdit {
        min-height: 32px;
        padding: 2px 10px;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        background: #ffffff;
        color: #1e293b;
    }
    QLineEdit:focus {
        border: 1px solid #3b82f6;
    }
    QLineEdit:disabled {
        background: #f1f5f9;
        color: #94a3b8;
    }
    QPushButton {
        min-height: 32px;
        padding: 4px 14px;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        background: #f8fafc;
        color: #1e293b;
        font-weight: 500;
    }
    QPushButton:hover {
        background: #e2e8f0;
    }
    QPushButton:pressed {
        background: #cbd5e1;
    }
    QPushButton:disabled {
        background: #f1f5f9;
        color: #94a3b8;
        border-color: #e2e8f0;
    }
    QPlainTextEdit {
        font-family: Consolas, "Courier New", monospace;
        font-size: 9.5pt;
    }
"""

# === ЭЖД-акцент (синий) ===
PRIMARY_EJD_BTN = """
    QPushButton {
        background-color: #1d4ed8;
        color: #ffffff;
        font-weight: 700;
        border: none;
        border-radius: 7px;
    }
    QPushButton:hover { background-color: #1e40af; }
    QPushButton:pressed { background-color: #1e3a8a; }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""

# === ПДОУ-акцент (фиолетовый) ===
PRIMARY_PDOU_BTN = """
    QPushButton {
        background-color: #7c3aed;
        color: #ffffff;
        font-weight: 700;
        border: none;
        border-radius: 7px;
    }
    QPushButton:hover { background-color: #6d28d9; }
    QPushButton:pressed { background-color: #5b21b6; }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""

SUCCESS_BTN = """
    QPushButton {
        background-color: #059669;
        color: #ffffff;
        font-weight: 600;
        border: none;
        border-radius: 6px;
    }
    QPushButton:hover { background-color: #047857; }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #64748b;
    }
"""

GHOST_BTN = """
    QPushButton {
        background: #eff6ff;
        color: #1d4ed8;
        border: 1px solid #bfdbfe;
        font-weight: 600;
    }
    QPushButton:hover { background: #dbeafe; }
"""

GHOST_PDOU_BTN = """
    QPushButton {
        background: #f5f3ff;
        color: #7c3aed;
        border: 1px solid #ddd6fe;
        font-weight: 600;
    }
    QPushButton:hover { background: #ede9fe; }
"""

DANGER_BTN = """
    QPushButton {
        background-color: #fff1f2;
        color: #be123c;
        border: 1px solid #fecdd3;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #ffe4e6; }
"""


# ============================================================
# ЭЖД: проверка ручного токена
# ============================================================
class TokenCheckWorker(QThread):
    log = Signal(str)
    done = Signal(dict)

    def __init__(self, auth_token, aupd_token="", profile_id="", save=False):
        super().__init__()
        self.auth_token = auth_token
        self.aupd_token = aupd_token or auth_token
        self.profile_id = profile_id or ""
        self.save = save

    def _log(self, msg):
        self.log.emit(msg)

    def run(self):
        result = {"ok": False, "school": "", "reason": "", "saved": False}
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Auth-Token": self.auth_token,
            "Authorization": f"Bearer {self.auth_token}",
        })
        if self.profile_id:
            session.headers["Profile-Id"] = str(self.profile_id)

        cj = CookieJar()
        for domain in ("dnevnik.mos.ru", "school.mos.ru"):
            cj.set_cookie(_build_cookie("auth_token", self.auth_token, domain))
        if self.aupd_token:
            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                cj.set_cookie(_build_cookie("aupd_token", self.aupd_token, domain))
        if self.profile_id:
            cj.set_cookie(_build_cookie("profile_id", self.profile_id,
                                        "dnevnik.mos.ru"))
        for c in cj:
            session.cookies.set_cookie(c)

        try:
            r = session.get("https://dnevnik.mos.ru/core/api/schools", timeout=15)
        except Exception as e:
            result["reason"] = f"Ошибка сети: {e}"
            self.done.emit(result)
            return

        self._log(f"[i] HTTP {r.status_code}")
        if r.status_code != 200:
            result["reason"] = f"HTTP {r.status_code}: {r.text[:200]}"
            self.done.emit(result)
            return

        try:
            data = r.json()
        except Exception:
            result["reason"] = "Ответ не JSON"
            self.done.emit(result)
            return

        if not data:
            result["reason"] = "Пустой ответ API"
            self.done.emit(result)
            return

        school_name = data[0].get("name", "?")
        sid = str(data[0].get("id", ""))
        self._log(f"[+] Токен принят. Школа: {school_name}")
        result["ok"] = True
        result["school"] = school_name

        if self.save:
            try:
                clean = _safe_pickle_jar(cj)
                with open(SESSION_FILE, "wb") as f:
                    pickle.dump(clean, f)
                with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "auth_token": self.auth_token,
                        "aupd_token": self.aupd_token,
                        "profile_id": str(self.profile_id),
                        "school_id": sid,
                    }, f, ensure_ascii=False, indent=2)
                self._log(f"[+] Сохранено: {SESSION_FILE}")
                self._log(f"[+] Сохранено: {AUTH_DATA_FILE}")
                result["saved"] = True
            except Exception as e:
                self._log(f"[!] Ошибка сохранения: {e}")
                result["reason"] = f"Ошибка сохранения: {e}"

        self.done.emit(result)


# ============================================================
# ЭЖД: импорт из JSON
# ============================================================
class EJDImportWorker(QThread):
    log = Signal(str)
    done = Signal(dict)

    def __init__(self, raw_json, save=True):
        super().__init__()
        self.raw_json = raw_json
        self.save = save

    def _log(self, msg):
        self.log.emit(msg)

    def run(self):
        result = {"ok": False, "school": "", "reason": "", "saved": False}
        try:
            data = json.loads(self.raw_json)
        except Exception as e:
            result["reason"] = f"Не JSON: {e}"
            self.done.emit(result)
            return

        if not isinstance(data, dict):
            result["reason"] = "Корень JSON не объект"
            self.done.emit(result)
            return

        auth_token = (data.get("auth_token") or "").strip()
        aupd_token = (data.get("aupd_token") or "").strip()
        profile_id = str(data.get("profile_id") or "").strip()
        school_id = str(data.get("school_id") or "").strip()

        if not auth_token:
            result["reason"] = "В JSON нет поля auth_token"
            self.done.emit(result)
            return

        cookies = data.get("cookies")
        if not isinstance(cookies, dict) or not cookies:
            SYSTEM_KEYS = {
                "auth_token", "aupd_token", "profile_id", "school_id",
                "saved_at", "source", "_auth_token_source",
            }
            flat = {}
            for k, v in data.items():
                if k in SYSTEM_KEYS:
                    continue
                if k.startswith("_"):
                    continue
                if isinstance(v, (str, int, float)):
                    flat[k] = str(v)
            if flat:
                cookies = flat
                self._log(f"[i] Обнаружен плоский формат cookies: "
                          f"{len(flat)} шт. в корне JSON")
            else:
                cookies = {}

        self._log(f"[i] auth_token: {'✅' if auth_token else '❌'} "
                  f"({len(auth_token)} симв.)")
        self._log(f"[i] aupd_token: {'✅' if aupd_token else '—'} "
                  f"({len(aupd_token)} симв.)")
        self._log(f"[i] profile_id: {profile_id or '❌'}")
        self._log(f"[i] school_id:  {school_id or '—'}")
        self._log(f"[i] cookies:    {len(cookies)} шт.")

        cj = CookieJar()
        for name, value in cookies.items():
            if not name or value is None:
                continue
            if name.startswith("_"):
                continue
            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                cj.set_cookie(_build_cookie(name, value, domain))

        if auth_token:
            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                cj.set_cookie(_build_cookie("auth_token", auth_token, domain))
        if aupd_token:
            for domain in ("dnevnik.mos.ru", "school.mos.ru"):
                cj.set_cookie(_build_cookie("aupd_token", aupd_token, domain))
        if profile_id:
            cj.set_cookie(_build_cookie("profile_id", profile_id,
                                        "dnevnik.mos.ru"))

        self._log("[i] Проверяю через dnevnik.mos.ru/core/api/schools...")
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        })
        for c in cj:
            session.cookies.set_cookie(c)
        session.headers["Auth-Token"] = auth_token
        session.headers["Authorization"] = f"Bearer {auth_token}"
        if profile_id:
            session.headers["Profile-Id"] = profile_id

        try:
            r = session.get("https://dnevnik.mos.ru/core/api/schools", timeout=15)
        except Exception as e:
            self._log(f"[!] Ошибка сети: {e}")
            result["reason"] = f"Ошибка сети: {e}"
            self.done.emit(result)
            return

        self._log(f"[i] HTTP {r.status_code}")
        if r.status_code != 200:
            result["reason"] = f"HTTP {r.status_code}: {r.text[:200]}"
            self.done.emit(result)
            return

        try:
            schools = r.json()
        except Exception:
            result["reason"] = "Ответ не JSON"
            self.done.emit(result)
            return

        if not schools:
            result["reason"] = "Пустой ответ API"
            self.done.emit(result)
            return

        school_name = schools[0].get("name", "?")
        sid = str(schools[0].get("id", "") or school_id or "")
        self._log(f"[+] Токен принят. Школа: {school_name}")
        result["ok"] = True
        result["school"] = school_name

        if self.save:
            try:
                # Собираем cookies как список словарей — безопасно для pickle
                cookies_list = []
                for c in cj:
                    cookies_list.append({
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path or "/",
                        "secure": bool(c.secure),
                        "expires": c.expires,
                    })

                with open(SESSION_FILE, "wb") as f:
                    pickle.dump(cookies_list, f)
                with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "auth_token": auth_token,
                        "aupd_token": aupd_token or auth_token,
                        "profile_id": profile_id,
                        "school_id": sid,
                    }, f, ensure_ascii=False, indent=2)
                self._log(f"[+] Сохранено: {SESSION_FILE}")
                self._log(f"[+] Сохранено: {AUTH_DATA_FILE}")
                result["saved"] = True
            except Exception as e:
                self._log(f"[!] Ошибка сохранения: {e}")
                result["reason"] = f"Ошибка сохранения: {e}"

        self.done.emit(result)


# ============================================================
# ПДОУ: импорт
# ============================================================
class PDOUImportWorker(QThread):
    log = Signal(str)
    done = Signal(dict)
    USER_URL = ("https://esz.mos.ru/Services/"
                "AuthorizationService/User/CurrentUser")

    def __init__(self, raw_json, save=True):
        super().__init__()
        self.raw_json = raw_json
        self.save = save

    def _log(self, msg):
        self.log.emit(msg)

    def run(self):
        result = {
            "ok": False, "user_name": "", "roles": [],
            "reason": "", "saved": False,
        }
        try:
            data = json.loads(self.raw_json)
        except Exception as e:
            result["reason"] = f"Не JSON: {e}"
            self.done.emit(result)
            return

        if not isinstance(data, dict):
            result["reason"] = "Корень JSON не объект"
            self.done.emit(result)
            return

        aupd_token = (data.get("aupd_token") or "").strip()
        esztoken = (data.get("esztoken") or "").strip()
        cookies = data.get("cookies") or {}

        if not aupd_token:
            result["reason"] = "В JSON нет поля aupd_token"
            self.done.emit(result)
            return
        if not esztoken:
            result["reason"] = "В JSON нет поля esztoken"
            self.done.emit(result)
            return
        if not isinstance(cookies, dict) or not cookies:
            result["reason"] = "В JSON нет поля cookies"
            self.done.emit(result)
            return

        cookies = {k: v for k, v in cookies.items()
                   if not k.startswith("_") and v}

        self._log(f"[i] aupd_token: {len(aupd_token)} симв.")
        self._log(f"[i] esztoken:   {len(esztoken)} симв.")
        self._log(f"[i] cookies:    {len(cookies)} шт.")

        has_ltpa = "Ltpatoken2" in cookies
        has_session = "session-cookie" in cookies
        self._log(f"[i] Ltpatoken2: {'✅' if has_ltpa else '❌'} | "
                  f"session-cookie: {'✅' if has_session else '❌'}")

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://esz.mos.ru",
            "Referer": "https://esz.mos.ru/serviceClasses",
            "Authorization": f"Bearer {aupd_token}",
            "x-mes-subsystem": "headerweb",
            "x-mes-hostId": "28",
            "esztoken": esztoken,
        })
        for name, value in cookies.items():
            try:
                session.cookies.set(name, str(value), domain="esz.mos.ru")
                session.cookies.set(name, str(value), domain=".mos.ru")
            except Exception:
                pass
        if has_ltpa:
            session.headers["LtpaToken2"] = cookies["Ltpatoken2"]

        try:
            r = session.get(self.USER_URL, timeout=20)
        except Exception as e:
            result["reason"] = f"Ошибка сети: {e}"
            self.done.emit(result)
            return

        self._log(f"[i] HTTP {r.status_code}")
        if r.status_code != 200:
            result["reason"] = f"HTTP {r.status_code}: {r.text[:200]}"
            self.done.emit(result)
            return

        try:
            user = r.json()
        except Exception:
            result["reason"] = "Ответ не JSON"
            self.done.emit(result)
            return

        user_name = (data.get("user_name") or "").strip()
        roles = data.get("user_roles") or []
        if not user_name:
            user_name = user.get("userName") or user.get("login") or ""
            full = user.get("fullName") or {}
            if full:
                parts = [
                    full.get("lastName", ""),
                    full.get("firstName", ""),
                    full.get("middleName", ""),
                ]
                user_name = " ".join(p for p in parts if p) or user_name
        if not roles:
            roles = []
            for role in (user.get("roles") or []):
                if isinstance(role, dict):
                    roles.append(role.get("name") or f"id {role.get('id')}")
                else:
                    roles.append(str(role))

        self._log(f"[+] Пользователь: {user_name or '?'}")
        self._log(f"[+] Роли: {', '.join(roles) or '(нет)'}")

        result["ok"] = True
        result["user_name"] = user_name
        result["roles"] = roles

        if self.save:
            try:
                with open(PDOU_TOKEN_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "aupd_token": aupd_token,
                        "esztoken": esztoken,
                        "user_name": user_name,
                        "user_roles": roles,
                        "saved_at": datetime.datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "browser_console",
                    }, f, ensure_ascii=False, indent=2)
                with open(PDOU_COOKIES_FILE, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                self._log(f"[+] Сохранено: {PDOU_TOKEN_FILE}")
                self._log(f"[+] Сохранено: {PDOU_COOKIES_FILE}")
                result["saved"] = True
            except Exception as e:
                self._log(f"[!] Ошибка сохранения: {e}")
                result["reason"] = f"Ошибка сохранения: {e}"

        self.done.emit(result)


# ============================================================
# Базовый диалог импорта (общий каркас)
# ============================================================
class _BaseImportDialog(QDialog):
    """Базовый класс для диалогов импорта. Задаёт единый стиль."""
    tokens_saved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self._apply_dialog_style()

    def _apply_dialog_style(self):
        self.setStyleSheet(DIALOG_STYLE)

    def _make_title(self, text: str, size_pt: int = 16) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: {size_pt}pt; font-weight: 700; "
            f"color: #0f172a; padding: 2px 0 4px 0;"
        )
        return lbl

    def _make_subtitle(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #64748b; margin-bottom: 4px;")
        return lbl

    def _make_hint(self, text: str, color: str = "#475569",
                   bg: str = "#f8fafc", border: str = "#e2e8f0") -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"""
            color: {color};
            background-color: {bg};
            border: 1px solid {border};
            padding: 10px;
            border-radius: 6px;
            font-size: 9.5pt;
        """)
        return lbl

    def _make_warning(self, text: str) -> QLabel:
        return self._make_hint(
            text,
            color="#b45309",
            bg="#fffbeb",
            border="#fde68a",
        )

    def _make_log_view(self) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMaximumBlockCount(3000)
        view.setMinimumHeight(140)
        view.setStyleSheet("""
            QPlainTextEdit {
                font-family: Consolas, "Courier New", monospace;
                font-size: 9.5pt;
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
                selection-background-color: #1e40af;
                selection-color: #ffffff;
            }
        """)
        return view

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            "color: #e2e8f0; background: #e2e8f0; max-height: 1px;"
        )
        return sep

    def append_log(self, msg):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())


# ============================================================
# Диалог ЭЖД (ручной ввод)
# ============================================================
class TokenImportDialog(_BaseImportDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋  Импорт ЭЖД-токенов")
        self.setMinimumSize(760, 660)
        self.last_auth_obj = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # === Заголовок ===
        layout.addWidget(self._make_title("📋  Импорт токенов ЭЖД"))
        layout.addWidget(self._make_subtitle(
            "Ручной ввод auth_token из DevTools браузера."
        ))

        # === Подсказка ===
        hint = self._make_hint(
            "Откройте Chrome DevTools (F12) на dnevnik.mos.ru:\n"
            "  Application → Cookies → https://dnevnik.mos.ru\n"
            "Скопируйте значения полей auth_token и (опционально) aupd_token."
        )
        layout.addWidget(hint)

        # === Форма полей ===
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)

        # auth_token
        self.auth_token_edit = QLineEdit()
        self.auth_token_edit.setPlaceholderText("auth_token (JWT)")
        self.auth_token_edit.textChanged.connect(self._on_token_changed)
        auth_row = QHBoxLayout()
        auth_row.setSpacing(6)
        auth_row.addWidget(self.auth_token_edit, 1)
        b = QPushButton("📋 Из буфера")
        b.setStyleSheet(GHOST_BTN)
        b.setMaximumWidth(140)
        b.clicked.connect(lambda: self._paste_into(self.auth_token_edit))
        auth_row.addWidget(b)
        form.addRow(self._form_label("auth_token:"), auth_row)

        # aupd_token
        self.aupd_token_edit = QLineEdit()
        self.aupd_token_edit.setPlaceholderText("aupd_token (необязательно)")
        aupd_row = QHBoxLayout()
        aupd_row.setSpacing(6)
        aupd_row.addWidget(self.aupd_token_edit, 1)
        b = QPushButton("📋 Из буфера")
        b.setStyleSheet(GHOST_BTN)
        b.setMaximumWidth(140)
        b.clicked.connect(lambda: self._paste_into(self.aupd_token_edit))
        aupd_row.addWidget(b)
        form.addRow(self._form_label("aupd_token:"), aupd_row)

        # profile_id
        self.profile_id_edit = QLineEdit()
        self.profile_id_edit.setPlaceholderText("profile_id (опционально)")
        pid_row = QHBoxLayout()
        pid_row.setSpacing(6)
        pid_row.addWidget(self.profile_id_edit, 1)
        b = QPushButton("📋 Из буфера")
        b.setStyleSheet(GHOST_BTN)
        b.setMaximumWidth(140)
        b.clicked.connect(lambda: self._paste_into(self.profile_id_edit))
        pid_row.addWidget(b)
        form.addRow(self._form_label("profile_id:"), pid_row)

        layout.addLayout(form)

        # === Кнопки действий ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self.check_btn = QPushButton("🔍  Проверить")
        self.check_btn.setMinimumHeight(38)
        self.check_btn.setMinimumWidth(160)
        self.check_btn.setStyleSheet(GHOST_BTN)
        self.check_btn.clicked.connect(lambda: self._start_worker(save=False))
        btn_row.addWidget(self.check_btn)

        self.save_btn = QPushButton("💾  Сохранить")
        self.save_btn.setMinimumHeight(38)
        self.save_btn.setMinimumWidth(160)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(SUCCESS_BTN)
        self.save_btn.clicked.connect(lambda: self._start_worker(save=True))
        btn_row.addWidget(self.save_btn)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumHeight(38)
        self.close_btn.setMinimumWidth(110)
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        # === Разделитель ===
        layout.addWidget(self._make_separator())

        # === Журнал ===
        log_title = QLabel("📋  Журнал")
        log_title.setStyleSheet(
            "font-size: 11pt; font-weight: 700; color: #0369a1;"
        )
        layout.addWidget(log_title)

        self.log_view = self._make_log_view()
        layout.addWidget(self.log_view, 1)

    def _form_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-weight: 600; color: #334155; padding-right: 4px;"
        )
        return lbl

    def _paste_into(self, line_edit):
        text = get_from_clipboard()
        if text:
            line_edit.setText(text)
            self.append_log(f"[clipboard] Вставлено {len(text)} символов")

    def _on_token_changed(self, text):
        has = bool(text.strip()) and len(text.strip()) > 50
        self.check_btn.setEnabled(has)
        self.save_btn.setEnabled(False)

    def _start_worker(self, save):
        auth_token = self.auth_token_edit.text().strip()
        if not auth_token or len(auth_token) < 50:
            QMessageBox.warning(self, "Ошибка", "Некорректный auth_token.")
            return
        aupd = self.aupd_token_edit.text().strip() or auth_token
        pid = self.profile_id_edit.text().strip()

        self._set_ui_enabled(False)
        self.append_log("=" * 50)
        self.append_log(
            f"[i] {'Сохранение' if save else 'Проверка'}..."
        )
        self.worker = TokenCheckWorker(
            auth_token=auth_token, aupd_token=aupd,
            profile_id=pid, save=save,
        )
        self.worker.log.connect(self.append_log)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_done(self, result):
        self._set_ui_enabled(True)
        if result.get("ok"):
            self.save_btn.setEnabled(True)
            if result.get("saved"):
                try:
                    from auth import dn_Auth
                    auth = dn_Auth()
                    if auth.load_session():
                        self.last_auth_obj = auth
                        QMessageBox.information(
                            self, "Готово",
                            f"✅ Сохранено.\n"
                            f"Школа: {result.get('school', '?')}"
                        )
                        self.tokens_saved.emit(auth)
                        self.accept()
                        return
                except Exception as e:
                    self.append_log(f"[!] {e}")
                QMessageBox.information(self, "Готово", "✅ Сохранено.")
            else:
                QMessageBox.information(
                    self, "Проверка успешна",
                    f"✅ Токен рабочий.\n"
                    f"Школа: {result.get('school', '?')}"
                )
        else:
            QMessageBox.warning(
                self, "Ошибка",
                result.get("reason", "Неизвестная ошибка")
            )

    def _set_ui_enabled(self, enabled):
        self.auth_token_edit.setEnabled(enabled)
        self.aupd_token_edit.setEnabled(enabled)
        self.profile_id_edit.setEnabled(enabled)
        self.check_btn.setEnabled(
            enabled and len(self.auth_token_edit.text().strip()) > 50
        )
        self.save_btn.setEnabled(enabled and bool(self.last_auth_obj))
        self.close_btn.setEnabled(enabled)


# ============================================================
# Диалог ЭЖД — импорт JSON
# ============================================================
class EJDImportDialog(_BaseImportDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔐  Импорт ЭЖД-сессии")
        self.setMinimumSize(780, 660)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # === Заголовок ===
        layout.addWidget(self._make_title("🔐  Импорт ЭЖД-сессии (JSON)"))
        layout.addWidget(self._make_subtitle(
            "Загрузка готового JSON-файла с токенами и cookies ЭЖД."
        ))

        # === Подсказка ===
        hint = self._make_hint(
            "Поддерживаются форматы:\n"
            "  • auth_data.json — auth_token, aupd_token, profile_id, school_id\n"
            "  • ejd_session.json / ejd_cookies.json — + cookies\n\n"
            "1. Откройте dnevnik.mos.ru и войдите.\n"
            "2. F12 → Console → скрипт zavuch2_ejd → Enter.\n"
            "3. Скачается файл.\n"
            "4. Ниже: «📋 Вставить из буфера» или «📁 Выбрать файл»."
        )
        layout.addWidget(hint)

        # === Поле JSON ===
        self.json_edit = QPlainTextEdit()
        self.json_edit.setPlaceholderText(
            '{"auth_token": "...", "profile_id": "...", "cookies": {...}}'
        )
        self.json_edit.setMinimumHeight(220)
        self.json_edit.setStyleSheet("""
            QPlainTextEdit {
                font-family: Consolas, "Courier New", monospace;
                font-size: 9.5pt;
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.json_edit)

        # === Кнопки ввода ===
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.paste_btn = QPushButton("📋  Вставить из буфера")
        self.paste_btn.setMinimumHeight(36)
        self.paste_btn.setStyleSheet(GHOST_BTN)
        self.paste_btn.clicked.connect(self._paste_from_clipboard)
        input_row.addWidget(self.paste_btn)

        self.load_file_btn = QPushButton("📁  Выбрать файл JSON")
        self.load_file_btn.setMinimumHeight(36)
        self.load_file_btn.clicked.connect(self._load_from_file)
        input_row.addWidget(self.load_file_btn)

        self.clear_btn = QPushButton("🗑  Очистить")
        self.clear_btn.setMinimumHeight(36)
        self.clear_btn.setStyleSheet(DANGER_BTN)
        self.clear_btn.clicked.connect(self.json_edit.clear)
        input_row.addWidget(self.clear_btn)

        input_row.addStretch()
        layout.addLayout(input_row)

        # === Кнопки действий ===
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()

        self.save_btn = QPushButton("💾  Проверить и сохранить")
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setMinimumWidth(260)
        self.save_btn.setStyleSheet(PRIMARY_EJD_BTN)
        self.save_btn.clicked.connect(self._start_worker)
        action_row.addWidget(self.save_btn)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumHeight(40)
        self.close_btn.setMinimumWidth(110)
        self.close_btn.clicked.connect(self.reject)
        action_row.addWidget(self.close_btn)
        layout.addLayout(action_row)

        # === Разделитель ===
        layout.addWidget(self._make_separator())

        # === Журнал ===
        log_title = QLabel("📋  Журнал")
        log_title.setStyleSheet(
            "font-size: 11pt; font-weight: 700; color: #0369a1;"
        )
        layout.addWidget(log_title)

        self.log_view = self._make_log_view()
        layout.addWidget(self.log_view, 1)

    def _paste_from_clipboard(self):
        text = get_from_clipboard()
        if text:
            self.json_edit.setPlainText(text)
            self.append_log(f"[clipboard] Вставлено {len(text)} символов")

    def _load_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите JSON",
            str(Path.home() / "Downloads"),
            "JSON files (*.json);;Все файлы (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось прочитать:\n{e}"
            )
            return

        if not isinstance(data, dict) or "auth_token" not in data:
            QMessageBox.warning(
                self, "Не тот файл", "Нет поля auth_token."
            )
            return

        self.json_edit.setPlainText(
            json.dumps(data, ensure_ascii=False, indent=2)
        )
        cookies_count = 0
        if isinstance(data.get("cookies"), dict):
            cookies_count = len(data["cookies"])
        else:
            SYSTEM = {"auth_token", "aupd_token", "profile_id",
                      "school_id", "saved_at", "source"}
            cookies_count = sum(
                1 for k, v in data.items()
                if k not in SYSTEM and not k.startswith("_")
                and isinstance(v, (str, int, float))
            )
        self.append_log(f"[+] Загружен файл: {path}")
        self.append_log(
            f"    auth_token: {'✅' if data.get('auth_token') else '❌'} | "
            f"profile_id: {'✅' if data.get('profile_id') else '—'} | "
            f"cookies: {cookies_count}"
        )

    def _start_worker(self):
        raw = self.json_edit.toPlainText().strip()
        if not raw:
            QMessageBox.warning(
                self, "Ошибка",
                "Вставьте JSON или выберите файл."
            )
            return
        self._set_ui_enabled(False)
        self.append_log("=" * 50)
        self.append_log("[i] Проверка и сохранение…")
        self.worker = EJDImportWorker(raw, save=True)
        self.worker.log.connect(self.append_log)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_done(self, result):
        self._set_ui_enabled(True)
        if result.get("ok") and result.get("saved"):
            QMessageBox.information(
                self, "Готово",
                f"✅ ЭЖД-сессия сохранена.\n\n"
                f"Школа: {result.get('school', '?')}"
            )
            try:
                from auth import dn_Auth
                auth = dn_Auth()
                if auth.load_session():
                    self.tokens_saved.emit(auth)
                    self.accept()
                    return
            except Exception as e:
                self.append_log(f"[!] {e}")
            self.tokens_saved.emit({
                "saved": True,
                "school": result.get("school", ""),
            })
            self.accept()
            return

        if result.get("ok") and not result.get("saved"):
            reason = result.get("reason", "причина неизвестна")
            QMessageBox.warning(
                self, "Не удалось сохранить",
                f"✅ Токен рабочий, но сохранить не удалось.\n\n"
                f"Причина: {reason}\n\n"
                "Проверьте:\n"
                "• Закрыто ли главное окно zavuch 2\n"
                "• Не запущено ли несколько копий приложения\n"
                "• Есть ли права на запись в sessions/"
            )
            return

        QMessageBox.warning(
            self, "Ошибка импорта",
            f"{result.get('reason', 'Неизвестная ошибка')}"
        )

    def _set_ui_enabled(self, enabled):
        self.paste_btn.setEnabled(enabled)
        self.load_file_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.close_btn.setEnabled(enabled)


# ============================================================
# Диалог ПДОУ
# ============================================================
class PDOUImportDialog(_BaseImportDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨  Импорт ПДОУ-сессии")
        self.setMinimumSize(780, 660)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # === Заголовок ===
        layout.addWidget(self._make_title("🎨  Импорт ПДОУ-сессии (JSON)"))
        layout.addWidget(self._make_subtitle(
            "Загрузка готового JSON-файла с токенами ПДОУ."
        ))

        # === Подсказка ===
        hint = self._make_hint(
            "1. Откройте esz.mos.ru и войдите в ПДОУ.\n"
            "2. F12 → Console → скрипт zavuch2 → Enter.\n"
            "3. Скачается pdou_session.json.\n"
            "4. Если в нём нет Ltpatoken2 / session-cookie —\n"
            "   добавьте их значения из DevTools → Application → Cookies.\n"
            "5. Ниже: «📋 Вставить из буфера» или «📁 Выбрать файл»."
        )
        layout.addWidget(hint)

        # === Поле JSON ===
        self.json_edit = QPlainTextEdit()
        self.json_edit.setPlaceholderText(
            '{"aupd_token": "...", "esztoken": "...", "cookies": {...}}'
        )
        self.json_edit.setMinimumHeight(220)
        self.json_edit.setStyleSheet("""
            QPlainTextEdit {
                font-family: Consolas, "Courier New", monospace;
                font-size: 9.5pt;
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.json_edit)

        # === Кнопки ввода ===
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.paste_btn = QPushButton("📋  Вставить из буфера")
        self.paste_btn.setMinimumHeight(36)
        self.paste_btn.setStyleSheet(GHOST_PDOU_BTN)
        self.paste_btn.clicked.connect(self._paste_from_clipboard)
        input_row.addWidget(self.paste_btn)

        self.load_file_btn = QPushButton("📁  Выбрать файл pdou_session.json")
        self.load_file_btn.setMinimumHeight(36)
        self.load_file_btn.clicked.connect(self._load_from_file)
        input_row.addWidget(self.load_file_btn)

        self.clear_btn = QPushButton("🗑  Очистить")
        self.clear_btn.setMinimumHeight(36)
        self.clear_btn.setStyleSheet(DANGER_BTN)
        self.clear_btn.clicked.connect(self.json_edit.clear)
        input_row.addWidget(self.clear_btn)

        input_row.addStretch()
        layout.addLayout(input_row)

        # === Кнопки действий ===
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()

        self.save_btn = QPushButton("💾  Проверить и сохранить")
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setMinimumWidth(260)
        self.save_btn.setStyleSheet(PRIMARY_PDOU_BTN)
        self.save_btn.clicked.connect(self._start_worker)
        action_row.addWidget(self.save_btn)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumHeight(40)
        self.close_btn.setMinimumWidth(110)
        self.close_btn.clicked.connect(self.reject)
        action_row.addWidget(self.close_btn)
        layout.addLayout(action_row)

        # === Разделитель ===
        layout.addWidget(self._make_separator())

        # === Журнал ===
        log_title = QLabel("📋  Журнал")
        log_title.setStyleSheet(
            "font-size: 11pt; font-weight: 700; color: #6d28d9;"
        )
        layout.addWidget(log_title)

        self.log_view = self._make_log_view()
        layout.addWidget(self.log_view, 1)

    def _paste_from_clipboard(self):
        text = get_from_clipboard()
        if text:
            self.json_edit.setPlainText(text)
            self.append_log(f"[clipboard] Вставлено {len(text)} символов")

    def _load_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите pdou_session.json",
            str(Path.home() / "Downloads"),
            "JSON files (*.json);;Все файлы (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось прочитать:\n{e}"
            )
            return

        if not isinstance(data, dict) or "aupd_token" not in data:
            QMessageBox.warning(
                self, "Не тот файл",
                "Нет полей aupd_token / esztoken."
            )
            return

        self.json_edit.setPlainText(
            json.dumps(data, ensure_ascii=False, indent=2)
        )
        ltpa = "✅" if data.get("cookies", {}).get("Ltpatoken2") else "❌"
        session = "✅" if data.get("cookies", {}).get("session-cookie") else "❌"
        self.append_log(f"[+] Загружен файл: {path}")
        self.append_log(f"    Ltpatoken2: {ltpa} | session-cookie: {session}")

    def _start_worker(self):
        raw = self.json_edit.toPlainText().strip()
        if not raw:
            QMessageBox.warning(
                self, "Ошибка",
                "Вставьте JSON или выберите файл."
            )
            return
        self._set_ui_enabled(False)
        self.append_log("=" * 50)
        self.append_log("[i] Проверка и сохранение…")
        self.worker = PDOUImportWorker(raw, save=True)
        self.worker.log.connect(self.append_log)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_done(self, result):
        self._set_ui_enabled(True)
        if result.get("ok") and result.get("saved"):
            user_name = result.get("user_name", "") or "неизвестен"
            roles = result.get("roles", []) or []
            roles_text = (
                "\n".join(f"• {r}" for r in roles) if roles else "(нет)"
            )
            QMessageBox.information(
                self, "Готово",
                f"✅ ПДОУ-сессия сохранена.\n\n"
                f"Пользователь: {user_name}\n\n"
                f"Роли ЕСЗ:\n{roles_text}"
            )
            self.tokens_saved.emit({
                "user_name": user_name,
                "roles": roles,
                "saved": True,
            })
            self.accept()
            return

        if result.get("ok") and not result.get("saved"):
            QMessageBox.information(
                self, "Проверка успешна",
                "✅ Токены рабочие, но сохранение не выполнялось."
            )
            return

        QMessageBox.warning(
            self, "Ошибка импорта ПДОУ-сессии",
            f"{result.get('reason', 'Неизвестная ошибка')}"
        )

    def _set_ui_enabled(self, enabled):
        self.paste_btn.setEnabled(enabled)
        self.load_file_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.close_btn.setEnabled(enabled)