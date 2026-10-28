@echo off
rem ====================================================================
rem  Google 关键词采集 —— 打包成单文件 exe
rem
rem  双击本文件即可。产物：dist\Google关键词采集.exe
rem
rem  前置条件：
rem    · Python 3.8+（默认用 D:\_code\python\python.exe，找不到则用 PATH 里的 python）
rem    · PyInstaller：python -m pip install pyinstaller
rem
rem  关于脚本自动生成的 _pyi_hooks 目录：
rem    本机 Python 环境里还装着 patchright（spiderJobs 在用）。它会向
rem    PyInstaller 注册一个和 playwright 同名同文件的 hook，
rem    内容是收集它自己的 100MB+ driver，从而把 patchright 整个打进 exe。
rem    本项目只用 newPlayWright（底层 playwright），所以这里放一份同名
rem    hook 覆盖掉它，只收集 playwright 真正需要的文件。
rem    效果：exe 从约 90MB 降到约 54MB。该目录可随时删除，脚本会重建。
rem ====================================================================
chcp 936 >nul
setlocal
cd /d "%~dp0"

echo ====================================================================
echo   Google 关键词采集 - 打包 exe
echo ====================================================================
echo.

rem ---------------- 1. 检查 Python ----------------
set "PY=d:\_code\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到可用的 Python。
    echo        请安装 Python，或修改本文件开头的 PY 变量。
    pause
    exit /b 1
)
for /f "delims=" %%v in ('"%PY%" --version 2^>^&1') do echo [1/5] Python: %%v

"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有安装 PyInstaller，请先执行：
    echo         "%PY%" -m pip install pyinstaller
    pause
    exit /b 1
)
for /f "delims=" %%v in ('"%PY%" -c "import PyInstaller;print(PyInstaller.__version__)" 2^>^&1') do echo [1/5] PyInstaller: %%v

rem ---------------- 2. 检查入口文件 ----------------
if not exist "keyword_get_email_gui.py" (
    echo [错误] 当前目录没有 keyword_get_email_gui.py
    echo        请把本 bat 放在 Google_get_email 目录下运行。
    pause
    exit /b 1
)
echo [2/5] 入口文件 OK: keyword_get_email_gui.py

set "ICON_ARG=--icon app.ico"
set "ICO_DATA=--add-data app.ico;."
set "PNG_DATA=--add-data app.png;."
if not exist "app.ico" (
    echo [警告] app.ico 不存在，将不带图标打包
    set "ICON_ARG="
    set "ICO_DATA="
)
if not exist "app.png" set "PNG_DATA="

rem ---------------- 3. 生成 playwright hook 覆盖 ----------------
if not exist "_pyi_hooks" mkdir "_pyi_hooks"
set "HK_SYNC=_pyi_hooks\hook-playwright.sync_api.py"
set "HK_ASYNC=_pyi_hooks\hook-playwright.async_api.py"

>"%HK_SYNC%" echo from PyInstaller.utils.hooks import collect_data_files
>>"%HK_SYNC%" echo datas = collect_data_files^('playwright', includes=['driver/node.exe', 'driver/package/lib/**', 'driver/package/*.json', 'driver/package/*.js', 'driver/package/*.mjs'], excludes=['**/*.d.ts', 'driver/package/types/**', '**/__pycache__/**', 'driver/package/lib/vite/**']^)
>>"%HK_SYNC%" echo binaries = []
>>"%HK_SYNC%" echo hiddenimports = []

>"%HK_ASYNC%" echo datas = []
>>"%HK_ASYNC%" echo binaries = []
>>"%HK_ASYNC%" echo hiddenimports = []
echo [3/5] 已生成 hook 覆盖: %HK_SYNC%

rem ---------------- 4. 清理旧产物 ----------------
echo [4/5] 清理旧产物...
if exist "build" rmdir /s /q "build"
if exist "__pycache__" rmdir /s /q "__pycache__"
if exist "dist\Google关键词采集.exe" del /q "dist\Google关键词采集.exe"

rem ---------------- 5. 打包 ----------------
echo [5/5] 开始打包，请稍候（首次约 1~2 分钟）...
echo.
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
    --name "Google关键词采集" ^
    %ICON_ARG% ^
    --additional-hooks-dir "_pyi_hooks" ^
    --paths "." --paths ".." ^
    %ICO_DATA% ^
    %PNG_DATA% ^
    --hidden-import newPlayWright ^
    --hidden-import Logger ^
    --hidden-import Config ^
    --hidden-import openpyxl.cell._writer ^
    --exclude-module patchright ^
    --exclude-module PIL ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module scipy ^
    --exclude-module matplotlib ^
    --exclude-module PyQt5 ^
    --exclude-module PyQt6 ^
    --exclude-module PySide2 ^
    --exclude-module PySide6 ^
    --exclude-module IPython ^
    --exclude-module pytest ^
    --exclude-module setuptools ^
    --exclude-module pip ^
    --exclude-module playwright.async_api ^
    --optimize 1 ^
    "keyword_get_email_gui.py"

if errorlevel 1 (
    echo.
    echo [失败] 打包出错，请查看上面的输出。
    echo        常见原因：PyInstaller 版本过旧、文件被杀软占用。
    pause
    exit /b 1
)

rem ---------------- 结果 ----------------
echo.
if not exist "dist\Google关键词采集.exe" (
    echo [失败] 没有生成 dist\Google关键词采集.exe
    pause
    exit /b 1
)
for %%F in ("dist\Google关键词采集.exe") do set "EXE_SIZE=%%~zF"
set /a EXE_MB=%EXE_SIZE%/1048576
echo ====================================================================
echo   打包完成
echo --------------------------------------------------------------------
echo   输出：%~dp0dist\Google关键词采集.exe
echo   体积：%EXE_MB% MB（%EXE_SIZE% 字节）
echo.
echo   说明：
echo     · 单文件 exe，复制到别的机器即可运行，无需安装 Python
echo     · 目标机器需要已安装 Microsoft Edge
echo     · 结果文件 google_contacts.xlsx 由程序在 exe 同级目录自动创建/读写
echo     · 日志写在 exe 同级目录的 logs\ 下
echo ====================================================================

if exist "build" rmdir /s /q "build"
echo.
pause
