# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))


import configparser

config_file = 'd:/_code/config.ini'

def get_config_value(section='login', option='order_cookie', file=None):
    """获取配置项"""
    file = config_file if not file else file
    Config = configparser.ConfigParser(interpolation=None)
    Config.read(file, encoding='utf-8')
    return Config.get(section, option, fallback="")

def write_config_value(section='login', option: dict = None, file=None):
    """写入配置项"""
    file = config_file if not file else file
    if option is None:
        option = {'cookie': get_config_value('login', 'order_cookie')}
    Config = configparser.ConfigParser(interpolation=None)
    Config.read(file, encoding='utf-8')
    if section not in Config.sections():
        Config.add_section(section)
    for key, value in option.items():
        if isinstance(value, (dict, list)):
            Config[section][key] = str(value)
        else:
            Config[section][key] = str(value) if value is not None else ''
    with open(file, mode='w', encoding='utf-8') as f:
        Config.write(f)
