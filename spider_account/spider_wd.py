# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger, get_config_value
import time
import os
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')


def wd_login(shop_id=1):
    try:

        logger.info('开始登录微店....')
        url = 'https://d.weidian.com/weidian-pc/login/#/shopSelect'
        ele = '//div[@class="nick-name"]'
        if shop_id <= 5:
            key = f'login.wd_cookie_1'
        elif shop_id <= 10:
            key = f'login.wd_cookie_2'
        else:
            key = f'login.wd_cookie_3'

        idx = (shop_id - 1) % 5 + 1
        extra = f'(//div[text()="子账号店铺:"]/../../div[@data-spider-mode="trackAction"])[{idx}]/div[1]'
        Playwright_.login(url, ele, key, extra=extra, file=config_file)
        logger.info('微店登录成功....')
        return True
    except Exception as e:
        logger.error(f'微店登录失败：{e}')
        return False


def wd_search(start, end):
    shop_name = Playwright_.get_text('//div[@class="user-name"]')
    shop_name = shop_name.strip()
    logger.info(f'当前店铺名称：{shop_name}')
    Playwright_.goto('https://d.weidian.com/weidian-pc/weidian-loader/#/pc-vue-balance/overview')
    time.sleep(8)

    Playwright_.input('//input[@placeholder="开始日期"]', start)
    Playwright_.input('//input[@placeholder="结束日期"]', end, enter=True)
    Playwright_.click('//span[text()="筛选"]')
    return shop_name


def main_(account_id=1):
    title = f'========================开始爬取微店第{account_id}个店铺======================='
    logger.info(title)
    end = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    start = f"{end[:-3]}-01"

    login = wd_login(account_id)
    if not login:
        return [None, None, None]
    shop_name = wd_search(start, end)

    time.sleep(10)

    logger.info(f'{shop_name}店铺开始导出明细....')
    status = False
    st_time = time.time()
    for roll in range(1, 6):
        logger.info(f'第{roll}次导出明细....')
        Playwright_.click('//span[text()="导出报表"]')
        time.sleep(8)
        if Playwright_.get_count('//span[text()="暂无数据"]'):
            return [None, None, None]
        if Playwright_.get_count('//span[text()="生成报表"]'):
            Playwright_.click('//span[text()="生成报表"]')
        time.sleep(5)
        date_ = Playwright_.get_text('(//div[@class="record-item"])[1]/div[1]/div[1]')[9:]
        time_struct = time.strptime(date_, "%Y-%m-%d %H:%M:%S")
        timestamp = int(time.mktime(time_struct))
        if timestamp >= st_time:
            status = True
            break
        else:
            Playwright_.reload()

    text = f'✅️ {shop_name}店铺明细数据预生成中....' if status else f'❌️ {shop_name}店铺明细数据预生成失败'
    logger.info(text)
    Playwright_.clear_cookie()
    return [shop_name, start, end] if status else [None, None, None]





if __name__ == '__main__':
    # wd_deal_data('测试', './数据/测试微店.xlsx')
    shop_count_ = get_config_value('login', 'wd_shop_count', file=config_file)
    shop_flag = input('请输入查询店铺序号（0默认查询全部）：')
    if shop_flag == '0':
        start_id = 1
        end_id = int(shop_count_) + 1
    elif ':' in shop_flag or '：' in shop_flag:
        shop_flag = shop_flag.replace('：', '').replace(':', '')
        start_id = int(shop_flag)
        end_id = int(shop_count_) + 1
    else:
        start_id = int(shop_flag)
        end_id = start_id + 1
    current_info = []
    for account_id in range(start_id, end_id):
        shop_reuslt = main_(account_id)
        if shop_reuslt == [None, None, None]:
            continue
        current_info.append(shop_reuslt)
    logger.info(f'共获取{len(current_info)}店铺数据：{current_info}')

    file = os.path.join(os.path.dirname(__file__), 'wd.txt')
    with open(file, 'r', encoding='utf-8') as f:
        text = f.readlines()

    string = ''
    for shop_info in current_info:
        if shop_info not in text:
            string += f'{shop_info}\n'
    with open(file, 'a', encoding='utf-8') as f:
        f.write(string)

