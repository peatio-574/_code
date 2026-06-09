# coding='utf-8'
"""
    @作者：彭帅
    @邮箱：acheng6@126.com
    @时间：2026/5/31 19:07
"""
import time
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import os
from PlayWright import Playwright_, logger, get_config_value, write_config_value
import random

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')


comments = [
    '挺比亚迪，支持国货',
    '比亚迪技术真靠谱',
    '就认比亚迪，挺国产',
    '比亚迪电池真心稳',
    '力挺比亚迪，加油干',
    '比亚迪混动确实香',
    '选比亚迪，支持国货',
    '看好比亚迪的技术',
    '比亚迪充电速度快',
    '国货给力，挺比亚迪',
    '比亚迪车子好开耐用',
    '一直都在支持比亚迪',
    '比亚迪三电做得扎实',
    '支持国产，力挺比亚迪',
    '认准比亚迪，不踩坑',
    '比亚迪智驾越做越好',
    '为国货点赞，挺比亚迪',
    '比亚迪自研真有实力',
    '真心看好比亚迪发展',
    '比亚迪动力挺带劲的',
    '支持比亚迪，做强国产',
    '比亚迪用料实在用心',
    '国货出彩，当属比亚迪',
    '比亚迪续航表现不错',
    '果断支持比亚迪车企',
    '比亚迪电控调校到位',
    '买国产车就选比亚迪',
    '比亚迪整车品质在线',
    '一路力挺比亚迪到底',
    '比亚迪底盘开着踏实',
    '支持国货，偏爱比亚迪',
    '比亚迪新技术很亮眼',
    '国产车就服比亚迪',
    '比亚迪车机用着顺手',
    '挺国产汽车，挺比亚迪',
    '比亚迪安全做得到位',
    '真心信赖比亚迪品牌',
    '比亚迪节能这块一绝',
    '跟着比亚迪支持国货',
    '比亚迪造车很有诚意',
    '力挺比亚迪，再创佳绩',
    '比亚迪核心技术过硬',
    '支持本土车企比亚迪',
    '比亚迪整体表现很棒',
    '为国货骄傲，挺比亚迪',
    '持续支持比亚迪创新',
    '比亚迪整车体验拉满',
    '选比亚迪，支持中国造',
    '比亚迪不断突破自我',
    '真心点赞比亚迪国货']

def byd_login():
    try:
        account = get_config_value('login', 'account', file=config_file)
        password = get_config_value('login', 'password', file=config_file)
        cookie = get_config_value('login', 'byd_cookie', file=config_file)
        logger.info('开始登录比亚迪小程序....')
        url = 'http://bydsong.soulmoto.com.cn/'

        if cookie:
            Playwright_.add_cookie(eval(cookie))
        Playwright_.goto(url)
        time.sleep(5)

        judge_ele = '//p[text()="任务大厅"]'
        if not Playwright_.get_count(judge_ele):
            account_ele = '//input[@placeholder="请输入账号/邮箱/手机号"]'
            Playwright_.input(account_ele, account)
            password_ele = '//input[@placeholder="请输入密码"]'
            Playwright_.input(password_ele, password)
            sure_ele = '//input[@name="isAgree"]/..'
            Playwright_.click(sure_ele)
            Playwright_.click('//button[text()="登录"]')
            time.sleep(5)
            assert Playwright_.get_count(judge_ele) == 1
        logger.info('比亚迪小程序登录成功....')

        # 页面cookie
        cookie_list = Playwright_.context.cookies()

        # api_cookie
        api_cookie = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookie_list])
        write_config_value('login', {'byd_cookie': str(cookie_list), f'byd_cookie_api': api_cookie}, file=config_file)

        return True
    except Exception as e:
        logger.error(f'比亚迪小程序登录失败：{e}')
        return False


def tt_login():
    try:
        logger.info('开始登录头条....')
        url = 'https://www.toutiao.com/'
        ele = '//div[@class="user-icon"]'
        key = 'login.tt_cookie'
        Playwright_.login(url, ele, key, file=config_file)
        logger.info('头条登录成功....')
        return True
    except Exception as e:
        logger.error(f'头条登录失败：{e}')
        return False

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


def get_url():
    logger.info('开始领取任务')
    url = 'http://bydsong.soulmoto.com.cn/ZbComTask/get_task?istype=25&usergroupid=43f3dc13dd6a8fff895f48c897b5a90b&openid=oYwld544l8JqilE_r9wVvUeAEfAQ'
    Playwright_.goto(url)
    time.sleep(5)
    order_ele = '//div[text()="领取互动任务"]'
    not_finish_ele = '//div[@class="tasks_box"]/a'
    order_count = Playwright_.get_count(order_ele)
    not_finish_count = Playwright_.get_count(not_finish_ele)
    if not order_count and not not_finish_count:
        return False, False, False
    elif order_count:
        detail = Playwright_.get_attribute(order_ele, 'href')
        Playwright_.click(order_ele)
    else:
        detail = Playwright_.get_attribute(not_finish_ele, 'href')
        detail = 'http://bydsong.soulmoto.com.cn' + detail
        Playwright_.click(not_finish_ele)
    time.sleep(5)
    order = Playwright_.get_attribute('//h4/a', 'href')
    title = Playwright_.get_text('//h4/a')
    logger.info(f'任务id：{detail}')
    logger.info(f'任务标题：{title}')
    logger.info(f'任务地址：{order}')
    return detail, order, title


def execute_tt_task(order, title):
    text1 = comments[random.randint(0, len(comments)-1)]
    text2 = comments[random.randint(0, len(comments)-1)]
    text = text1 + '，' + text2

    result = False
    logger.info(f'开始执行任务：{title}')

    Playwright_.goto(order)
    time.sleep(2)
    if Playwright_.get_count('//p[text()="抱歉，你访问的内容不存在"]'):
        logger.error('头条内容不存在')
        return result
    if Playwright_.get_count('//i[@class="comment-icon"]'):
        Playwright_.click('//i[@class="comment-icon"]')
        Playwright_.input('//div[@class="comment-textarea"]', text)

        Playwright_.click('//div[@class="submit-emoji-icon"]')
        Playwright_.click('//div[@class="main-input"]//div[@class="submit-emoji-list"]/li[2]/div')
        Playwright_.click('//div[@class="comment-textarea"]')
        Playwright_.page.keyboard.press('Backspace')
        Playwright_.click('//button[text()="评论"]')

    else:
        Playwright_.click('//div[@class="detail-interaction-comment"]')
        Playwright_.input('(//div[@class="ttp-comment-input"])[2]/div[1]', text)

        Playwright_.click('(//div[@class="submit-emoji-icon"])[2]')
        Playwright_.click('(//div[@class="submit-emoji-list"])[last()]/li[1]/div')
        # Playwright_.click('(//div[@class="submit-emoji-list"])[2]/li[2]/div')
        Playwright_.click('(//div[@class="ttp-comment-input"])[2]/div[1]')
        Playwright_.page.keyboard.press('Backspace')

        Playwright_.click('//button[@class="submit-btn"]')

    text_count = Playwright_.get_count(f'//p[contains(text(),"{text}")]')
    assert text_count != 0
    result = True
    logger.info(f'任务：{order}，提交评论成功：{text}')
    return result


def execute_wb_task(order, title):
    text1 = comments[random.randint(0, len(comments) - 1)]
    text2 = comments[random.randint(0, len(comments) - 1)]
    text = text1 + '，' + text2

    result = False
    logger.info(f'开始执行任务：{title}')

    Playwright_.goto(order)
    time.sleep(8)
    if Playwright_.get_count('//p[text()="抱歉，你访问的内容不存在"]'):
        logger.error('微博内容不存在')
        return result
    comement_ele = '//textarea[@placeholder]'
    Playwright_.click(comement_ele)
    Playwright_.input(comement_ele, text)
    Playwright_.click('//span[contains(text(),"评论")]')
    Playwright_.reload()
    time.sleep(5)
    text_count = Playwright_.get_count(f'//span[contains(text(), "{text}")]')
    assert text_count != 0
    result = True
    logger.info(f'任务：{order}，提交评论成功：{text}')
    return result

def deal_result(detail, result):
    Playwright_.goto(detail)
    time.sleep(5)
    if not result:
        Playwright_.click('//div[@class="bottomBox"]/a[1]')
        Playwright_.click('//div[@class="weui-dialog__ft"]/a[2]')
        logger.info('作品内容不存在，放弃任务')
    else:
        finish_ele = '//div[@class="bottomBox"]/a[2]'
        Playwright_.wait_for_selector(finish_ele, timeout=30000)
        Playwright_.click(finish_ele)
        logger.info('评论完成，可领取下一个任务')


def main():

    flag = byd_login()
    if not flag:
        exit()
    while True:
        logger.info('=' * 80)
        detail, order, title = get_url()
        if not title:
            logger.info('当前没有任务可领取')
            exit()

        if 'toutiao' in order:
            flag = tt_login()
            if not flag:
                continue
            result = execute_tt_task(order, title)
        else:
            flag = wb_login()
            if not flag:
                continue
            result = execute_wb_task(order, title)
        deal_result(detail, result)


if __name__ == '__main__':
    main()