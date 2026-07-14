# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))



from PlayWright import logger, Playwright_
import os

configFile = os.path.join(os.path.dirname(__file__), 'config.ini')

def douYinLogin(account):
    url = 'https://www.douyin.com/user/self'
    ele = ''
    key = f'login.douYinCookie{account}'
    try:
        loginStatus = Playwright_.login(url, ele, key, file=configFile)
        if loginStatus:
            logger.info(f'✅️ 第{account}个抖音账号登录成功')
        else:
            logger.error(f'❌ 第{account}个抖音账号登录失败，未获取到元素')
    except Exception as e:
        logger.error(f'❌ 第{account}个抖音账号登录失败：{e}')


