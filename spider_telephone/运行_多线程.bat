@echo off
chcp 65001 > nul

:: 切换到脚本所在目录
cd /d "%~dp0"


echo ======================================
echo 开始拆分数据...
echo ======================================
:: 先运行数据拆分脚本
python split_data.py
if errorlevel 1 (
    echo 数据拆分失败，请检查 split_data.py
    pause
    exit /b 1
)


echo ======================================
echo 正在启动5个爬虫线程...
echo ======================================

:: 启动5个爬虫进程（无多余引号）
start "Spider-1" cmd /c python spider_1.py
start "Spider-2" cmd /c python spider_2.py
start "Spider-3" cmd /c python spider_3.py
start "Spider-4" cmd /c python spider_4.py
start "Spider-5" cmd /c python spider_5.py

:: 等待所有 python 进程结束
echo ======================================
echo 等待所有线程运行完毕...
echo ======================================
:wait_loop
timeout /t 5 /nobreak >nul
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if not errorlevel 1 goto wait_loop

echo 所有线程运行完毕...
echo ======================================
echo 开始合并数据...
echo ======================================
python merge_data.py
if errorlevel 1 (
    echo 数据合并失败，请检查 merge_data.py
    pause
    exit /b 1
)
echo ======================================
echo 处理完毕，请按任意键退出...
echo ======================================
pause