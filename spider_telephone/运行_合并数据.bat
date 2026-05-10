@echo off
chcp 65001 > nul

:: 切换到脚本所在目录
cd /d "%~dp0"
echo ======================================
echo 开始合并数据...
echo ======================================
d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/merge_data.py
if errorlevel 1 (
    echo 数据合并失败，请检查 merge_data.py
    pause
    exit /b 1
)
echo ======================================
echo 处理完毕，请按任意键退出...
echo ======================================
pause