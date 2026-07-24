@echo off
echo ========================================
echo   SpiderOkx Build Script
echo ========================================

echo [1/4] Clean old files...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist spiderOkx.spec del spiderOkx.spec

echo [2/4] Install dependencies...
pip install pyinstaller openpyxl requests pandas playwright screeninfo -q

echo [3/4] Building...
pyinstaller --noconfirm --onedir --console --name "spiderOkx" --add-data "D:\_code\PlayWright.py;." --add-data "D:\_code\ReadFile.py;." --add-data "D:\_code\Config.py;." --add-data "D:\_code\Logger.py;." --hidden-import=logging.handlers --hidden-import=pandas --hidden-import=pandas._libs.tslibs.timedeltas --hidden-import=pandas._libs.tslibs.nattype --hidden-import=pandas._libs.tslibs.np_datetime --hidden-import=openpyxl --hidden-import=screeninfo --hidden-import=playwright --hidden-import=playwright.sync_api --hidden-import=playwright._impl D:\_code\spiderOkx\control.py

echo [4/4] Copy config files...
copy /y config.ini dist\spiderOkx\config.ini
copy /y *.xlsx dist\spiderOkx\ 2>nul

echo.
echo ========================================
echo   Build Complete!
echo   Output: dist\spiderOkx\
echo   Run: dist\spiderOkx\spiderOkx.exe
echo   Note: Edge browser required
echo ========================================
echo.
pause
