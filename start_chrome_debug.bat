@echo off
REM Запуск Chrome с отладочным портом для монитора сессии zavuch 2
REM ВАЖНО: предварительно закройте все окна обычного Chrome!

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_PATH% (
    set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

if not exist %CHROME_PATH% (
    echo [ОШИБКА] Chrome не найден по стандартным путям.
    echo Откройте start_chrome_debug.bat и укажите путь вручную.
    pause
    exit /b 1
)

echo Запускаю Chrome с отладочным портом 9222...
echo Профиль: C:\chrome_debug_profile
echo.
start "" %CHROME_PATH% --remote-debugging-port=9222 --user-data-dir="C:\chrome_debug_profile"