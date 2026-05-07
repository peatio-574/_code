# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

from spider_gemi.Spider_gemi import login
from Logger import logger

def logins():
    """登录6个账号"""
    logger.info('登录6个账号')
    account = ['google1', 'google2', 'google3', 'google4', 'google5', 'google6']
    for key in account:
        logger.info(f'开始登录{key}账号')
        login(key, clear=True)

if __name__ == '__main__':
    logins()