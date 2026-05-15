# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

from Logger import logger
from PIL import ImageGrab
import time
from PlayWright import Playwright_
from Config import get_config_value, write_config_value
import ctypes

def read_csv(file):
    """读取csv文件"""
    try:
        with open(file, 'r', encoding='cp949') as f:
            file_content = f.readlines()
        logger.info('%s文件读取成功' % file)
        result = list()
        for line in range(len(file_content)):
            line_info = (line+1, file_content[line].strip())
            result.append(line_info)
        logger.info(f'共读取到{len(result)}条提示词')
        return result
    except Exception as e:
        logger.error('%s文件读取失败：%s' % (file, e))
        return None

def login(key='google1', clear=False):
    cookie = get_config_value('login', key)
    if cookie:
        Playwright_.add_cookie(eval(cookie), clear=clear)
    else:
        Playwright_.clear_cookie()
    url = 'https://gemini.google.com/app'
    Playwright_.goto(url)
    time.sleep(5)
    element = Playwright_.wait_for_selector('//span[@class="gb_ge"]', timeout=3 * 60 * 1000, way='xpath')
    if not element:
        return False
    cookie_list = Playwright_.context.cookies()
    write_config_value('login', {key: str(cookie_list)})
    return True

def clean():
    """清空粘贴板"""
    user32 = ctypes.windll.user32
    user32.OpenClipboard(0)
    user32.EmptyClipboard()
    user32.CloseClipboard()

def execute(word_info, account, first=False):
    try:
        login(account, clear=first)

        logger.info('开始执行提示词：%s' % word_info[1])

        logger.info('勾选pro模式')
        Playwright_.click('//mat-icon[@fonticon="keyboard_arrow_down"]', force=True)
        Playwright_.click('//span[text()=" Pro "]')
        if Playwright_.exit:
            return False

        logger.info('勾选图片生成')
        Playwright_.click('//div[contains(text(), "Create image")]', force=True)

        logger.info('输入提示词')
        Playwright_.input('//div[@data-placeholder="Describe your image"]', word_info[1], enter=True)
        logger.info('等待图片生成....')


        location = '//model-response//mat-icon[@fonticon="content_copy"]'
        Playwright_.wait_for_selector(location, timeout=3 * 60 * 1000)


        picture_count = Playwright_.get_count(location)
        logger.info(f'图片数量：{picture_count}')

        if picture_count == 0:
            file = f'd:/_code/photo/error/{time.strftime("%Y%m%d%H%M%S")}_{word_info[0]}_error.png'
            Playwright_.screenshot(file=file)
            logger.info(f'提示词未生成图片，请查看截图：{file}')
            return False
        for i in range(1, picture_count+1):
            clean()  # 清空粘贴板

            logger.info(f'开始下载第{i}张图片')
            Playwright_.click(f'({location})[{i}]')
            img = ImageGrab.grabclipboard()

            if not img:
                file = f'd:/_code/photo/error/{time.strftime("%Y%m%d%H%M%S")}_{word_info[0]}_{i}_error.png'
                Playwright_.page.screenshot(path=file)
                logger.error(f'图片保存失败，请查看截图：{file}')
                continue
            file = f'd:/_code/photo/{time.strftime("%Y%m%d%H%M%S")}_{word_info[0]}_{i}.png'
            img.save(file)
            logger.info(f'下载{file}图片下载完成')
            time.sleep(10)
        return  True
    except Exception as e:
        logger.error(f'提示词运行失败：{word_info[1]}：{e}')
        return False

def main():
    account = ['google1', 'google2', 'google3', 'google4', 'google5', 'google6']

    file = get_config_value('login', 'file')
    words = read_csv(file)
    if not words:
        logger.error('未读取到任何提示词数据')
        return

    # 计算每个账号需要处理的数据量
    total_words = len(words)
    words_per_account = total_words // 6
    remainder = total_words % 6

    start_index = 0
    for i, account in enumerate(account):
        # 前remainder个账号多处理一条数据
        if i < remainder:
            end_index = start_index + words_per_account + 1
        else:
            end_index = start_index + words_per_account

        # 获取当前账号要处理的数据
        account_words = words[start_index:end_index]

        logger.info(f'账号 {account} 将处理 {len(account_words)} 条数据 (索引 {start_index} 到 {end_index - 1})')

        # 为当前账号执行所有分配的任务
        first = True  # 第一个任务需要清除cookie
        for word in account_words:
            execute(word, account, first=first)
            first = False  # 后续任务不需要清除cookie

        start_index = end_index

        logger.info(f'账号 {account} 已完成所有分配的任务')


if __name__ == '__main__':
    main()
