@echo off
rem ====================================================================
rem  Google 关键词采集 —— 打包成单文件 exe
rem
rem  双击本文件即可。产物：dist\Google关键词采集.exe
rem
rem  入口是 run.py（图形界面，可在 Google / Facebook 之间切换）
rem  另外两个采集模块：google.py、facebook.py —— 不要单独打包它们
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
if not exist "run.py" (
    echo [错误] 当前目录没有 run.py
    echo        请把本 bat 放在 Google_get_email 目录下运行。
    pause
    exit /b 1
)
echo [2/5] 入口文件 OK: run.py

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
    "run.py"

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

rem ---- 生成外部配置文件（exe 同级；已存在则不覆盖） ----
rem config.ini 和结果 xlsx 都必须是「exe 外面的普通文件」：
rem   程序运行时按 exe 所在目录读写它们，用户随时能打开查看 / 编辑。
rem   绝对不要用 --add-data 把它们打进 exe —— 那样改的是临时解包目录里的副本，
rem   进程一退出就没了，用户也改不到。
if not exist "dist\config.ini" (
    >"dist\config.ini" echo [login]
    >>"dist\config.ini" echo ; Facebook login cookie. Written back automatically after login.
    >>"dist\config.ini" echo ; To switch account: click the delete-account button, or log in again.
    >>"dist\config.ini" echo facebook_cookie = 
    >>"dist\config.ini" echo facebook_cookie_api = 
    echo   已生成空白 dist\config.ini（可自行编辑）
) else (
    echo   dist\config.ini 已存在，保留原内容
)

echo ====================================================================
echo   打包完成
echo --------------------------------------------------------------------
echo   输出：%~dp0dist\Google关键词采集.exe
echo   体积：%EXE_MB% MB（%EXE_SIZE% 字节）
echo.
echo   说明：
echo     · 单文件 exe，复制到别的机器即可运行，无需安装 Python
echo     · 目标机器需要已安装 Microsoft Edge
echo.
echo   【外部文件】下面这些都在 exe 同级目录，不在 exe 里面：
echo     · config.ini            Facebook 账号 cookie（自动生成 / 自动写回）
echo     · 结果.xlsx  采集结果（首次运行自动创建）
echo       这两个可以直接用记事本 / Excel 打开，改完保存即可生效
echo     · logs\                 运行日志
echo.
echo   【迁移】把 exe 换到别的文件夹或机器时，连同 config.ini 一起复制，
echo           就不用重新登录 Facebook。
echo ====================================================================

if exist "build" rmdir /s /q "build"
echo.
pause
