# -*- coding: utf-8 -*-
"""
Монитор токена МЭШ — подключается к уже открытому Chrome (в режиме отладки).

Схема работы:
1) Вы запускаете Chrome через start_chrome_debug.bat (порт 9222).
2) Входите на school.mos.ru вручную, ходите по сайту.
3) Запускаете этот скрипт → он подключается к Chrome и в фоне
   раз в 2 секунды проверяет localStorage / sessionStorage / cookies.
4) Как только находит auth_token — сохраняет его в ~/.ejd_checker/auth_data.json.
"""
import sys
import io
import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QMessageBox, QPlainTextEdit, QLineEdit,
)


# --- Буферизация вывода (для PyCharm) ---
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
except Exception:
    pass

DATA_DIR = Path.home() / ".ejd_checker"
DATA_DIR.mkdir(exist_ok=True)
AUTH_FILE = DATA_DIR / "auth_data.json"
COOKIES_FILE = DATA_DIR / "cookies_monitor.json"


# ============================================================
#  Поток мониторинга
# ============================================================
class MonitorWorker(QThread):
    log = Signal(str)
    found = Signal(str)
    cookies_found = Signal(dict)

    TOKEN_KEYS = [
        "auth_token", "token", "access_token", "authToken",
        "ACCESS_TOKEN", "AUTH_TOKEN",
    ]
    IMPORTANT_COOKIES = [
        "auth_token", "aupd_token", "Ltpatoken2", "mos_id",
        "session-cookie", "obr_id", "user_login", "ghur", "sbp_sid",
    ]

    def __init__(self, driver, interval_sec: float = 2.0):
        super().__init__()
        self.driver = driver
        self.interval = interval_sec
        self._stop = False

    def stop(self):
        self._stop = True

    # ------------------------------------------------------------------
    def _js_get(self, script: str):
        try:
            return self.driver.execute_script(script)
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _extract_token(self):
        # 1. sessionStorage
        for key in self.TOKEN_KEYS:
            val = self._js_get(f"return window.sessionStorage.getItem('{key}');")
            if val:
                return val, f"sessionStorage['{key}']"
        # 2. localStorage
        for key in self.TOKEN_KEYS:
            val = self._js_get(f"return window.localStorage.getItem('{key}');")
            if val:
                return val, f"localStorage['{key}']"
        # 3. перебор ключей (вдруг под другим именем)
        for storage in ("localStorage", "sessionStorage"):
            keys = self._js_get(f"return Object.keys(window.{storage});") or []
            for k in keys:
                low = k.lower()
                if any(x in low for x in ("token", "auth", "access", "jwt")):
                    val = self._js_get(f"return window.{storage}.getItem('{k}');")
                    if val and len(val) > 20:
                        return val, f"{storage}['{k}']"
        # 4. cookies
        try:
            for c in self.driver.get_cookies():
                if c["name"] in self.TOKEN_KEYS:
                    return c["value"], f"cookie['{c['name']}']"
        except Exception:
            pass
        return None, None

    # ------------------------------------------------------------------
    def _collect_cookies(self):
        try:
            return {c["name"]: c["value"] for c in self.driver.get_cookies()}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    def run(self):
        self.log.emit("[i] Мониторинг запущен. Ходите по school.mos.ru.")
        self.log.emit(f"[i] Интервал: {self.interval} сек.")

        token_saved = False
        cookies_saved = False
        last_url = None

        while not self._stop:
            try:
                url = self.driver.current_url
                if url != last_url:
                    self.log.emit(f"[i] URL: {url}")
                    last_url = url
            except Exception:
                self.log.emit("[!] Потеряна связь с Chrome. Возможно, он закрыт.")
                break

            # --- токен ---
            if not token_saved:
                token, where = self._extract_token()
                if token:
                    self.log.emit(f"[+] Токен найден ({where}): {token[:40]}...")
                    try:
                        with open(AUTH_FILE, "w", encoding="utf-8") as f:
                            json.dump({"auth_token": token, "source": where},
                                      f, ensure_ascii=False, indent=2)
                        self.log.emit(f"[+] Сохранено: {AUTH_FILE}")
                    except Exception as e:
                        self.log.emit(f"[!] Не сохранилось: {e}")
                    self.found.emit(token)
                    token_saved = True

            # --- куки ---
            if not cookies_saved:
                cookies = self._collect_cookies()
                if cookies:
                    try:
                        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                            json.dump(cookies, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    important = {k: v for k, v in cookies.items()
                                 if k in self.IMPORTANT_COOKIES}
                    if important:
                        self.log.emit("[+] Важные куки:")
                        for k, v in important.items():
                            self.log.emit(f"    - {k} = {v[:40]}...")
                    self.cookies_found.emit(cookies)
                    cookies_saved = True

            if token_saved and cookies_saved:
                self.log.emit("[+] Всё найдено. Мониторинг можно остановить.")
                break

            slept = 0.0
            while slept < self.interval and not self._stop:
                time.sleep(0.2)
                slept += 0.2

        self.log.emit("[i] Мониторинг остановлен.")


# ============================================================
#  GUI
# ============================================================
class TokenMonitorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Монитор токена (подключение к Chrome)")
        self.setMinimumSize(720, 520)

        self.driver = None
        self.worker = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        title = QLabel("Монитор токена МЭШ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin: 6px;")

        hint = QLabel(
            "Порядок работы:\n"
            "1) Закройте ВСЕ окна Chrome.\n"
            "2) Запустите start_chrome_debug.bat (порт 9222).\n"
            "3) В этом Chrome войдите на school.mos.ru (логин, пароль, SMS).\n"
            "4) Вернитесь сюда и нажмите «Подключиться к Chrome».\n"
            "5) Затем — «Начать мониторинг». Ходите по сайту, скрипт сам найдёт токен."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #444; padding: 4px;")

        # --- Адрес отладки ---
        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel("Адрес отладки:"))
        self.addr_edit = QLineEdit("127.0.0.1:9222")
        addr_row.addWidget(self.addr_edit, stretch=1)
        addr_row.addWidget(QLabel("Интервал, сек:"))
        self.interval_edit = QLineEdit("2.0")
        self.interval_edit.setFixedWidth(60)
        addr_row.addWidget(self.interval_edit)

        # --- Кнопки ---
        self.connect_btn = QPushButton("Подключиться к Chrome")
        self.connect_btn.clicked.connect(self.on_connect)
        self.connect_btn.setMinimumHeight(36)

        self.start_btn = QPushButton("Начать мониторинг")
        self.start_btn.clicked.connect(self.on_start_monitor)
        self.start_btn.setEnabled(False)
        self.start_btn.setMinimumHeight(36)

        self.stop_btn = QPushButton("Остановить мониторинг")
        self.stop_btn.clicked.connect(self.on_stop_monitor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(36)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        # --- Статус ---
        self.status = QLabel("Готов к работе")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #666; padding: 4px;")

        # --- Лог ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
            "background-color: #1e1e1e; color: #d4d4d4;"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(addr_row)
        layout.addLayout(btn_row)
        layout.addWidget(self.status)
        layout.addWidget(self.log_view, stretch=1)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    def on_connect(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        addr = self.addr_edit.text().strip() or "127.0.0.1:9222"

        try:
            options = Options()
            options.add_experimental_option("debuggerAddress", addr)
            self.driver = webdriver.Chrome(options=options)

            # Проверяем связь
            url = self.driver.current_url
            self.append_log(f"[+] Подключено к Chrome: {addr}")
            self.append_log(f"[i] Текущий URL: {url}")

            self.status.setText("Подключено к Chrome")
            self.status.setStyleSheet("color: green; font-weight: bold;")
            self.start_btn.setEnabled(True)

        except Exception as e:
            self.append_log(f"[!] Не удалось подключиться: {e}")
            self.status.setText("Ошибка подключения")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.critical(
                self, "Ошибка подключения",
                "Не удалось подключиться к Chrome.\n\n"
                "Убедитесь, что:\n"
                "1) Все окна Chrome закрыты.\n"
                "2) Chrome запущен через start_chrome_debug.bat.\n"
                "3) Порт совпадает (9222).\n\n"
                f"Техническая ошибка:\n{e}"
            )

    # ------------------------------------------------------------------
    def on_start_monitor(self):
        if not self.driver:
            QMessageBox.warning(self, "Нет подключения",
                                "Сначала нажмите «Подключиться к Chrome».")
            return

        try:
            interval = float(self.interval_edit.text().replace(",", "."))
        except ValueError:
            interval = 2.0

        self.worker = MonitorWorker(self.driver, interval_sec=interval)
        self.worker.log.connect(self.append_log)
        self.worker.found.connect(self.on_token_found)
        self.worker.cookies_found.connect(self.on_cookies_found)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Мониторинг идёт. Ходите по сайту.")
        self.status.setStyleSheet("color: #0066cc; font-weight: bold;")

    # ------------------------------------------------------------------
    def on_stop_monitor(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText("Мониторинг остановлен.")
        self.status.setStyleSheet("color: #666;")

    # ------------------------------------------------------------------
    def on_token_found(self, token: str):
        self.status.setText("✅ Токен найден и сохранён!")
        self.status.setStyleSheet("color: green; font-weight: bold;")
        self.append_log(f"[+] Токен: {token[:60]}...")
        QMessageBox.information(
            self, "Готово",
            f"Токен сохранён в:\n{AUTH_FILE}\n\n"
            "Теперь его можно использовать в основном приложении."
        )

    # ------------------------------------------------------------------
    def on_cookies_found(self, cookies: dict):
        self.append_log(f"[+] Сохранено куки: {len(cookies)} шт. → {COOKIES_FILE}")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self.on_stop_monitor()
        event.accept()


# ============================================================
def main():
    app = QApplication(sys.argv)
    w = TokenMonitorWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()