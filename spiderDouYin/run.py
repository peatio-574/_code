# -*- coding: utf-8 -*-
import sys
import time

from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))



from PlayWright import logger, Playwright_
import os

configFile = os.path.join(os.path.dirname(__file__), 'config.ini')

def douYinLogin(account):
    url = 'https://www.douyin.com/user/self'
    ele = '(//div[@class="arXOQVuK"]/../div)[last()]/div/a'
    key = f'login.douYinCookie{account}'
    try:
        loginStatus = Playwright_.login(url, ele, key, file=configFile)
        if loginStatus:
            logger.info(f'✅️ 第{account}个抖音账号登录成功')
        else:
            logger.error(f'❌ 第{account}个抖音账号登录失败，未获取到元素')
    except Exception as e:
        logger.error(f'❌ 第{account}个抖音账号登录失败：{e}')


def control():
    douYinLogin(1)
    url = 'https://www.douyin.com/user/MS4wLjABAAAADwbAaYXwhePGP0u5L0TQnjZGZElOyQFId_V1QjHsvg0?from_tab_name=main'
    Playwright_.goto(url)
    time.sleep(10)


    Playwright_.click('//div[@id="tooltip"]/button/span')
    Playwright_.click('//span[text()="举报账号"]')
    Playwright_.click('//div[text()="举报原因"]/../../div[2]/div[1]/div')

    text = Playwright_.get_text('//div[text()="举报原因"]/../../div[2]/div[1]/span')
    Playwright_.input('//div[@class="report-text"]/textarea', text)




if __name__ == '__main__':
    control()