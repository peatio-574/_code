@echo off
chcp 936 >nul 2>nul
setlocal EnableDelayedExpansion

rem ============================================================
rem  艺术水平考级证书附件 - 作品照片批量贴图  打包脚本
rem
rem  * 模板 空白副证图片.pdf 打包进 exe
rem  * 字体只打包“数字 + 连字符”的宋体子集（约 10KB），
rem    不内置 17MB 的完整 simsun.ttc
rem  * 生成单文件免安装 exe，双击即可运行（GUI 不显示模板路径）
rem
rem  可选环境变量：
rem    PYTHON     指定解释器路径（默认 D:\_code\python\python.exe）
rem    APP_NAME   生成的 exe 名称
rem    KEEP_BUILD 为 1 时保留 build 中间目录
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

rem ============ 1. 检查 Python ============
echo.
echo [1/5] 检查 Python...
if not exist "%PYTHON%" (
    where "%PYTHON%" >nul 2>nul
    if errorlevel 1 goto :no_python
)
"%PYTHON%" -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,8) else 1)" >nul 2>nul
if errorlevel 1 goto :bad_python
"%PYTHON%" -c "import sys;print('  Python ' + sys.version.split()[0])"

rem ============ 2. 检查依赖 ============
echo.
echo [2/5] 检查 PyInstaller 与依赖...
"%PYTHON%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo   未安装 PyInstaller，正在安装...
    "%PYTHON%" -m pip install --upgrade pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto :fail
)
"%PYTHON%" -c "import pymupdf, PIL, fontTools;print('  PyInstaller + pymupdf + Pillow + fontTools 就绪')"
if errorlevel 1 (
    echo   缺少依赖，正在安装...
    "%PYTHON%" -m pip install pymupdf pillow fonttools -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto :fail
)

rem ============ 3. 准备内置资源 ============
echo.
echo [3/5] 准备内置资源（模板 + 字体子集）...
if not exist "%TEMPLATE%" (
    echo   [ERROR] 缺少模板：%TEMPLATE%
    goto :fail
)
echo   模板：%TEMPLATE%  （约 250KB）

if not exist "%FONT%" (
    echo   正在从系统宋体生成数字子集...
    "%PYTHON%" "subset_font.py"
    if errorlevel 1 goto :fail
)
if not exist "%FONT%" (
    echo   [ERROR] 生成字体子集失败：%FONT%
    goto :fail
)
echo   字体：%FONT%

rem ============ 4. 清理旧产物 ============
echo.
echo [4/5] 清理旧产物...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe" >nul 2>nul
echo   完成

rem ============ 5. 打包 ============
echo.
echo [5/5] 正在打包（约 1-3 分钟）...
"%PYTHON%" -m PyInstaller ^
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
    --exclude-module "IPython" ^
    --exclude-module "pytest" ^
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
echo    EXE：%cd%\%DIST_DIR%\%APP_NAME%.exe  (%EXE_MB% MB)
echo.
echo  使用说明：
echo    * 单文件 exe，模板与字体子集已内置，双击即可运行
echo    * 把 exe 放到作品目录的上级目录，或运行后在界面里选择图片根目录
echo    * 每个 “029-xxx-xxx图片” 目录会在同级生成 “029-xxx-xxx附证” 并输出 PDF
echo    * 输出目录可在界面中另行指定
echo ============================================================
echo.
pause
exit /b 0

:no_python
echo.
echo [ERROR] 未找到 Python：%PYTHON%
echo         请安装 Python 3.8+，或用环境变量 PYTHON 指定解释器路径
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
echo [ERROR] 打包失败，请查看上方日志
echo.
pause
exit /b 1
