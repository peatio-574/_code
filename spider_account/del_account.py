# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))



from Config import write_config_value, os

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')



info_ = {
    '小红书': {
        '1': 'xhs_cookie_1',
        '2': 'xhs_cookie_2',
        '3': 'xhs_cookie_3',
        '4': 'xhs_cookie_4',
        '5': 'xhs_cookie_5',
        '6': 'xhs_cookie_6',
        '7': 'xhs_cookie_7',
        '8': 'xhs_cookie_8',
        '9': 'xhs_cookie_9',
        '10': 'xhs_cookie_10',
        '11': 'xhs_cookie_11',
        '12': 'xhs_cookie_12',
    },
    '抖店': {
        '1': 'dd_cookie_1',
        '2': 'dd_cookie_2',
        '3': 'dd_cookie_3',
        '4': 'dd_cookie_4',
        '5': 'dd_cookie_5',
        '6': 'dd_cookie_6',
    },
    '微店': {
        '1': 'wd_cookie_1',
        '2': 'wd_cookie_1',
        '3': 'wd_cookie_1',
        '4': 'wd_cookie_1',
        '5': 'wd_cookie_1',
        '6': 'wd_cookie_2',
        '7': 'wd_cookie_2',
        '8': 'wd_cookie_2',
        '9': 'wd_cookie_2',
        '10': 'wd_cookie_2',
        '11': 'wd_cookie_3',
        '12': 'wd_cookie_3',
    },
    '淘宝': {
        '1': 'tt_cookie_1',
        '2': 'tt_cookie_2',
        '3': 'tt_cookie_3',
        '4': 'tt_cookie_4',
        '5': 'tt_cookie_5',
        '6': 'tt_cookie_6',
    },
    '拼多多': {
        '1': 'pdd_cookie_1',
        '2': 'pdd_cookie_2',
        '3': 'pdd_cookie_3',
        '4': 'pdd_cookie_4',
        '5': 'pdd_cookie_5',
        '6': 'pdd_cookie_6',
    },
}


info = input('请输入删除的平台及账号（如：抖店 3）：')

shopname, ids = info.split(' ')

new = {info_[shopname][ids]: None, f'{info_[shopname][ids]}_api': None}
config_date = write_config_value('login', new, file=config_file)