# coding='utf-8'
"""
    @作者：彭帅
    @邮箱：acheng6@126.com
    @时间：2026/5/31 17:03
"""
import os
from PlayWright import Playwright_, logger

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

def login():
    try:
        logger.info('开始登录')
        url = 'http://990.com'
        url = 'https://204.236.15.51:58888/#/'
        ele = '//div[@class="account"]/ul/li[2]/span'
        key = f'login.cookie'

        Playwright_.login(url, ele, key, file=config_file)
        logger.info('登录成功....')
        return True
    except Exception as e:
        logger.error(f'登录失败：{e}')
        return False


if __name__ == '__main__':
    import time
    while True:
        login()
        print('休眠3小时')
        time.sleep(60 * 60 * 3)