import sys
from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

import logging
import os
import time
from logging.handlers import RotatingFileHandler

class Logger(object):
    level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL
    }

    def __init__(self, name='main', con_level='info', file_level='debug'):
        filename = os.path.join(os.path.dirname(__file__), 'logs', time.strftime('%Y-%m-%d') + '.log')

        # 创建一个logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        # 日志记录格式
        formater = logging.Formatter('[%(asctime)s %(name)s %(levelname)s]-->%(message)s')
        console_formater = logging.Formatter('%(message)s')

        # 创建一个handler，用于输出到控制台
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.level[con_level])
        console_handler.setFormatter(console_formater)

        # 创建一个日志回滚handler，用于写入日志文件
        # file_handler = logging.FileHandler(filename=filename, encoding='utf-8')
        file_handler = RotatingFileHandler(filename=filename, maxBytes=24*1024*1024, backupCount=10, encoding='utf-8')
        file_handler.setLevel(self.level[file_level])
        file_handler.setFormatter(formater)

        # 记录器设置处理器，给logger添加handler
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def debug(self, msg):
        self.logger.debug(msg)

    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)

    def critical(self, msg):
        self.logger.critical(msg)

logger = Logger('main')

if __name__ == '__main__':
    # debug info warning error critical
    logger.info("---测试开始---")
    logger.debug("---测试结束---")