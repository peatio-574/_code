@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM Edge 账号批量处理工具 - PyInstaller 打包脚本
REM 入口：execute.py
REM 输出：dist\Edge账号批量处理工具.exe
REM ============================================================

set "APP_NAME=Edge账号批量处理工具"
set "ENTRY=execute.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "SPEC_FILE=%APP_NAME%.spec"

set "PYTHON=d:\_code\python\python.exe"

echo.
echo [1/5] 检查 Python 环境...
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 并加入 PATH。
    pause
    exit /b 1
)
"%PYTHON%" --version

echo.
echo [2/5] 检查并安装打包依赖 PyInstaller...
"%PYTHON%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    "%PYTHON%" -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败。
        pause
        exit /b 1
    )
) else (
    echo PyInstaller 已安装。
)

echo.
echo [3/5] 检查项目依赖...
"%PYTHON%" -c "import tkinter, pandas, openpyxl, requests, urllib3" >nul 2>nul
if errorlevel 1 (
    echo [提示] 检测到缺少运行依赖，开始安装...
    "%PYTHON%" -m pip install pandas openpyxl requests urllib3 -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败。
        pause
        exit /b 1
    )
) else (
    echo 项目依赖检查通过。
)

echo.
echo [4/5] 清理旧打包文件...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%SPEC_FILE%" del /f /q "%SPEC_FILE%"

echo.
echo [5/5] 开始打包可视化程序...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --paths "." ^
    --paths ".." ^
    --hidden-import "ReadFile" ^
    --hidden-import "pandas" ^
    --hidden-import "openpyxl" ^
    --hidden-import "requests" ^
    --hidden-import "urllib3" ^
    --hidden-import "tkinter" ^
    --collect-submodules "pandas" ^
    --collect-submodules "openpyxl" ^
    "%ENTRY%"

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方 PyInstaller 错误信息。
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [完成] 打包成功！
echo EXE 文件位置：%cd%\%DIST_DIR%\%APP_NAME%.exe
echo ============================================================
echo.
pause
