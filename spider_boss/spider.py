# coding='utf-8'
"""
    @作者：彭帅
    @邮箱：acheng6@126.com
    @时间：2026/6/1 21:56
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import logger, Playwright_
import os

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

def boss_login(account_id=1):
    try:
        logger.info('开始登录boss直聘....')
        url = 'https://www.zhipin.com/web/chat/index'
        ele = '(//a[text()="已交换微信"])[1]'

        key = f'login.cookie_{account_id}'
        Playwright_.login(url, ele, key, file=config_file)
        logger.info('boss直聘登录成功....')
        return True
    except Exception as e:
        logger.error(f'boss直聘登录失败：{e}')
        return False