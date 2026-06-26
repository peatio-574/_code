# -*- coding: utf-8 -*-
import sys

from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import requests, time
from Logger import logger
import re
import os
from openpyxl import load_workbook, Workbook

filename = os.path.join(os.path.dirname(__file__), '数据.xlsx')
company_file = os.path.join(os.path.dirname(__file__), 'company.txt')

if os.path.exists(filename):
    # 如果文件存在，加载现有工作簿
    wb = load_workbook(filename)
    ws = wb.active
else:
    headers = ['营业部名称', '详情链接', '上榜日期', '股票简称', '上榜原因',
               '涨跌幅(%)', '买入额（万）', '卖出额（万）', '买卖净额（万）', '所属板块']
    wb = Workbook()
    ws = wb.active
    ws.title = '数据'
    ws.append(headers)
    wb.save(filename)


headers = {
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Host": "data.10jqka.com.cn",
    "hexin-v": "Ax7qvCre-HSliywQ9clrO5NQb79l3-iudLOWIcini71clbBhMG8yaUQz5keb",
    "Referer": "https://data.10jqka.com.cn/market/longhu/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome 130.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def get_first(page=1):
    """上榜次数最多营业部名称，链接"""

    url = f'https://data.10jqka.com.cn/ifmarket/lhbyyb/type/1/tab/sbcs/field/sbcs/sort/desc/page/{page}/'

    info = requests.get(url, headers=headers).content.decode('gbk')
    companys = re.findall(r'<a href="(.*?)" target="_blank" title="(.*?)">.*?</a>', info)
    return companys

def get_second(page=1):
    """实力最强营业部名称，链接"""

    url = f'https://data.10jqka.com.cn/ifmarket/lhbyyb/type/1/tab/zjsl/field/zgczje/sort/desc/page/{page}/'

    info = requests.get(url, headers=headers).content.decode('gbk')
    companys = re.findall(r'<a href="(.*?)" target="_blank" title="(.*?)">.*?</a>', info)
    return companys

def get_companys(pages=10):
    result = []
    for page in range(1, pages + 1):
        first = get_first(page)
        for company in first:
            if company not in result:
                result.append(company)
        second = get_second(page)
        for company in second:
            if company not in result:
                result.append(company)
        logger.info(f'已获取第{page}页数据，当前共{len(result)}家公司')
        time.sleep(3)
    logger.info(f'共获取{len(result)}家公司')
    result = [str(company) for company in result]
    with open(company_file, 'w', encoding='utf-8') as f:
        string = '\n'.join(result)
        f.write(string)
        logger.info('公司信息保存成功')


def get_page_detail(orgcode, page=1):
    """获取营业部指定页码数据"""
    url = f'http://data.10jqka.com.cn/ifmarket/lhbhistory/orgcode/{orgcode}/field/ENDDATE/order/desc/page/{page}/'
    logger.info(f'链接:{url}')
    info = requests.get(url, headers=headers).content.decode('gbk')
    rows = re.findall(
        r'<tr>\s*<td>(\d{4}-\d{2}-\d{2})</td>\s*<td>\s*<a[^>]*>([^<]+)</a>\s*</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*</tr>',
        info,
        re.DOTALL
    )

    # 提取总页数
    page_info = re.search(r'(\d+)/(\d+)', info)
    total_pages = int(page_info.group(2)) if page_info else 0
    logger.info(f'当前营业部共{total_pages}页，当前第{page}页，含有{len(rows)}行数据')
    return total_pages, rows

def save_page(idx, company_name, company_url, page_info, page_no):
    """保存单页数据"""
    try:
        for page_ in page_info:
            row = [company_name, company_url, *page_]
            ws.append(row)
        wb.save(filename)
        logger.info(f'第{idx}家：【{company_name}】第{page_no}页保存数据成功')
    except Exception as e:
        logger.error(f'第{idx}家：【{company_name}】第{page_no}页保存数据失败：{e}')
    time.sleep(2)

def run():
    with open(company_file, 'r', encoding='utf-8') as f:
        companys = f.readlines()
        logger.info(f'共{len(companys)}家公司')
    for idx, company in enumerate(companys, start=1):
        company = eval(company)
        company_url, company_name = company
        logger.info(f'开始获取第{idx}家：【{company_name}】数据')
        orgcode = company_url.split('/')[-2]
        total_pages, page_info = get_page_detail(orgcode, page=1)
        save_page(idx, company_name, company_url, page_info, page_no=1)

        for page_no in range(2, total_pages+1):
            page_total, page_info = get_page_detail(orgcode, page=page_no)
            save_page(idx, company_name, company_url, page_info, page_no=page_no)

        logger.info(f'【{company_name}】爬取完成，休息10秒')
        time.sleep(10)


if __name__ == '__main__':
    while True:
        step = input('请输入操作步骤(1获取公司信息，2开始获取数据)：')
        if step == '1':
            get_companys()
        else:
            run()