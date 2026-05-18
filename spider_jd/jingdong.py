# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from ReadFile import ReadData
import openpyxl
from Logger import logger
from PlayWright import Playwright_
import re
import time
import random


file = 'd:/_code/spider_jd/京东手机评论爬取.xlsx'
exist_data = ReadData.read_xlsx_col(file)
column = exist_data['评论人']
column_ = exist_data['机型']
comtent = exist_data['评论内容']
exist_data = [comtent[i][:10]+ column[i]+ column_[i] for i in range(len(column))]

exist_count = len(exist_data)  # 已爬取数据行数
current_row_id = exist_count + 1  # 当前行号
current_valid_id = 0  # 当前有效数据条数

wb = openpyxl.load_workbook(file)
ws = wb['Sheet1']


def login():
    """京东登录"""
    logger.info('登录京东....')
    url = 'https://www.jd.com/'
    ele = '//li[@id="ttbar-login-2024"]/div[1]'
    key = 'login.jd_cookie'
    Playwright_.login(url, ele, key)
    logger.info('京东登录成功')


def get_info(phone_id):
    global exist_data  # 已爬取数据
    global current_row_id  # 当前行号
    global current_valid_id  # 当前有效行数
    global file

    flag = False  # 标记是否有新数据

    # 获取评论数量
    comment_count_ele = '//div[@data-testid="virtuoso-item-list"]/div'
    comment_count = Playwright_.get_count(comment_count_ele)

    comment_count = min(comment_count, 6)  # 每次最多爬取5条数据
    for comement_ in range(1, comment_count):
        # 商品型号
        phone_type_ele = f'({comment_count_ele})[{comement_}]//span[@class="info"]'
        phone_type = Playwright_.get_text(phone_type_ele)
        
        # 评论人名
        comment_name_ele = f'({comment_count_ele})[{comement_}]//span[@class="jdc-pc-rate-card-nick"]'
        comment_name = Playwright_.get_text(comment_name_ele)

        # 评论时间
        comment_time_ele = f'({comment_count_ele})[{comement_}]//span[@class="date list"]'
        comment_time = Playwright_.get_text(comment_time_ele)

        # 评论内容
        comment_text_ele = f'({comment_count_ele})[{comement_}]//span[@class="jdc-pc-rate-card-main-desc"]'
        comment_text = Playwright_.get_text(comment_text_ele)

        # 评论ID：评论人名+型号作为唯一标识，避免重复爬取，
        comment_id = comment_text[:10] + comment_name + phone_type
        if comment_id in exist_data:
            logger.info(f'已爬取过该条数据，评论ID：{comment_id}')
            continue

        # 写入数据
        row_number = current_row_id + 1
        ws.cell(row=row_number, column=1, value=comment_time)
        ws.cell(row=row_number, column=2, value=comment_name)
        ws.cell(row=row_number, column=3, value=phone_type)
        ws.cell(row=row_number, column=4, value=comment_text)
        ws.cell(row=row_number, column=5, value=phone_id)
        ws.cell(row=row_number, column=6, value='352空气净化器 家用除甲醛异味细菌病毒雾霾过敏原认证 甲醛精准数显 双塔式大空间Z90 Z90')
        wb.save(file)

        current_valid_id += 1
        current_row_id += 1
        logger.info(f'第{current_valid_id}条有效数据，已保存第 {current_row_id} 行，合计条数：{current_row_id-1}，评论ID：{comment_id}')

        flag = True
        exist_data.append(comment_id)
    return 1 if flag else 0
        
        
def spider_url(url):
    # 登录
    login()
    
    # 访问商品详情页
    Playwright_.goto(url)
    phone_id = re.findall(r'\d+', url)[0]

    logger.info(f'开始{url}爬取数据，初始数据数量：{exist_count}')
    
    # 滚动页面，查看评价
    Playwright_.page.keyboard.press('PageDown')
    time.sleep(2)
    logger.info('点击查看更多')
    Playwright_.click('//div[@class="applause-rate golden"]')
    time.sleep(5)
    
    flag = 0  # 是否有新数据
    roll_time = 0  # 滚动次数
    # limit_roll_time = 6
    while True:
        # 爬取数据足够就退出，获取连续6次未获取到新数据就退出
        if exist_count == 1000:
            logger.info('已爬取所有评论')
            return True

        # 获取评论
        flag += get_info(phone_id)
        # 滚动页面
        down_size = random.randint(900, 1500)
        Playwright_.page.mouse.wheel(0, down_size)  # 向下滚动
        roll_time += 1


        # if roll_time % limit_roll_time == 0:
        #     if flag == 0:
        #         logger.info(f'已连续滚动{limit_roll_time}次未获取到新数据，退出')
        #         return False
        #     flag = 0

        # 睡眠
        if flag != 0:

            sleep_sec = random.randint(15, 20)
        else:
            sleep_sec = random.randint(1, 3)
        logger.info(f'已滚动{roll_time}次，睡眠{sleep_sec}秒')
        time.sleep(sleep_sec)
        flag = 0


if __name__ == '__main__':
    urls = [
        # 'https://item.jd.com/100331677354.html',
        # 'https://item.jd.com/100335522888.html',
        # 'https://item.jd.com/100251446817.html',
        # 'https://item.jd.com/100334589938.html',
        # 'https://item.jd.com/100251526387.html',
        # 'https://item.jd.com/100288840752.html',
        # 'https://item.jd.com/100331677404.html',
        # 'https://item.jd.com/100333436660.html',
        # 'https://item.jd.com/100307090484.html',
        # 'https://item.jd.com/100164212291.html',
        # 'https://item.jd.com/100300133968.html',
        # 'https://item.jd.com/100232754967.html',
        # 'https://item.jd.com/100249883337.html',
        # 'https://item.jd.com/100342703604.html',
        # 'https://item.jd.com/100224133343.html',
        # 'https://item.jd.com/100307090484.html',
        # 'https://item.jd.com/100257288238.html',
        # 'https://item.jd.com/100278264242.html',
        # 'https://item.jd.com/100251446863.html',
        # 'https://item.jd.com/10187587238729.html',
        # 'https://item.jd.com/100257288238.html',
        # 'https://item.jd.com/10199734655343.html',
        # 'https://item.jd.com/10196624110223.html',
        # 'https://item.jd.com/100219670879.html',
        # 'https://item.jd.com/10082141614576.html',
        # 'https://item.jd.com/100250023001.html',
        # 'https://item.jd.com/100256502833.html',
        # 'https://item.jd.com/100041689524.html',
        # 'https://item.jd.com/100303346690.html',
        # 'https://item.jd.com/100186787559.html',
        # 'https://item.jd.com/100324659982.html',
        # 'https://item.jd.com/100324470246.html',
        # 'https://item.jd.com/100232839373.html',
        # 'https://item.jd.com/10215101425662.html',
        # 'https://item.jd.com/100246101314.html',
        # 'https://item.jd.com/100252256925.html',
        # 'https://item.jd.com/10155241534544.html',
        # 'https://item.jd.com/10216974212917.html',
        'https://item.jd.com/10114677013390.html',
        # 'https://item.jd.com/100183353902.html',
        # 'https://item.jd.com/100307090484.html',
    ]

    for url in urls:
        spider_url(url)
        # time.sleep(120)

