# -*- coding: utf-8 -*-
import sys

from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from ReadFile import ReadData
import openpyxl
from Logger import logger
from PlayWright import Playwright_, get_config_value
import time
import random
import os

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

file = get_config_value('login', 'file', file=config_file)

wb = openpyxl.load_workbook(file)
ws = wb['商品评论']

exist_data = ReadData.read_xlsx_col(file, sheetname='商品评论')['唯一编号']


def login():
    """京东登录"""
    logger.info('开始登录京东....')
    url = 'https://www.jd.com/'
    ele = '//li[@id="ttbar-login-2024"]/div[1]'
    key = 'login.jd_cookie'
    Playwright_.login(url, ele, key, file=config_file)
    logger.info('京东登录成功')
    return True


def get_title(url):
    """获取商品标题"""
    try:
        Playwright_.goto(url)
        time.sleep(3)
        title = Playwright_.get_text('//span[@class="sku-title-name"]')
        return title
    except Exception as e:
        logger.error(f'获取商品标题失败：{e}')
        return False


def get_page_comments(product_id, title, bad=False):
    """获取商品单页评论"""
    global exist_data
    page_comments = []
    try:
        # 获取评论数量
        comment_count_ele = '//div[@data-testid="virtuoso-item-list"]/div'
        comment_count = Playwright_.get_count(comment_count_ele)

        comment_count = min(comment_count, 6)  # 每次最多爬取5条数据
        for comement_ in range(1, comment_count):
            # 评论ID
            comment_id_ele = f'({comment_count_ele})[{comement_}]'
            known_size = Playwright_.get_attribute(comment_id_ele, 'data-known-size')

            # 评论人名
            comment_name_ele = f'{comment_id_ele}//span[@class="jdc-pc-rate-card-nick"]'
            comment_name = Playwright_.get_text(comment_name_ele)

            # 唯一编号：：product_id + comment_name + data_known_size
            unique_id = product_id + '-' + comment_name + '-' + known_size
            unique_id = 'bad_' + unique_id if bad else unique_id
            if unique_id in exist_data:
                logger.info(f'已爬取过该条数据，唯一编号：{unique_id}')
                continue

            # 商品型号
            product_type_ele = f'{comment_id_ele}//span[@class="info"]'
            product_type_count = Playwright_.get_count(product_type_ele)
            product_type = Playwright_.get_text(product_type_ele) if product_type_count > 0 else ''

            # 评论时间
            comment_time_ele = f'{comment_id_ele}//span[@class="date list"]'
            comment_time = Playwright_.get_text(comment_time_ele)

            # 评论内容
            comment_text_ele = f'{comment_id_ele}//span[@class="jdc-pc-rate-card-main-desc"]'
            comment_text = Playwright_.get_text(comment_text_ele)

            # 点赞数
            like_count_ele = f'({comment_id_ele}//span[@class="jdc-count"])[last()]'
            like_count = Playwright_.get_text(like_count_ele)
            like_count = '0' if like_count == '有用' else like_count

            comment = [product_id, unique_id, title, comment_time, comment_name, product_type, comment_text, like_count]
            page_comments.append(comment)
            exist_data.append(unique_id)
            logger.info(f'第{len(exist_data)}条评论：{comment[:-2]}')
    except Exception as e:
        logger.error(f'获取商品{product_id}的评论异常：{e}')
    return page_comments


def get_tab_info(rowid, file):
    """获取tab信息"""
    ws_ = wb['商品链接']
    tab_info = ''
    tabs_ele = '//div[contains(@class, "jdcc-custom")]/div/div'
    tabs_count = Playwright_.get_count(tabs_ele)  # tab数量
    for tab_ in range(1, tabs_count + 1):
        tab_ele = f'({tabs_ele})[{tab_}]/span'
        tab_count = Playwright_.get_count(tab_ele)
        tab_text = ''
        for _tab_ in range(1, tab_count + 1):
            _tab_ele = f'({tab_ele})[{_tab_}]'
            tab_text += Playwright_.get_text(_tab_ele)  # tab文案
        tab_info += tab_text + ','
    tab_info = tab_info[:-1]
    ws_.cell(row=rowid, column=2, value=tab_info)
    wb.save(file)


def spider_product(product_id, title, rowid, bad=False):
    global ws, wb, file, exist_data

    row_flag = product_id if not bad else 'bad_' + product_id
    current_count = len([i for i in exist_data if i.startswith(row_flag)])
    text = '' if not bad else '差评'

    try:
        if not bad:
            # 滚动页面，查看评价
            Playwright_.page.keyboard.press('PageDown')
            time.sleep(2)
            logger.info('点击查看更多')
        else:
            # 切换差评
            Playwright_.click('//div[@class="applause-rate"]')

        Playwright_.click('//div[@class="applause-rate golden"]')  # 聚焦评论区
        time.sleep(10)
        if not bad:
            get_tab_info(rowid, file)

        roll_time = 0  # 滚动次数
        limit_roll_time = 6
        limit_count = 300 if not bad else 500

        invalid_roll_time = 0  # 无效滚动次数
        while True:
            # 爬取数据足够就退出
            if current_count >= limit_count:
                logger.info(f'已爬取{current_count}条{text}评论，退出当前商品评论爬取')
                return True

            # 获取评论
            page_comments = get_page_comments(product_id, title)

            current_count += len(page_comments)
            logger.info(f'{product_id}商品，已爬取{current_count}条{text}数据')
            for row in page_comments:
                ws.append(row)
                wb.save(file)

            # 连续6次未获取到新数据就退出
            if invalid_roll_time == limit_roll_time:  # 滚动次数达到6次，判断是否有新数据
                logger.info(f'已连续滚动{limit_roll_time}次未获取到新数据，退出当前商品{text}评论爬取')
                return True


            # 滚动页面
            Playwright_.page.mouse.move(500, 500)
            down_size = random.randint(500, 900)
            Playwright_.page.mouse.wheel(0, down_size)  # 向下滚动

            # Playwright_.page.keyboard.press('PageDown')
            roll_time += 1

            invalid_roll_time = 0 if page_comments else invalid_roll_time + 1

            # 睡眠：有新数据睡眠20-30s，无新数据睡眠5-20s
            sleep_sec = random.randint(5, 20)  # if not page_comments else random.randint(20, 30)
            logger.info(f'滚动第{roll_time}次，睡眠{sleep_sec}秒，当前无效滚动次数：{invalid_roll_time}')
            time.sleep(sleep_sec)
    except Exception as e:
        logger.error(f'爬取商品{product_id}的{text}评论异常：{e}')
        return False



def main():
    urls = ReadData.read_xlsx_col(file)['商品链接']
    for rowid, url in enumerate(urls, start=2):
        time.sleep(3)
        product_id = url.split('.html')[0].split('/')[-1]
        logger.info(f'开始爬取商品：{product_id}数据')
        if not login():
            logger.error('京东登录失败')
            continue
        title = get_title(url)
        if not title:
            logger.error(f'获取商品{product_id}的标题失败')
            continue
        spider_product(product_id, title, rowid)
        spider_product(product_id, title, rowid, bad=True)


if __name__ == '__main__':
    main()