@echo off
cd /d "%~dp0"

echo ========================================
echo   Pokemon Login Tool - Build
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    pause & exit /b 1
)

python -c "import pyinstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/4] Installing pyinstaller...
    pip install pyinstaller
)

python -c "from playwright.sync_api import sync_playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/4] Installing requirements...
    pip install playwright requests openpyxl pandas screeninfo
) else (
    echo [2/4] Dependencies OK
)

python -c "from playwright.sync_api import sync_playwright; print('checking browser'); p=sync_playwright().start(); p.chromium.launch().close(); p.stop()" >nul 2>&1
if %errorlevel% neq 0 (
    echo [3/4] Installing Playwright Chromium...
    playwright install chromium
) else (
    echo [3/4] Playwright Chromium OK
)

if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"

echo [4/4] Building...
pyinstaller --onedir --windowed --name "PokemonLogin" --paths "D:\_code" --hidden-import tkinter --hidden-import asyncio --hidden-import playwright.sync_api --hidden-import requests --hidden-import screeninfo --collect-all playwright --collect-all openpyxl --collect-all pandas --clean run.py

if %errorlevel% equ 0 (
    echo ========================================
    echo   BUILD SUCCESS
    echo   Output: dist\PokemonLogin\
    echo ========================================
) else (
    echo ========================================
    echo   BUILD FAILED
    echo ========================================
)
pause
