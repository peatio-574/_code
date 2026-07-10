chcp 65001
@echo off
cd /d "%~dp0"
echo "安装python库"
d:\_code\python\python.exe -m pip install -r d:/_code/spider_ems/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

echo "安装playwright"
d:\_code\python\python.exe -m playwright install
pause