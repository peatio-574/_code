# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger
import time
import os

def tb_login(shop_id=1):
    try:
        logger.info('开始登录千牛....')
        url = 'https://myseller.taobao.com/home.htm/QnworkbenchHome/'
        ele = '//span[contains(text(),"首页")]'
        key = f'login.tb_cookie{shop_id}'

        Playwright_.login(url, ele, key)
        logger.info('千牛登录成功....')
        return True
    except Exception as e:
        logger.error(f'千牛登录失败：{e[:50]}')
        return False


def main_(account_id=1):
    title = f'========================开始爬取千牛第{account_id}个店铺======================='
    logger.info(title)
    end = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    start = f"{end[:-3]}-01"
    dirname = 'd:/_code/spider_account/数据'

    login = tb_login(account_id)
    if not login:
        return False
    shop_name = search(start, end)

    filename = f'{shop_name}店铺{end}明细.xlsx'
    filename = os.path.join(dirname, filename)

    time.sleep(10)

    logger.info(f'{shop_name}店铺开始导出明细....')
    status = 0
    for roll in range(1, 6):
        logger.info(f'第{roll}次导出明细....')
        Playwright_.click('//span[text()="导出"]')
        status = save(filename)
        if status:
            break

        status = download(filename)
        if status:
            break
    text = f'✅️ {shop_name}明细数据下载成功：{filename}' if status else f'❌️ {shop_name}明细数据下载失败'
    logger.info(text)
    if status:
        deal_data(shop_name, filename)
    Playwright_.clear_cookie()
    return True