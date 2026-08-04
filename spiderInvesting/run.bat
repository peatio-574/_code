@echo off
echo ========================================
echo   SpiderInvesting Build Script
echo ========================================

echo [1/4] Clean old files...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist Investing.spec del Investing.spec

echo [2/4] Install dependencies...
pip install pyinstaller playwright screeninfo requests -q

echo [3/4] Building...
pyinstaller --noconfirm --onedir --console --name "Investing" --add-data "D:\_code\PlayWright.py;." --add-data "D:\_code\Config.py;." --add-data "D:\_code\Logger.py;." --hidden-import=logging.handlers --hidden-import=screeninfo --hidden-import=playwright --hidden-import=playwright.sync_api --hidden-import=playwright._impl D:\_code\spiderInvesting\Investing.py

echo [4/4] Copy data files...
copy /y spiderInvesting\*.csv dist\Investing\ 2>nul

echo.
echo ========================================
echo   Build Complete!
echo   Output: dist\Investing\
echo   Run: dist\Investing\Investing.exe
echo   Note: Edge browser required
echo ========================================
echo.
pause
