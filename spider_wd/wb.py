# -*- coding: utf-8 -*-
import sys

import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger, get_config_value
import os
import requests
import time
from openpyxl import load_workbook

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

def wb_login():
    try:
        logger.info('开始登录微博....')
        url = 'https://weibo.com/'
        ele = '//div[@class="woo-box-flex woo-tab-nav woo-tab-nav"]/a[5]'
        key = 'login.wb_cookie'
        Playwright_.login(url, ele, key, file=config_file)
        logger.info('微博登录成功....')
        return True
    except Exception as e:
        logger.error(f'微博登录失败：{e}')
        return False


filename = os.path.join(os.path.dirname(__file__), '评价数据.xlsx')
wb = load_workbook(filename)
ws = wb.active

max_id = 0
l = 0
while True:
    if max_id == 0:
        url = f'https://weibo.com/ajax/statuses/buildComments?is_reload=1&id=5175334749344497&is_show_bulletin=2&is_mix=0&count=10&uid=7516679696&fetch_level=0&locale=zh-CN'
    else:
        url = f'https://weibo.com/ajax/statuses/buildComments?flow=0&is_reload=1&id=5175334749344497&is_show_bulletin=2&is_mix=0&max_id={max_id}&count=20&uid=7516679696&fetch_level=0&locale=zh-CN'
    headers = {
        'user-agent': get_config_value('login', 'user_agent', file=config_file),
        'cookie': get_config_value('login', 'wb_cookie_api', file=config_file),
        'referer': 'https://weibo.com/7516679696/PvBNEDcVH?refer_flag=1001030103_',
        'x-requested-with': 'XMLHttpRequest',
        'x-xsrf-token': 'BHG6TIiy6PvQqu1mlnxfYIx4',

    }

    info = requests.get(url, headers=headers).json()
    print(info['max_id'])
    for item in info['data']:
        row = [item['text_raw']]
        print(row)
        ws.append(row)
    wb.save(filename)
    max_id = info['max_id']
    if info['max_id'] == 0:
        break

    time.sleep(2)



# if __name__ == '__main__':
#     # wb_login()