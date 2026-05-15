chcp 65001
@echo off
cd /d "%~dp0"
d:\_code\python3.13.11\python.exe -m pip uninstall greenlet -y
d:\_code\python3.13.11\python.exe -m pip install greenlet
pause