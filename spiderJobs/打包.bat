@echo off
chcp 936 >nul 2>nul
setlocal EnableDelayedExpansion

rem ============================================================
rem  Jobs 打包脚本（PyInstaller）
rem
rem  * 解释器：d:\_code\python\python.exe（可用 PYTHON 覆盖）
rem  * config.ini 放在 exe 同目录：外部可读可改，登录后 Cookie 自动写回
rem  * 体积优化：裁剪 playwright 无用数据 + 排除重型依赖 + 单文件 + 字节码优化
rem
rem  可选环境变量：
rem    PYTHON         指定解释器（路径或命令名）
rem    PIP_MIRROR     pip 镜像，默认清华
rem    OPTIMIZE       字节码优化级别，默认 1；设 2 更小
rem    UPX_DIR        UPX 目录，设置后启用 UPX 压缩
rem    KEEP_PW_FULL   设为 1 则不裁剪 playwright
rem ============================================================

set "APP_NAME=Jobs"
set "ENTRY=getJobs.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "WORK_DIR=%BUILD_DIR%\work"
set "HOOK_DIR=%BUILD_DIR%\hooks"

if not defined PYTHON set "PYTHON=d:\_code\python\python.exe"
if not defined PIP_MIRROR set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
if not defined OPTIMIZE set "OPTIMIZE=1"
if not defined KEEP_PW_FULL set "KEEP_PW_FULL=0"

cd /d "%~dp0"

rem ============ 1. 检查 Python ============
echo.
echo [1/6] 检查 Python...

set "PY_OK=0"
if exist "%PYTHON%" set "PY_OK=1"
if "%PY_OK%"=="0" (
    where "%PYTHON%" >nul 2>nul
    if not errorlevel 1 set "PY_OK=1"
)
if "%PY_OK%"=="0" goto :no_python

"%PYTHON%" -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,8) else 1)" >nul 2>nul
if errorlevel 1 goto :bad_python
"%PYTHON%" -c "import sys;print('  Python ' + sys.version.split()[0] + '  (' + sys.executable + ')')"
if errorlevel 1 goto :bad_python

rem ============ 2. PyInstaller ============
echo.
echo [2/6] 检查 PyInstaller...
"%PYTHON%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo   未安装，正在安装...
    "%PYTHON%" -m pip install --upgrade pyinstaller -i "%PIP_MIRROR%"
    if errorlevel 1 goto :fail
)
"%PYTHON%" -c "import PyInstaller;print('  PyInstaller', PyInstaller.__version__)"

rem ============ 3. 运行依赖 ============
echo.
echo [3/6] 检查运行依赖...
"%PYTHON%" -c "import requests, openpyxl, bs4, playwright, screeninfo" >nul 2>nul
if errorlevel 1 (
    echo   缺少依赖，正在安装...
    "%PYTHON%" -m pip install requests openpyxl beautifulsoup4 playwright screeninfo -i "%PIP_MIRROR%"
    if errorlevel 1 goto :fail
)
echo   依赖就绪

rem ============ 4. 清理旧产物 ============
rem 只清理 build 与旧 exe；dist 下的 config.ini / logs / zp_profile 保留
echo.
echo [4/6] 清理旧产物...
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
if exist "%BUILD_DIR%\*.spec" del /f /q "%BUILD_DIR%\*.spec" >nul 2>nul
if not exist "%HOOK_DIR%" mkdir "%HOOK_DIR%" >nul 2>nul
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%" >nul 2>nul
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe" >nul 2>nul

rem ============ 5. playwright 裁剪 hook ============
rem 官方 hook 会全量 collect_data_files('playwright')，driver 约 100MB。
rem 以下内容本工具用不到，排除后 exe 明显变小：
rem   driver\package\types       1.8MB  TypeScript 类型声明
rem   driver\package\bin         安装脚本（.ps1/.sh）
rem   driver\package\lib\vite    3.5MB  仅 trace viewer / codegen / UI 模式使用
echo.
echo [5/6] 准备 playwright 裁剪 hook...
if "%KEEP_PW_FULL%"=="1" (
    echo   跳过裁剪（KEEP_PW_FULL=1）
) else (
    call :write_hook "hook-playwright.async_api.py"
    call :write_hook "hook-playwright.sync_api.py"
    echo   已排除 types / bin / lib\vite
)

rem ============ 6. 打包 ============
echo.
echo [6/6] 打包中（单文件，约 1-3 分钟）...
set "UPX_ARG=--noupx"
if defined UPX_DIR set "UPX_ARG=--upx-dir %UPX_DIR%"

"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%WORK_DIR%" ^
    --specpath "%BUILD_DIR%" ^
    --additional-hooks-dir "%HOOK_DIR%" ^
    --optimize %OPTIMIZE% ^
    --log-level WARN ^
    --paths "." ^
    --paths ".." ^
    --hidden-import "Logger" ^
    --hidden-import "Config" ^
    --hidden-import "newPlayWright" ^
    --hidden-import "guopin" ^
    --hidden-import "ncss" ^
    --hidden-import "zhipin" ^
    --hidden-import "requests" ^
    --hidden-import "openpyxl" ^
    --hidden-import "bs4" ^
    --hidden-import "screeninfo" ^
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
    --exclude-module "notebook" ^
    --exclude-module "pytest" ^
    --exclude-module "setuptools" ^
    --exclude-module "pkg_resources" ^
    --exclude-module "pip" ^
    --exclude-module "unittest" ^
    --exclude-module "doctest" ^
    --exclude-module "lib2to3" ^
    --exclude-module "test" ^
    --exclude-module "pydoc_data" ^
    --exclude-module "xlsxwriter" ^
    --exclude-module "ensurepip" ^
    --exclude-module "venv" ^
    --exclude-module "idlelib" ^
    --exclude-module "turtle" ^
    --exclude-module "turtledemo" ^
    %UPX_ARG% ^
    "%ENTRY%"

if errorlevel 1 goto :fail
if not exist "%DIST_DIR%\%APP_NAME%.exe" goto :fail

rem ============ 7. 外置 config.ini ============
call :ensure_config

for %%F in ("%DIST_DIR%\%APP_NAME%.exe") do set "EXE_SIZE=%%~zF"
set /a EXE_MB=%EXE_SIZE%/1048576

echo.
echo ============================================================
echo  打包完成
echo    EXE      : %cd%\%DIST_DIR%\%APP_NAME%.exe  (%EXE_MB% MB)
echo    配置文件 : %cd%\%DIST_DIR%\config.ini
echo.
echo  使用说明：
echo    * config.ini 与 exe 同目录，可直接用记事本编辑；
echo      学信网登录成功后 Cookie 自动写回该文件，下次启动仍有效。
echo    * 日志：exe 同目录 logs\日期.log
echo    * 智联登录态：exe 同目录 zp_profile（删除后需重新登录）
echo    * 使用系统 Edge/Chrome，不内置浏览器；PLAYWRIGHT_CHANNEL 可指定。
echo ============================================================
echo.
pause
exit /b 0

rem ==================== 子过程 ====================

:write_hook
rem 生成仅含 ASCII 的 hook，避免编码问题
> "%HOOK_DIR%\%~1" echo from PyInstaller.utils.hooks import collect_data_files
>>"%HOOK_DIR%\%~1" echo datas = collect_data_files(
>>"%HOOK_DIR%\%~1" echo     "playwright",
>>"%HOOK_DIR%\%~1" echo     excludes=[
>>"%HOOK_DIR%\%~1" echo         "driver/package/types/**/*",
>>"%HOOK_DIR%\%~1" echo         "driver/package/bin/*",
>>"%HOOK_DIR%\%~1" echo         "driver/package/lib/vite/**/*",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.d.ts",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.map",
>>"%HOOK_DIR%\%~1" echo         "**/__pycache__/**",
>>"%HOOK_DIR%\%~1" echo         "**/*.ps1",
>>"%HOOK_DIR%\%~1" echo         "**/*.sh",
>>"%HOOK_DIR%\%~1" echo     ],
>>"%HOOK_DIR%\%~1" echo )
exit /b 0

:ensure_config
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%" >nul 2>nul
if exist "%DIST_DIR%\config.ini" (
    echo   已保留现有 config.ini（不覆盖）
    exit /b 0
)
if exist "config.ini" (
    copy /y "config.ini" "%DIST_DIR%\config.ini" >nul
    echo   已复制现有 config.ini 到 dist
    exit /b 0
)
> "%DIST_DIR%\config.ini" echo [login]
>>"%DIST_DIR%\config.ini" echo nscc_cookie =
>>"%DIST_DIR%\config.ini" echo nscc_cookie_api =
echo   已创建空白 config.ini 模板
exit /b 0

:no_python
echo.
echo [ERROR] 未找到 Python：%PYTHON%
echo         请安装 3.8+，或设置环境变量 PYTHON 指向解释器。
echo.
pause
exit /b 1

:bad_python
echo.
echo [ERROR] Python 版本过低（需 3.8+）：%PYTHON%
echo.
pause
exit /b 1

:fail
echo.
echo [ERROR] 打包失败，请查看上方日志。
echo.
pause
exit /b 1
