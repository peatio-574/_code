# -*- coding: utf-8 -*-
import sys
import time

from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from PlayWright import Playwright_, logger
import openpyxl

file = 'c:/_code/spider_panjiva/数据.xlsx'

wb = openpyxl.load_workbook(file)
ws = wb['Sheet1']



def panjiva_login():
    logger.info('开始登录盘踞网....')
    url = 'https://cn.panjiva.com/shipment_search?type=us_imports'
    ele = '//span[contains(@title,"User icon")]'
    key = 'login.panjiva_cookie'
    Playwright_.login(url, ele, key)
    logger.info('盘踞网登录成功....')



def qcc_login():
    logger.info('开始登录企查查....')
    url = 'https://www.qcc.com/'
    ele = '//div[contains(@class, "qcc-header-user-avatar")]'
    key = 'login.qcc_cookie'
    Playwright_.login(url, ele, key)
    logger.info('企查查登录成功....')



def tj_login():
    logger.info('开始登录探迹....')
    url = 'https://user.tungee.com/home'
    ele = '//img[@alt="头像"]'
    key = 'login.tj_cookie'
    Playwright_.login(url, ele, key)
    logger.info('探迹登录成功....')


if __name__ == '__main__':
    panjiva_login()
    qcc_login()
    tj_login()

