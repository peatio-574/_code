# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# 把项目根目录  加入Python路径
sys.path.append(str(Path(__file__).parent))


import configparser
import os

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

class CaseSensitiveConfig(configparser.ConfigParser):
    def optionxform(self, optionstr):
        # 覆盖默认转小写逻辑，原样返回key，保留大小写
        return optionstr

def get_config_value(section='login', option='order_cookie', file=None):
    """获取配置项"""
    file = config_file if not file else file
    Config = CaseSensitiveConfig(interpolation=None)
    Config.read(file, encoding='utf-8')
    return Config.get(section, option, fallback="")

def write_config_value(section='login', option: dict = None, file=None):
    """写入配置项"""
    file = config_file if not file else file
    if option is None:
        option = {'cookie': get_config_value('login', 'order_cookie')}
    Config = CaseSensitiveConfig(interpolation=None)
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
