# -*- coding: utf-8 -*-
"""
GUI-приложение для авторизации в ЭЖД МЭШ.
PySide6 + Selenium + webdriver-manager.
Сохраняет логин, пароль и TOTP-ключ между запусками.
"""
import sys
import io

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QMessageBox,
    QPlainTextEdit, QComboBox, QCheckBox
)

from auth_worker import (
    AuthWorker,
    load_credentials,
    save_credentials,
    clear_credentials,
)


# --- Построчная буферизация stdout (для PyCharm) ---
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
except Exception:
    pass


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭЖД МЭШ — Авторизация")
        self.setMinimumSize(600, 660)

        self.worker = None
        self._build_ui()
        self._load_saved_credentials()

    # ------------------------------------------------------------------
    def _build_ui(self):
        title = QLabel("Вход в ЭЖД МЭШ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 8px;")

        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Логин (телефон, email или СНИЛС)")
        self.login_edit.setMinimumHeight(32)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(32)

        self.totp_edit = QLineEdit()
        self.totp_edit.setPlaceholderText(
            "TOTP-ключ (Base32; если пусто — код из СМС вводится вручную)"
        )
        self.totp_edit.setMinimumHeight(32)

        self.show_password_cb = QCheckBox("Показывать пароль")
        self.show_password_cb.stateChanged.connect(self._toggle_password_echo)

        self.remember_cb = QCheckBox("Запомнить логин, пароль и TOTP-ключ")
        self.remember_cb.setChecked(True)

        browser_label = QLabel("Браузер:")
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["chrome", "firefox"])
        self.browser_combo.setMinimumHeight(28)

        browser_row = QHBoxLayout()
        browser_row.addWidget(browser_label)
        browser_row.addWidget(self.browser_combo)
        browser_row.addStretch()

        self.login_btn = QPushButton("Войти")
        self.login_btn.setMinimumHeight(38)
        self.login_btn.clicked.connect(self.on_login_clicked)

        self.clear_btn = QPushButton("Очистить сохранённые данные")
        self.clear_btn.setMinimumHeight(28)
        self.clear_btn.clicked.connect(self.on_clear_clicked)

        self.status_label = QLabel("Готов к работе")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #666; padding: 4px;")

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)

        log_label = QLabel("Журнал:")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 11px;"
            "background-color: #1e1e1e; color: #d4d4d4;"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(8)

        layout.addWidget(title)
        layout.addWidget(self.login_edit)
        layout.addWidget(self.password_edit)
        layout.addWidget(self.totp_edit)
        layout.addWidget(self.show_password_cb)
        layout.addWidget(self.remember_cb)
        layout.addLayout(browser_row)
        layout.addWidget(self.login_btn)
        layout.addWidget(self.clear_btn)
        layout.addWidget(line)
        layout.addWidget(self.status_label)
        layout.addWidget(log_label)
        layout.addWidget(self.log_view, stretch=1)

        self.setLayout(layout)

    # ------------------------------------------------------------------
    def _toggle_password_echo(self, state):
        if state == Qt.Checked:
            self.password_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)

    # ------------------------------------------------------------------
    def _load_saved_credentials(self):
        creds = load_credentials()
        if not creds:
            return
        self.login_edit.setText(creds.get("login", ""))
        self.password_edit.setText(creds.get("password", ""))
        self.totp_edit.setText(creds.get("totp_key", ""))
        if creds.get("login"):
            self.append_log(f"[i] Загружены сохранённые данные для: {creds['login']}")

    # ------------------------------------------------------------------
    def append_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    def on_clear_clicked(self):
        answer = QMessageBox.question(
            self,
            "Подтверждение",
            "Удалить сохранённые логин, пароль и TOTP-ключ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            clear_credentials()
            self.login_edit.clear()
            self.password_edit.clear()
            self.totp_edit.clear()
            self.status_label.setText("Сохранённые данные удалены")
            self.status_label.setStyleSheet("color: #666;")

    # ------------------------------------------------------------------
    def on_login_clicked(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        totp_key = self.totp_edit.text().strip() or None
        browser = self.browser_combo.currentText()

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль.")
            return

        if self.remember_cb.isChecked():
            save_credentials(login, password, totp_key or "")

        self._set_ui_enabled(False)
        self.status_label.setText("Выполняется вход, подождите...")
        self.status_label.setStyleSheet("color: #0066cc; font-weight: bold;")
        self.log_view.clear()

        self.worker = AuthWorker(
            login, password,
            totp_key=totp_key,
            browser=browser,
        )
        self.worker.finished_ok.connect(self.on_success)
        self.worker.finished_err.connect(self.on_error)
        self.worker.log.connect(self.append_log)
        self.worker.start()

    # ------------------------------------------------------------------
    def on_success(self, message: str):
        self.status_label.setText("✅ Вы вошли!")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        self._set_ui_enabled(True)
        QMessageBox.information(self, "Успех", message)

    # ------------------------------------------------------------------
    def on_error(self, message: str):
        self.status_label.setText("❌ Ошибка входа")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self._set_ui_enabled(True)
        QMessageBox.critical(self, "Ошибка", message)

    # ------------------------------------------------------------------
    def _set_ui_enabled(self, enabled: bool):
        self.login_btn.setEnabled(enabled)
        self.login_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.totp_edit.setEnabled(enabled)
        self.browser_combo.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)


# ============================================================
def main():
    app = QApplication(sys.argv)
    window = LoginWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()