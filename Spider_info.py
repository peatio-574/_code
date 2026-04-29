# -*- coding: utf-8 -*-
import time

import pandas
from openpyxl.styles import Font
import requests

def get_page_info(keyword='America', page='1'):
    """获取单页数据"""
    print(f'第{page}页数据')
    url = f'https://newspal-api.cgtn.com/search/web?keyword={keyword}&page_no={page}&page_size=20&sort_by=relevance&is_highlight=true'
    try:
        start_time = int(time.mktime(time.strptime('2023-01-01 00:00:00', '%Y-%m-%d %H:%M:%S'))) * 1000
        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
        }
        response = requests.get(url, headers=headers).json()['data']
        data = list()
        for line in response['news_list']:
            publish_time = line['publishTime']
            if publish_time >= start_time:
                date = time.strftime('%Y-%m-%d', time.localtime(publish_time // 1000))
                title = line['shortHeadline']
                author = line['authors']
                link = line['webUrl']
                data.append([title, date, author, link])
        return response['total'], data
    except Exception as e:
        print(url)
        print(f'第{page}页数据抓取失败：{e}')
        return False

def get_pages(keywords: list):
    info = dict()
    for keyword in keywords:
        print(f'获取{keyword}数据')
        total, data = get_page_info(keyword)
        for item in data:
            info[item[0]] = item

        pages = total // 20 if total % 20 == 0 else total // 20 + 1
        print(f'共{pages}页数据')
        for page in range(2, pages+1):
            if page % 170 == 0:
                print(f'当前页码{page}，暂停3分钟')
                time.sleep(60*3)

            page_info  = get_page_info(keyword, page)
            if not page_info:
                break
            data = page_info[1]
            for item in data:
                if item[0] in list(info.keys()):
                    continue
                info[item[0]] = item
        print(f'{keyword}完成')
        if keyword == keywords[-1]:
            break
        print('暂停3分钟')
        time.sleep(3*60)

    data = list(info.values())
    print(f'共{len(data)}条数据')
    data.sort(key=lambda x: x[1], reverse=True)
    return data

def to_xlsx(keywords):
    # keywords1 = [
    #     ['US', 'America', 'American'],
    #     ['UK', 'British'],
    #     ['Canada', 'Canadian'],
    #     ['France', 'French'],
    #     ['German', 'Germany']
    # ]

    file = './爬虫数据2.xlsx'
    columns = ['标题', '时间', '作者', '分享链接']

    info = get_pages(keywords=keywords)

    result = {columns[i]: [row[i] for row in info] for i in range(len(columns))}
    df = pandas.DataFrame(result)
    with pandas.ExcelWriter(file, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
        workbook = writer.book
        sheet = workbook.active
        start_row = sheet.max_row
        df.to_excel(writer, sheet_name=keywords[0], startrow=start_row, index=False, header=True)

        bold_font = Font(bold=True)
        header_row = start_row + 1  # 表头所在行
        cols = len(columns)

        # 循环给表头所有单元格加粗
        for col in range(1, cols + 1):
            sheet.cell(row=header_row, column=col).font = bold_font
    print('数据写入成功')

def main():
    keywords2 = [
        # ['Brazil', 'Brazilian'],
        ['Russia', 'Russian'],
        # ['India', 'Indian'],
        ['China', 'Chinese'],
        ['South Africa', 'South African']
    ]
    for mysql in keywords2:
        to_xlsx(mysql)
        time.sleep(5*60)



if __name__ == '__main__':
    main()