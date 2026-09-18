@echo off
setlocal

REM ============================================================
REM moneyga automation - PyInstaller build script
REM Entry : execute.py (imports newPlayWright.py / Config.py / Logger.py from parent dir)
REM Browser: system Microsoft Edge (Chromium is NOT bundled, keeps size small)
REM Output : dist\MoneyGa.exe
REM ============================================================

cd /d "%~dp0"

set "APP_NAME=MoneyGa"
set "ENTRY=execute.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "SPEC_FILE=%APP_NAME%.spec"
set "PYTHON=d:\_code\python\python.exe"
set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

echo.
echo [1/6] Checking Python...
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found: %PYTHON%
    pause
    exit /b 1
)
"%PYTHON%" --version

echo.
echo [2/6] Checking PyInstaller...
"%PYTHON%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    "%PYTHON%" -m pip install pyinstaller -i "%PIP_MIRROR%"
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed.
        pause
        exit /b 1
    )
) else (
    echo PyInstaller OK.
)

echo.
echo [3/6] Checking project dependencies...
"%PYTHON%" -c "import playwright, openpyxl, screeninfo, requests" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    "%PYTHON%" -m pip install playwright openpyxl screeninfo requests -i "%PIP_MIRROR%"
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
) else (
    echo Dependencies OK.
)

echo.
echo [4/6] Cleaning old output...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%SPEC_FILE%" del /f /q "%SPEC_FILE%"

echo.
echo [5/6] Building EXE...
REM --onefile           single EXE
REM --console           keep console (script prints / logs)
REM --paths ".."        find newPlayWright.py / Config.py / Logger.py in parent dir
REM --collect-all       collect playwright driver (node) only, no Chromium
REM --exclude-module    drop unused heavy libraries to shrink size
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name "%APP_NAME%" ^
    --paths "." ^
    --paths ".." ^
    --collect-all "playwright" ^
    --hidden-import "newPlayWright" ^
    --hidden-import "Config" ^
    --hidden-import "Logger" ^
    --hidden-import "logging.handlers" ^
    --hidden-import "openpyxl" ^
    --hidden-import "screeninfo" ^
    --hidden-import "requests" ^
    --exclude-module "pandas" ^
    --exclude-module "numpy" ^
    --exclude-module "scipy" ^
    --exclude-module "matplotlib" ^
    --exclude-module "PIL" ^
    --exclude-module "tkinter" ^
    --exclude-module "IPython" ^
    --exclude-module "jupyter" ^
    --exclude-module "pytest" ^
    --exclude-module "setuptools" ^
    --exclude-module "pkg_resources" ^
    --exclude-module "distutils" ^
    --exclude-module "lib2to3" ^
    --exclude-module "test" ^
    --exclude-module "pydoc_data" ^
    "%ENTRY%"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See PyInstaller output above.
    pause
    exit /b 1
)

echo.
echo [6/6] Copying runtime files to dist...
if exist "*.xlsx" copy /y "*.xlsx" "%DIST_DIR%\" >nul
if exist "..\config.ini" copy /y "..\config.ini" "%DIST_DIR%\" >nul

echo.
echo ============================================================
echo [DONE] Build success!
echo EXE: %cd%\%DIST_DIR%\%APP_NAME%.exe
echo.
echo Notes:
echo   * Microsoft Edge must be installed (script uses system Edge, Chromium not bundled)
echo   * Put data.xlsx next to the EXE; results are written back into it
echo   * logs folder is created next to the EXE automatically
echo ============================================================
echo.
pause
