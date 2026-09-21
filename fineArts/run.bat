@echo off
setlocal

REM ============================================================
REM FineArts certificate query system - start server
REM Frontend : http://127.0.0.1:5000/
REM Admin    : http://127.0.0.1:5000/admin  (admin / admin123)
REM ============================================================

cd /d "%~dp0"

set "PYTHON=d:\_code\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -c "import flask, flask_login, flask_sqlalchemy, PIL, openpyxl, pymysql, dotenv" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
)

echo.
echo Starting server... press Ctrl+C to stop.
echo.
"%PYTHON%" run.py
pause
