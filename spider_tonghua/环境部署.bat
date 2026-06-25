chcp 65001
@echo off
cd /d "%~dp0"
echo "安装python库"
d:\_code\python\python.exe -m pip install -r d:/_code/spider_tonghua/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
pause