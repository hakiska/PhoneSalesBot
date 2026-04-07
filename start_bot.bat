@echo off
chcp 65001 >/dev/null 2>/dev/null
echo ========================================
echo    Bot prodazh zapchastey telefonov
echo ========================================
echo.

python --version >/dev/null 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [!] Python ne ustanovlen!
    echo Skachay: https://www.python.org/downloads/
    echo Pri ustanovke postavi galochku Add Python to PATH
    echo.
    pause
    exit /b
)

echo Ustanovka bibliotek...
pip install -r requirements.txt >/dev/null 2>&1
echo Gotovo!
echo.
echo Bot zapushen! Ne zakryvay eto okno.
echo Dlya ostanovki nazmi Ctrl+C
echo ========================================
echo.

python bot.py

pause
