@echo off
chcp 936 >nul 2>nul
setlocal EnableDelayedExpansion

rem ============================================================
rem  艺术水平考级证书附件  打包脚本
rem
rem  Python 默认使用 D:\_code\python\python.exe
rem
rem  关于其他电脑报错 “丢失 api-ms-win-core-path-l1-1-0.dll”：
rem    该 DLL 只有 Windows 8 及以上才提供，而 Python 3.9+ 的
rem    python3xx.dll 依赖它，所以用 3.9/3.10 打包的 exe 在 Win7
rem    上必然报这个错。Win7 只能用 Python 3.8 + PyInstaller 5.x。
rem
rem  本脚本策略：
rem    1) 主解释器 PYTHON 使用 D:\_code\python\python.exe（生成字体子集等）
rem    2) 打包时若 PYTHON 是 3.8 就直接用；否则自动寻找 3.8 解释器打包，
rem       以保证 exe 能在 Win7 运行
rem    3) 找不到 3.8 时才会用 PYTHON 打包，并提示仅支持 Win8+
rem
rem  可选环境变量：
rem    PYTHON        主解释器路径（默认 D:\_code\python\python.exe）
rem    PYTHON38      Win7 打包用 3.8 解释器路径（可手动指定）
rem    APP_NAME      生成的 exe 名称
rem    KEEP_BUILD    为 1 时保留 build 中间目录
rem ============================================================

set "APP_NAME=证书附件生成"
set "ENTRY=deal.py"
set "TEMPLATE=空白副证图片.pdf"
set "FONT=simsun_num.ttf"
set "DIST_DIR=dist"
set "BUILD_DIR=build"

if not defined PYTHON set "PYTHON=D:\_code\python\python.exe"
if not defined KEEP_BUILD set "KEEP_BUILD=0"

cd /d "%~dp0"

rem ============ 1. 检查主解释器 ============
echo.
echo [1/5] 检查主解释器...
if not exist "%PYTHON%" (
    where "%PYTHON%" >nul 2>nul
    if errorlevel 1 goto :no_python
)
set "MAIN_VER="
call :py_version "%PYTHON%"
if "%MAIN_VER%"=="" goto :bad_python
echo   %PYTHON%  (Python %MAIN_VER%)

rem ============ 2. 选定打包解释器（Win7 需 3.8） ============
echo.
echo [2/5] 选定打包解释器...
set "BUILDER="
if "%MAIN_VER:~0,3%"=="3.8" (
    set "BUILDER=%PYTHON%"
    echo   使用 %PYTHON%（已是 3.8，兼容 Win7）
) else (
    if defined PYTHON38 (
        call :try38 "%PYTHON38%"
    ) else (
        call :try38 "D:\software\python3.8\python.exe"
        if not defined BUILDER call :try38 "D:\Python38\python.exe"
        if not defined BUILDER call :try38 "%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
        if not defined BUILDER call :try38 "C:\Python38\python.exe"
    )
    if defined BUILDER (
        echo   检测到主解释器为 Python %MAIN_VER%，改用 3.8 打包：!BUILDER!
        echo   （3.9+ 依赖 api-ms-win-core-path-l1-1-0.dll，Win7 没有该文件）
    ) else (
        echo   [警告] 未找到 Python 3.8，将用 Python %MAIN_VER% 打包
        echo          生成的 exe 仅支持 Windows 8 及以上，Win7 会提示缺少
        echo          api-ms-win-core-path-l1-1-0.dll
        set "BUILDER=%PYTHON%"
    )
)

rem ============ 3. 检查依赖 ============
echo.
echo [3/5] 检查 PyInstaller 与依赖...
"%BUILDER%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo   未安装 PyInstaller，正在安装...
    "%BUILDER%" -m pip install "pyinstaller>=5.0" -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto :fail
)
"%BUILDER%" -c "import pymupdf, PIL;print('  pymupdf + Pillow 就绪')"
if errorlevel 1 (
    echo   缺少依赖，正在安装...
    "%BUILDER%" -m pip install pymupdf pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto :fail
)
"%BUILDER%" -c "import PyInstaller;print('  PyInstaller ' + PyInstaller.__version__)"

rem ============ 4. 准备内置资源 ============
echo.
echo [4/5] 准备内置资源（模板 + 字体子集 + UCRT）...
if not exist "%TEMPLATE%" (
    echo   [ERROR] 缺少模板：%TEMPLATE%
    goto :fail
)
echo   模板：%TEMPLATE%

if not exist "%FONT%" (
    echo   正在生成数字字体子集（使用主解释器）...
    "%PYTHON%" "subset_font.py"
    if errorlevel 1 (
        echo   主解释器无法生成，尝试打包解释器...
        "%BUILDER%" "subset_font.py"
        if errorlevel 1 goto :fail
    )
)
if not exist "%FONT%" (
    echo   [ERROR] 缺少字体子集：%FONT%
    goto :fail
)
echo   字体：%FONT%

rem UCRT：Win7 未打 KB2999226 时缺少通用 C 运行库，这里一并收集
set "UCRT_ARGS="
if exist "%WINDIR%\System32\ucrtbase.dll" (
    set "UCRT_ARGS=--add-binary %WINDIR%\System32\ucrtbase.dll;."
    echo   UCRT：ucrtbase.dll
)
for %%D in (api-ms-win-crt-runtime-l1-1-0.dll api-ms-win-crt-heap-l1-1-0.dll api-ms-win-crt-stdio-l1-1-0.dll api-ms-win-crt-string-l1-1-0.dll api-ms-win-crt-convert-l1-1-0.dll api-ms-win-crt-math-l1-1-0.dll api-ms-win-crt-locale-l1-1-0.dll api-ms-win-crt-time-l1-1-0.dll api-ms-win-crt-filesystem-l1-1-0.dll api-ms-win-crt-environment-l1-1-0.dll api-ms-win-crt-process-l1-1-0.dll api-ms-win-crt-conio-l1-1-0.dll api-ms-win-crt-utility-l1-1-0.dll) do (
    if exist "%WINDIR%\System32\%%D" (
        set "UCRT_ARGS=!UCRT_ARGS! --add-binary %WINDIR%\System32\%%D;."
    )
)

rem ============ 5. 打包 ============
echo.
echo [5/5] 正在打包（约 1-3 分钟）...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe" >nul 2>nul

"%BUILDER%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%\work" ^
    --specpath "%BUILD_DIR%" ^
    --add-data "%~dp0%TEMPLATE%;." ^
    --add-data "%~dp0%FONT%;." ^
    !UCRT_ARGS! ^
    --hidden-import "pymupdf" ^
    --hidden-import "PIL" ^
    --hidden-import "PIL.Image" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "tkinter.filedialog" ^
    --hidden-import "tkinter.messagebox" ^
    --exclude-module "numpy" ^
    --exclude-module "pandas" ^
    --exclude-module "matplotlib" ^
    --exclude-module "scipy" ^
    --exclude-module "setuptools" ^
    --exclude-module "pkg_resources" ^
    --exclude-module "pip" ^
    --exclude-module "unittest" ^
    --exclude-module "test" ^
    --exclude-module "lib2to3" ^
    --exclude-module "pydoc_data" ^
    --exclude-module "idlelib" ^
    --exclude-module "turtle" ^
    --exclude-module "turtledemo" ^
    --exclude-module "venv" ^
    --exclude-module "ensurepip" ^
    --log-level WARN ^
    "%ENTRY%"

if errorlevel 1 goto :fail
if not exist "%DIST_DIR%\%APP_NAME%.exe" goto :fail

if "%KEEP_BUILD%"=="0" if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"

for %%F in ("%DIST_DIR%\%APP_NAME%.exe") do set "EXE_SIZE=%%~zF"
set /a EXE_MB=%EXE_SIZE%/1048576

echo.
echo ============================================================
echo  打包完成
echo    EXE      ：%cd%\%DIST_DIR%\%APP_NAME%.exe  (%EXE_MB% MB)
echo    主解释器 ：%PYTHON%  (Python %MAIN_VER%)
echo    打包解释器：%BUILDER%
echo.
echo  使用说明：
echo    * 单文件 exe，模板与字体子集已内置，双击即可运行
echo    * 每个 “029-xxx-xxx图片” 目录会在同级生成 “029-xxx-xxx附证” 并输出 PDF
echo    * 输出根目录默认等于图片根目录，可在界面中另行指定
echo ============================================================
echo.
pause
exit /b 0

rem ==================== 子过程 ====================

:py_version
rem %1=解释器；把 "3.8.10" 形式写到 MAIN_VER
set "MAIN_VER="
if not exist "%~1" exit /b 1
set "VER_FILE=%TEMP%\_pyver_%~n0.txt"
del /f /q "%VER_FILE%" >nul 2>nul
"%~1" -c "import sys,io;io.open(r'%VER_FILE%','w').write('.'.join(map(str,sys.version_info[:3])))" >nul 2>nul
if exist "%VER_FILE%" (
    set /p MAIN_VER=<"%VER_FILE%"
    del /f /q "%VER_FILE%" >nul 2>nul
)
exit /b 0

:try38
rem %1=候选 3.8 解释器；可用则设置 BUILDER 并返回
if defined BUILDER exit /b 0
if not exist "%~1" exit /b 1
set "VER_FILE=%TEMP%\_pyver38_%~n0.txt"
del /f /q "%VER_FILE%" >nul 2>nul
"%~1" -c "import sys,io;io.open(r'%VER_FILE%','w').write('.'.join(map(str,sys.version_info[:3])))" >nul 2>nul
set "V="
if exist "%VER_FILE%" (
    set /p V=<"%VER_FILE%"
    del /f /q "%VER_FILE%" >nul 2>nul
)
if "%V:~0,3%"=="3.8" set "BUILDER=%~1"
exit /b 0

:no_python
echo.
echo [ERROR] 未找到 Python：%PYTHON%
echo         请安装 Python，或用环境变量 PYTHON 指定解释器路径
echo.
pause
exit /b 1

:bad_python
echo.
echo [ERROR] 无法获取 Python 版本：%PYTHON%
echo.
pause
exit /b 1

:fail
echo.
echo [ERROR] 打包失败，请查看上方日志
echo.
pause
exit /b 1
