# -*- coding: utf-8 -*-
"""
Диалог импорта токенов в ~/.zavuch2/.

Позволяет вставить auth_token + aupd_token (и опционально profile_id),
проверить через API dnevnik.mos.ru и сохранить как session.pkl + auth_data.json.
"""
import base64
import datetime
import json
import pickle
import time
from pathlib import Path

import requests

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QPlainTextEdit, QMessageBox, QFrame,
    QFormLayout, QGroupBox
)


DATA_DIR = Path.home() / ".zavuch2"
DATA_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session.pkl"
AUTH_DATA_FILE = DATA_DIR / "auth_data.json"


# ============================================================
#  Утилиты
# ============================================================
def decode_jwt_payload(token: str) -> dict:
    """Декодирует payload JWT без проверки подписи (только для чтения)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
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


# ============================================================
#  Поток проверки/сохранения токена
# ============================================================
class TokenCheckWorker(QThread):
    """
    Проверяет токен через API и, если ok=True, сохраняет в ~/.zavuch2/.
    Сохраняем только при save=True.
    """
    log = Signal(str)
    done = Signal(dict)   # {"ok": bool, "school": str, "reason": str, "saved": bool}

    def __init__(self, auth_token: str, aupd_token: str = "",
                 profile_id: str = "", save: bool = False):
        super().__init__()
        self.auth_token = auth_token
        self.aupd_token = aupd_token or auth_token
        self.profile_id = profile_id or ""
        self.save = save

    def _log(self, msg):
        self.log.emit(msg)

    def run(self):
        result = {"ok": False, "school": "", "reason": "", "saved": False}

        # 1. Декодируем JWT
        payload = decode_jwt_payload(self.auth_token)
        if payload:
            self._log("[i] Payload auth_token:")
            for k in ("sub", "iss", "exp", "iat", "ath"):
                if k in payload:
                    if k == "exp":
                        try:
                            dt = datetime.datetime.fromtimestamp(payload[k])
                            self._log(f"    {k} = {payload[k]} → {dt.strftime('%d.%m.%Y %H:%M:%S')}")
                        except Exception:
                            self._log(f"    {k} = {payload[k]}")
                    else:
                        self._log(f"    {k} = {payload[k]}")
        else:
            self._log("[!] Не удалось декодировать auth_token как JWT")

        # 2. Запрос к API
        self._log("[i] Проверяю через API dnevnik.mos.ru…")

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/152.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Auth-Token": self.auth_token,
            "Authorization": f"Bearer {self.auth_token}",
        })
        if self.profile_id:
            session.headers["Profile-Id"] = str(self.profile_id)

        # Пробуем старые cookies, если есть
        old_cookies = {}
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, "rb") as f:
                    cj = pickle.load(f)
                old_cookies = requests.utils.dict_from_cookiejar(cj)
            except Exception:
                pass

        for name, value in old_cookies.items():
            session.cookies.set(name, value, domain="dnevnik.mos.ru")
            session.cookies.set(name, value, domain="school.mos.ru")
        session.cookies.set("auth_token", self.auth_token, domain="dnevnik.mos.ru")
        session.cookies.set("auth_token", self.auth_token, domain="school.mos.ru")
        if self.aupd_token:
            session.cookies.set("aupd_token", self.aupd_token, domain="dnevnik.mos.ru")
            session.cookies.set("aupd_token", self.aupd_token, domain="school.mos.ru")
        if self.profile_id:
            session.cookies.set("profile_id", str(self.profile_id), domain="dnevnik.mos.ru")

        try:
            r = session.get("https://dnevnik.mos.ru/core/api/schools", timeout=15)
        except Exception as e:
            self._log(f"[!] Ошибка запроса: {e}")
            result["reason"] = f"Ошибка сети: {e}"
            self.done.emit(result)
            return

        self._log(f"[i] HTTP {r.status_code}")

        if r.status_code != 200:
            self._log(f"[!] Тело: {r.text[:200]}")
            result["reason"] = f"API вернул HTTP {r.status_code}"
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

        # 3. Сохранение
        if self.save:
            try:
                with open(SESSION_FILE, "wb") as f:
                    pickle.dump(session.cookies, f)
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
#  Диалог импорта токенов
# ============================================================
class TokenImportDialog(QDialog):
    """
    Диалог импорта токенов.

    Сигнал tokens_saved(auth_obj) — испускается после успешного сохранения,
    чтобы AuthWindow мог открыть MainWindow.
    """
    tokens_saved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 Импорт токенов в ~/.zavuch2/")
        self.setMinimumSize(720, 620)
        self.worker = None
        self.last_auth_obj = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # Заголовок + инструкция
        title = QLabel("📋 Импорт токенов")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        hint = QLabel(
            "Откройте Chrome DevTools (F12) на вкладке dnevnik.mos.ru:\n"
            "Application → Cookies → https://dnevnik.mos.ru\n"
            "Скопируйте значения полей auth_token и (опционально) aupd_token.\n"
            "Поле profile_id — если оно есть в cookies (иначе оставьте пустым)."
        )
        hint.setStyleSheet("color: #555; font-size: 9pt; background-color: #f5f5f5; "
                           "padding: 8px; border-radius: 5px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # === Поля ввода ===
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # auth_token
        self.auth_token_edit = QLineEdit()
        self.auth_token_edit.setPlaceholderText("Вставьте auth_token (JWT, длинная строка)")
        self.auth_token_edit.setMinimumHeight(34)
        self.auth_token_edit.textChanged.connect(self._on_token_changed)
        auth_row = QHBoxLayout()
        auth_row.addWidget(self.auth_token_edit, 1)
        self.paste_auth_btn = QPushButton("📋 Из буфера")
        self.paste_auth_btn.setMaximumWidth(130)
        self.paste_auth_btn.clicked.connect(
            lambda: self._paste_into(self.auth_token_edit)
        )
        auth_row.addWidget(self.paste_auth_btn)
        form.addRow("auth_token:", auth_row)

        # aupd_token
        self.aupd_token_edit = QLineEdit()
        self.aupd_token_edit.setPlaceholderText(
            "aupd_token (необязательно, если совпадает с auth_token)"
        )
        self.aupd_token_edit.setMinimumHeight(34)
        aupd_row = QHBoxLayout()
        aupd_row.addWidget(self.aupd_token_edit, 1)
        self.paste_aupd_btn = QPushButton("📋 Из буфера")
        self.paste_aupd_btn.setMaximumWidth(130)
        self.paste_aupd_btn.clicked.connect(
            lambda: self._paste_into(self.aupd_token_edit)
        )
        aupd_row.addWidget(self.paste_aupd_btn)
        form.addRow("aupd_token:", aupd_row)

        # profile_id
        self.profile_id_edit = QLineEdit()
        self.profile_id_edit.setPlaceholderText(
            "profile_id (опционально; можно найти в cookies)"
        )
        self.profile_id_edit.setMinimumHeight(34)
        pid_row = QHBoxLayout()
        pid_row.addWidget(self.profile_id_edit, 1)
        self.paste_pid_btn = QPushButton("📋 Из буфера")
        self.paste_pid_btn.setMaximumWidth(130)
        self.paste_pid_btn.clicked.connect(
            lambda: self._paste_into(self.profile_id_edit)
        )
        pid_row.addWidget(self.paste_pid_btn)
        form.addRow("profile_id:", pid_row)

        layout.addLayout(form)

        # === Кнопки ===
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.check_btn = QPushButton("🔍 Проверить")
        self.check_btn.setMinimumHeight(36)
        self.check_btn.setMinimumWidth(150)
        self.check_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb; color: white; font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        self.check_btn.clicked.connect(lambda: self._start_worker(save=False))
        btn_row.addWidget(self.check_btn)

        self.save_btn = QPushButton("💾 Сохранить")
        self.save_btn.setMinimumHeight(36)
        self.save_btn.setMinimumWidth(150)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: white; font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        self.save_btn.clicked.connect(lambda: self._start_worker(save=True))
        btn_row.addWidget(self.save_btn)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumHeight(36)
        self.close_btn.setMinimumWidth(100)
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

        # === Журнал ===
        log_label = QLabel("Журнал:")
        layout.addWidget(log_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 10px; "
            "background-color: #1e1e1e; color: #d4d4d4;"
        )
        layout.addWidget(self.log_view, 1)

    # ------------------------------------------------------------------
    def _paste_into(self, line_edit: QLineEdit):
        text = get_from_clipboard()
        if text:
            line_edit.setText(text)
            self.append_log(f"[clipboard] Вставлено {len(text)} символов")
        else:
            self.append_log("[clipboard] Буфер обмена пуст")

    def _on_token_changed(self, text):
        # Как только появился auth_token — активируем кнопку «Проверить»
        has_token = bool(text.strip()) and len(text.strip()) > 50
        self.check_btn.setEnabled(has_token)
        # Сбрасываем «Сохранить» — надо перепроверить
        self.save_btn.setEnabled(False)

    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    def _start_worker(self, save: bool):
        auth_token = self.auth_token_edit.text().strip()
        if not auth_token:
            QMessageBox.warning(self, "Ошибка", "Поле auth_token пустое.")
            return

        if len(auth_token) < 50:
            QMessageBox.warning(
                self, "Ошибка",
                "auth_token слишком короткий — это точно не JWT.\n"
                "Скопируйте значение полностью."
            )
            return

        aupd = self.aupd_token_edit.text().strip() or auth_token
        pid = self.profile_id_edit.text().strip()

        self._set_ui_enabled(False)
        self.append_log("")
        self.append_log("=" * 50)
        self.append_log(f"[i] {'Сохранение' if save else 'Проверка'} токена…")

        self.worker = TokenCheckWorker(
            auth_token=auth_token,
            aupd_token=aupd,
            profile_id=pid,
            save=save,
        )
        self.worker.log.connect(self.append_log)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_done(self, result: dict):
        self._set_ui_enabled(True)

        if result.get("ok"):
            # Токен валиден — можно сохранять (даже если только что проверяли)
            self.save_btn.setEnabled(True)

            if result.get("saved"):
                # Загружаем только что сохранённую сессию
                try:
                    from auth import dn_Auth
                    auth = dn_Auth()
                    if auth.load_session():
                        self.last_auth_obj = auth
                        QMessageBox.information(
                            self, "Готово",
                            f"✅ Токен сохранён и сессия активна.\n\n"
                            f"Школа: {result.get('school', '?')}"
                        )
                        self.tokens_saved.emit(auth)
                        self.accept()
                        return
                except Exception as e:
                    self.append_log(f"[!] Не удалось загрузить сессию: {e}")

                QMessageBox.information(
                    self, "Готово",
                    "✅ Токен сохранён.\n\nНажмите «📂 Войти используя имеющиеся данные» "
                    "на экране входа, чтобы активировать."
                )
            else:
                QMessageBox.information(
                    self, "Проверка успешна",
                    f"✅ Токен рабочий.\n\nШкола: {result.get('school', '?')}\n\n"
                    "Нажмите «💾 Сохранить», чтобы применить."
                )
        else:
            QMessageBox.warning(
                self, "Проверка не удалась",
                result.get("reason", "Неизвестная ошибка") +
                "\n\nПроверьте, что скопированы оба токена полностью."
            )

    def _set_ui_enabled(self, enabled: bool):
        self.auth_token_edit.setEnabled(enabled)
        self.aupd_token_edit.setEnabled(enabled)
        self.profile_id_edit.setEnabled(enabled)
        self.paste_auth_btn.setEnabled(enabled)
        self.paste_aupd_btn.setEnabled(enabled)
        self.paste_pid_btn.setEnabled(enabled)
        self.check_btn.setEnabled(enabled and
                                  len(self.auth_token_edit.text().strip()) > 50)
        self.save_btn.setEnabled(enabled and bool(self.last_auth_obj))
        self.close_btn.setEnabled(enabled)