# -*- coding: utf-8 -*-
import random
import re
from Config import *
from PlayWright import Playwright_
import time
from Logger import logger

def login():
    """登录"""
    cookie = get_config_value('login', 'web_cookie')
    if cookie:
        Playwright_.add_cookie(eval(cookie))
    Playwright_.goto('https://www.taobao.com/')
    element = Playwright_.wait_for_selector('//div[@class="site-nav-user"]/a', timeout=3 * 60 * 1000)
    if not element:
        logger.error('3分钟内未登录！！！！')
        return False
    time.sleep(5)
    cookie_list = Playwright_.context.cookies()
    reuslt = {'web_cookie': str(cookie_list)}
    write_config_value('login', reuslt)  # cookie写入ini配置项
    return True

def search():
    """搜索，获取商品列表及初步信息
    返回list
    """
    keyword = input('请输入搜索关键字:')
    keyword += '女装'
    # 搜索
    Playwright_.input('//input[@aria-label="请输入搜索文字"]', keyword, enter=True)
    Playwright_.switch_to_page()
    count = Playwright_.get_count('//div[@id="content_wrapper"]/div/div') # 列表数量
    infos = list()
    for i in range(1, count+1):
        # 判断是否广告位
        flag_count = Playwright_.get_count(f'(//div[@id="content_wrapper"]/div/div)[{i}]/a')
        if flag_count:
            # 标题
            title = Playwright_.get_text(f'(//div[@id="content_wrapper"]/div/div)[{i}]//div[contains(@class, "title")]/span')
            # 店铺名
            shopname = Playwright_.get_text(f'(//div[@id="content_wrapper"]/div/div)[{i}]//span[contains(@class, "shopNameText")]')
            # 价格
            priceInt = Playwright_.get_text(f'(//div[@id="content_wrapper"]/div/div)[{i}]//div[contains(@class, "priceInt")]')
            priceFloat = Playwright_.get_text(f'(//div[@id="content_wrapper"]/div/div)[{i}]//div[contains(@class, "priceFloat")]')
            price = priceInt + priceFloat
            # 进入详情页
            href = Playwright_.get_attribute(f'(//div[@id="content_wrapper"]/div/div)[{i}]/a', 'href')
            info = {'title': title, 'shopname': shopname, 'price': price, 'href': href}
            infos.append(info)
    return infos

def get_details(info):
    """获取每件商品详情
    返回dict
    """
    Playwright_.goto(info['href'])
    # 销量
    sales = Playwright_.get_text('(//div[contains(@class, "itemInfo")]/span)[1]')
    # 轮播图
    turns = list()
    turn_count = Playwright_.get_count('//div[@class="thumbnail--TxeB1sWz "]/div/img')
    for turn in range(1, turn_count + 1):
        src = Playwright_.get_attribute(f'(//div[@class="thumbnail--TxeB1sWz "]/div/img)[{turn}]', 'src')
        turns.append(src)

    # 评价
    Playwright_.page.evaluate("window.scrollBy(0, 300)")  # 鼠标滑动
    Playwright_.click('//div[text()="查看全部评价"]')
    page_count = Playwright_.get_count('(//div[contains(@class, "comments")])[2]/div')
    commit  = page_count - 1

    extra = Playwright_.get_count(f'(//div[contains(@class, "comments")])[2]/div[{page_count}]/div')
    if extra == 1:  # 评价较多的情况
        extra = re.findall(r'\d+', extra)[0]
        commit += int(extra)
    Playwright_.click('//div[contains(@class, "closeWrap")]')

    # 图片
    Playwright_.click('//span[text()="图文详情"]')
    picture_count = Playwright_.get_count('//div[@id="imageTextInfo-content"]/div/div')
    pictures = list()
    for pic_id in range(1, picture_count + 1):
        img = Playwright_.get_attribute(f'(//div[@id="imageTextInfo-content"]/div/div)[{pic_id}]/img', 'data-src')
        if not img:
            img = Playwright_.get_attribute(f'(//div[@id="imageTextInfo-content"]/div/div)[{pic_id}]/img', 'src')
        pictures.append(img)
    info['turns'] = turns
    info['sales'] = sales
    info['commit'] = commit
    info['pictures'] = pictures
    return info

def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    content = now + '淘宝爬虫'
    logger.info(content.center(100, '='))

    logger.info('开始登录....')
    login()

    while True:
        data = list()
        infos = search()
        for info in infos:
            logger.info(f'开始获取{info["title"]}详细信息')
            info = get_details(info)
            data.append(info)
            logger.info(str(info))
            sec = random.randint(50,800)
            logger.info(f'间歇{sec}秒再进行抓取')
            time.sleep(sec)

if __name__ == '__main__':
    main()