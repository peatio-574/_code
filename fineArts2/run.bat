@echo off
setlocal

REM ============================================================
REM FineArts2 signup system - start server
REM Frontend : http://127.0.0.1:5001/new/apply
REM Admin    : http://127.0.0.1:5001/new/manager  (admin / Caa@Admin2026)
REM ============================================================

cd /d "%~dp0"

set "PYTHON=d:\_code\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -c "import flask, flask_login, flask_sqlalchemy, PIL, openpyxl, pymysql, dotenv, qrcode" >nul 2>nul
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
