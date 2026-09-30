@echo off
setlocal

rem ============ Configurable ============
set "APP_NAME=Jobs"
set "ENTRY=getJobs.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "SPEC_FILE=%APP_NAME%.spec"
set "PYTHON=d:\_code\python\python.exe"
set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

cd /d "%~dp0"

rem ============ 1. Check Python ============
echo.
echo [1/5] Checking Python...
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found: %PYTHON%
    pause
    exit /b 1
)
"%PYTHON%" --version

rem ============ 2. Check PyInstaller ============
echo.
echo [2/5] Checking PyInstaller...
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

rem ============ 3. Check dependencies ============
echo.
echo [3/5] Checking dependencies...
"%PYTHON%" -c "import requests, openpyxl, playwright, tkinter" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    "%PYTHON%" -m pip install requests openpyxl playwright -i "%PIP_MIRROR%"
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
    echo [INFO] Dependencies installed.
) else (
    echo Dependencies OK.
)

rem ============ 4. Prune bundled browsers + clean old output ============
rem 不再内置 Chromium：删除 playwright 包内的 .local-browsers（约 680MB），
rem 运行时改用系统自带的 Edge/Chrome，从而大幅缩小 exe 体积。
echo.
echo [4/5] Pruning bundled browsers and cleaning old output...
"%PYTHON%" -c "import playwright, os, shutil; p=os.path.join(os.path.dirname(playwright.__file__),'driver','package','.local-browsers'); existed=os.path.isdir(p); shutil.rmtree(p, ignore_errors=True); print('[INFO] removed bundled browsers' if existed else '[INFO] no bundled browsers found')"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%SPEC_FILE%" del /f /q "%SPEC_FILE%"

rem ============ 5. Build ============
echo.
echo [5/5] Building single-file EXE...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --paths "." ^
    --paths ".." ^
    --collect-all "playwright" ^
    --hidden-import "Logger" ^
    --hidden-import "requests" ^
    --hidden-import "openpyxl" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "tkinter.simpledialog" ^
    --exclude-module "pandas" ^
    --exclude-module "numpy" ^
    --exclude-module "scipy" ^
    --exclude-module "matplotlib" ^
    --exclude-module "PIL" ^
    --exclude-module "IPython" ^
    --exclude-module "jupyter" ^
    --exclude-module "pytest" ^
    --exclude-module "setuptools" ^
    --exclude-module "ReadFile" ^
    --exclude-module "lib2to3" ^
    --exclude-module "test" ^
    --exclude-module "doctest" ^
    --exclude-module "pydoc_data" ^
    --exclude-module "xlsxwriter" ^
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
echo EXE : %cd%\%DIST_DIR%\%APP_NAME%.exe
echo.
echo Notes:
echo   * No bundled browser: the EXE uses the system Edge/Chrome at runtime.
echo     Windows 10/11 ships Edge, so no extra install is needed.
echo   * Force a specific browser via env PLAYWRIGHT_CHANNEL (msedge/chrome/chromium).
echo   * Login state zp_profile is created/reused next to the EXE; keep that dir writable.
echo   * If the "removed bundled browsers" line above said "no bundled browsers found",
echo     the EXE may still be large because a browser is present in the package.
echo ============================================================
echo.
pause
