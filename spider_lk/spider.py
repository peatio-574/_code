# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger, get_config_value
import os

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

def lk_login():
    """抖音快客登录"""
    logger.info('=' * 80)
    logger.info('开始登录抖音快客....')
    url = 'https://life.douyin.com/p/liteapp/leads_life/sales/list'
    ele = '//div[contains(@class,"Profile-index-module__title--")]'
    key = 'login.lk_cookie'
    try:
        Playwright_.login(url, ele, key, file=config_file)
        logger.info('✓ 抖音快客登录成功')
        return True
    except Exception as e:
        logger.error(f'✗ 抖音快客登录失败：{e}')
        return False

def get_lk_data():
    """获取抖音快客数据"""

    ele = '//tbody/tr[1]/td[3]/div/div[1]/span'
    if '**' in Playwright_.get_text(ele):
        logger.info('抖音快客号码处于隐藏状态，进行点击')
        Playwright_.click('(//tbody/tr[1]/td[3]/div/div[1]/*)[2]')
        time.sleep(2)
        Playwright_.click('//div[@class="cursor-pointer mr-1 flex items-center"]')
        time.sleep(3)
    row_ele = '//tbody/tr'
    row_count = Playwright_.get_count(row_ele)
    rows = []
    for i in range(1, row_count + 1):
        username = Playwright_.get_text(f'{row_ele}[{i}]/td[2]//a//div')
        phone = Playwright_.get_text(f'{row_ele}[{i}]/td[3]/div/div[1]/span')
        city = Playwright_.get_text(f'{row_ele}[{i}]/td[3]/div/div[2]//div')
        city = city.split('：')[1]
        date = Playwright_.get_text(f'{row_ele}[{i}]/td[6]')
        rows.append({'username': username, 'phone': phone, 'city': city, 'date': date})
    return rows

def mk_login():
    """麦客登录"""
    logger.info('=' * 80)
    logger.info('开始登录麦客....')
    url = 'https://mikeauth.com/login.php?prd=1&rg=1&d=form.php#/submit?id=200175265'
    ele = '//div[contains(@class,"Profile-index-module__title--")]'
    key = 'login.mk_cookie'
    try:
        Playwright_.login(url, ele, key, file=config_file)
        logger.info('✓ 麦客登录成功')
        return True
    except Exception as e:
        logger.error(f'✗ 麦客登录失败：{e}')
        return False



if __name__ == '__main__':
    lk_login()
    get_lk_data()
    time.sleep(10000)