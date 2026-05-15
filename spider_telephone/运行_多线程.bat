@echo off
chcp 65001 > nul

:: 切换到脚本所在目录
cd /d "%~dp0"


echo ======================================
echo 开始拆分数据...
echo ======================================
:: 先运行数据拆分脚本
d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/split_data.py
if errorlevel 1 (
    echo 数据拆分失败，请检查 split_data.py
    pause
    exit /b 1
)


echo ======================================
echo 正在启动9个爬虫线程...
echo ======================================

:: 启动5个爬虫进程（无多余引号）
start "Spider-1" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_1.py
start "Spider-2" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_2.py
start "Spider-3" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_3.py
start "Spider-4" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_4.py
start "Spider-5" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_5.py
start "Spider-6" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_6.py
start "Spider-7" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_7.py
start "Spider-8" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_8.py
start "Spider-9" cmd /k d:\_code\python3.13.11\python.exe d:/_code/spider_telephone/spider_9.py

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