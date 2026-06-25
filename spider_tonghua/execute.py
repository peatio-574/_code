# -*- coding: utf-8 -*-
import sys

import re
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from PlayWright import Playwright_, logger
import os
from openpyxl import load_workbook, Workbook
#
# filename = os.path.join(os.path.dirname(__file__), '数据.xlsx')
#
# if os.path.exists(filename):
#     # 如果文件存在，加载现有工作簿
#     wb = load_workbook(filename)
#     ws = wb.active
# else:
#     headers = ['用户ID', '用户名称', 'IP属地', '用户简介', '用户标签',
#                '笔记标题', '编辑时间', '正文文本', '标签', '点赞数',
#                '评论数', '评论列表', '笔记图片', '作品链接']
#     wb = Workbook()
#     ws = wb.active
#     ws.title = '小红书笔记数据'
#     ws.append(headers)
# wb.save(filename)

import requests, time

headers = {
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    # "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Host": "data.10jqka.com.cn",
    "hexin-v": "Ax7qvCre-HSliywQ9clrO5NQb79l3-iudLOWIcini71clbBhMG8yaUQz5keb",
    "Referer": "https://data.10jqka.com.cn/market/longhu/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome 130.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def get_first(page=1):
    url = f'https://data.10jqka.com.cn/ifmarket/lhbyyb/type/1/tab/sbcs/field/sbcs/sort/desc/page/{page}/'

    info = requests.get(url, headers=headers).content.decode('gbk')
    companys = re.findall(r'<a href="(.*?)" target="_blank" title="(.*?)">.*?</a>', info)
    return companys

def get_second(page=1):
    url = f'https://data.10jqka.com.cn/ifmarket/lhbyyb/type/1/tab/zjsl/field/zgczje/sort/desc/page/{page}/'

    info = requests.get(url, headers=headers).content.decode('gbk')
    companys = re.findall(r'<a href="(.*?)" target="_blank" title="(.*?)">.*?</a>', info)
    return companys

def get_companys():
    pages = 10
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
    with open('company.txt', 'w', encoding='utf-8') as f:
        string = '\n'.join(result)
        f.write(string)
        logger.info('公司信息保存成功')


def get_detail(orgcode, page=1):
    # company_url, company_name = eval(company)
    # orgcode = company_url.split('/')[-2]
    url = f'http://data.10jqka.com.cn/ifmarket/lhbhistory/orgcode/{orgcode}/field/ENDDATE/order/desc/page/{page}/'
    info = requests.get(url, headers=headers).content.decode('gbk')
    print(info)


if __name__ == '__main__':
    get_detail('43dbc90e8cbe02a2')