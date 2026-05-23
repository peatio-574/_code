# -*- coding: utf-8 -*-
import sys

import re
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from Config import get_config_value
import time
from spider_panjiva.login import Playwright_, logger, panjiva_login, ws, wb, file



def get_panjiva_page_info():
    """获取盘踞网当页数据"""
    company = []
    page = Playwright_.get_text('//ul[@class="results-by-page"]/li/div/span')
    logger.info(f'开始获取第{page}页数据')
    try:
        count_ele = '//tbody[@class="notranslate"]/tr'
        count = Playwright_.get_count(count_ele)
        for i in range(1, count+1):
            ele = f'({count_ele})[{i}]/td[5]/strong/a'
            if Playwright_.get_count(ele):
                company_en = Playwright_.get_text(ele)
                link = Playwright_.get_attribute(ele, 'href')
                company.append([company_en, link])
    except Exception as e:
        logger.error(f'第{page}页数据获取异常：{e}')
    return company


def panjiva_search():
    """获取盘踞网所有数据"""
    # 限制数量
    limit_count = int(get_config_value('login', 'limit_count'))

    panjiva_login()
    logger.info('请选择自定义搜索条件，进行搜索，45秒后开始读取数据....')
    time.sleep(35)
    logger.info('倒计时10秒，10秒后开始读取数据')
    time.sleep(10)

    companys = []

    row_id = 1

    while True:
        # 页面滚动
        Playwright_.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)
        # 获取页面数据
        company = get_panjiva_page_info()
        for company_ in company:
            if company_[0] not in companys:
                companys.append(company_[0])
                row_id += 1
                ws.cell(row=row_id, column=1, value=company_[0])
                ws.cell(row=row_id, column=2, value=company_[1])
                wb.save(file)
                logger.info(f'已保存第{len(companys)}条数据：{company_[0]}，行号：{row_id}')

        # 判断是否获取足够数据
        if len(companys) >= limit_count:
            logger.info(f'限制数量：{limit_count}，已获取{len(companys)}条数据，停止获取数据')
            break

        # 判断是否有下一页
        next_page_ele = '//i[@class="panjiva-icon-right"]'
        next_page_count = Playwright_.get_count(next_page_ele)
        if next_page_count > 0:
            Playwright_.click(next_page_ele)
            time.sleep(5)
        else:
            logger.info('已获取网站所有数据，停止获取数据')
            break


def get_company_detail(company, url):
    """获取盘踞网公司详细数据"""
    info = {'product': '', 'compare': ''}
    try:
        Playwright_.goto(url)
        time.sleep(5)
        product_ele  = '//h3[text()="Top Product Terms"]/../../ol/li/a'
        products = ''
        for i in range(1, 3):
            ele = f'({product_ele})[{i}]'
            product = Playwright_.get_text(ele) if Playwright_.get_count(ele) else ''

            HS_ele = f'(//h3[text()="Top Products"]/../../div[3]//div[@aria-expanded])[{i}]'
            HS_code = Playwright_.get_text(HS_ele) if Playwright_.get_count(HS_ele) else ''

            product_ = f'{product}    {HS_code}'
            products += product_ + '\n'
        products = products.strip()
        info['product'] = products

        compare_ele = '(//h3[text()="Top Carriers"]/../../div[3]//a)[1]'
        compare = Playwright_.get_text(compare_ele) if Playwright_.get_count(compare_ele) else ''
        info['compare'] = compare
    except Exception as e:
        logger.error(f'【{company}】盘踞网数据获取异常：{e}')
    return info

if __name__ == '__main__':
    panjiva_search()