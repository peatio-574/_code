@echo off
REM ============================================================
REM 一键启动：FastAPI 后端(8000) + Nginx(8081)
REM 访问地址：http://localhost:8081
REM 说明：前端改动后需先构建：cd /d D:\_code\edu\frontend 然后 npm run build
REM ============================================================
setlocal
set "ROOT=D:\_code\edu"
set "NGINX_DIR=D:\software\nginx-1.23.0"
set "CONF=%ROOT%\deploy\nginx.edu.conf"
set "PY=%ROOT%\backend\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [错误] 未找到虚拟环境：%PY%
  echo        请先执行：
  echo          cd /d %ROOT%\backend
  echo          python -m venv .venv
  echo          .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)
if not exist "%NGINX_DIR%\nginx.exe" (
  echo [错误] 未找到 Nginx：%NGINX_DIR%\nginx.exe
  pause
  exit /b 1
)
if not exist "%ROOT%\backend\.env" copy "%ROOT%\backend\.env.example" "%ROOT%\backend\.env" >nul
if not exist "%ROOT%\frontend\dist\index.html" (
  echo [提示] 未找到前端构建产物，页面将无法打开。
  echo        请先执行：cd /d %ROOT%\frontend 然后 npm run build
)

echo [0/2] 清理可能残留的进程...
taskkill /IM nginx.exe /F >nul 2>&1
call :killport 8000

echo [1/2] 启动后端(8000)...
start "edu-backend" /D "%ROOT%\backend" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo        等待后端就绪...
set /a tries=0
:waitloop
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try{if((Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){exit 0}}catch{};exit 1" >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% lss 40 goto waitloop
echo [错误] 后端启动超时，请查看后端窗口日志。
pause
exit /b 1
:ready
echo        后端已就绪。

echo [2/2] 启动 Nginx...
pushd "%NGINX_DIR%"
"%NGINX_DIR%\nginx.exe" -p "%NGINX_DIR%" -c "%CONF%"
popd

echo.
echo 已启动：http://localhost:8081
echo 停止请运行：stop-all.bat
endlocal
exit /b 0

:killport
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1" ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
)
exit /b 0
