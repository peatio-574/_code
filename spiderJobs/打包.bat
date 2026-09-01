@echo off
chcp 936 >nul
setlocal enabledelayedexpansion

set "APP_NAME=guopin_spider"
set "ENTRY=getJobs.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "SPEC_FILE=%APP_NAME%.spec"

set "PYTHON=d:\_code\python\python.exe"

cd /d "%~dp0"

echo.
echo [1/5] Checking Python...
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)
"%PYTHON%" --version

echo.
echo [2/5] Checking PyInstaller...
"%PYTHON%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    "%PYTHON%" -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed.
        pause
        exit /b 1
    )
) else (
    echo PyInstaller OK.
)

echo.
echo [3/5] Checking dependencies...
"%PYTHON%" -c "import requests, openpyxl, tkinter" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    "%PYTHON%" -m pip install requests openpyxl -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
    echo Dependencies OK.
)

echo.
echo [4/5] Cleaning old files...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%SPEC_FILE%" del /f /q "%SPEC_FILE%"

echo.
echo [5/5] Building...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --paths "." ^
    --paths ".." ^
    --hidden-import "Logger" ^
    --hidden-import "requests" ^
    --hidden-import "openpyxl" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --exclude-module "pandas" ^
    --exclude-module "numpy" ^
    --exclude-module "scipy" ^
    --exclude-module "matplotlib" ^
    --exclude-module "ReadFile" ^
    --add-data "data.json;." ^
    "%ENTRY%"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [DONE] Build success!
echo EXE: %cd%\%DIST_DIR%\%APP_NAME%.exe
echo ============================================================
echo.
pause
