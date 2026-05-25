chcp 65001
@echo off
cd /d "%~dp0"
d:\_code\python\python.exe -m pip uninstall playwright -y
d:\_code\python\python.exe -m pip install playwright
pause