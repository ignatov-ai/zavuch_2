@echo off
REM --- Закрываем все окна Chrome (важно!) ---
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 2 /nobreak >nul

REM --- Путь к Chrome: подкорректируйте под себя, если он в другом месте ---
set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% (
    set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

REM --- Отдельный профиль для отладки (чтобы не мешать основному) ---
set PROFILE_DIR=%USERPROFILE%\ChromeDebugProfile

REM --- Запуск Chrome в режиме отладки ---
start "" %CHROME% --remote-debugging-port=9222 --user-data-dir="%PROFILE_DIR%" https://school.mos.ru/

echo.
echo Chrome запущен в режиме отладки на порту 9222.
echo Войдите на school.mos.ru, затем вернитесь в token_monitor.py.
pause