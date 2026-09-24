@echo off
REM ============================================================
REM 一键停止：Nginx、后端(8000)、前端(3000)
REM 未运行的进程会被自动忽略。
REM ============================================================
setlocal

echo 停止 Nginx...
taskkill /IM nginx.exe /F >nul 2>&1

echo 停止后端(8000)...
call :killport 8000

echo 停止前端(3000)...
call :killport 3000

echo 全部服务已停止。
endlocal
exit /b 0

:killport
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1" ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
)
exit /b 0
