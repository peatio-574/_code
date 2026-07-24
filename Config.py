# -*- coding: utf-8 -*-
import sys
import os

if getattr(sys, 'frozen', False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _base)


import configparser

config_file = os.path.join(_base, 'config.ini')

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
