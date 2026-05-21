chcp 65001
@echo off
cd /d "%~dp0"
echo "安装python库"
d:\_code\python3.13.11\python.exe -m pip install -r d:/_code/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
echo "安装浏览器驱动"
d:\_code\python3.13.11\python.exe -m playwright install
pause