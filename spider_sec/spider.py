import sys
from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

import json
import os
import requests
from Config import get_config_value
from PlayWright import Playwright_, logger

index = get_config_value('login', 'index')

os.makedirs('d:/_code/spider_sec/files', exist_ok=True)

def run():
    with open('./company.json', mode='r', encoding='utf-8') as f:
        company_infos = json.loads(f.read())['data']
    headers = {
        'user-agent': get_config_value('login', 'user_agent')
    }

    for company_ in range(len(company_infos)):
        if company_ < int(index):
            continue

        company = company_infos[company_]

        logger.info(f'开始获取{company[1]}信息，索引：{company_}')

        code = f"{company[0]:010d}"
        code_url = f'https://efts.sec.gov/LATEST/search-index?keysTyped={code}'
        company_name = requests.get(code_url, headers=headers).json()['hits']['hits'][0]['_source']['entity_words']

        logger.info(f'完整证券代码为：{code}，公司名称为：{company_name}')

        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '.', '\n', ' ']
        dir_name = str(company_) + company_name
        for c in invalid_chars:
            dir_name = dir_name.replace(c, '-')

        url = 'https://efts.sec.gov/LATEST/search-index'

        parmas = {
            'dateRange': 'custom',
            'category': 'form-cat1',
            'ciks': code,
            'entityName': company_name,
            'forms': '10-K,20-F',
            'startdt': '2017-01-01',
            'enddt': '2026-05-07'
        }
        #
        contents = requests.get(url, headers=headers, params=parmas).json().get('hits')
        if not contents:
            logger.info(f'{company_name}没有数据')
            continue

        contents = contents.get('hits')

        if len(contents) == 0:
            logger.info(f'{company_name}没有数据')
            continue

        os.makedirs(f'd:/_code/spider_sec/files/{dir_name}', exist_ok=True)
        logger.info(f'{company_name}共{len(contents)}条数据')
        for i in contents:
            a, b = i['_id'].split(':')
            a = a.replace('-', '')
            url = f'https://www.sec.gov/Archives/edgar/data/{i["_source"]["ciks"][0][3:]}/{a}/{b}'
            logger.info(f'开始下载{url}')

            date = i['_source']['period_ending']
            description = i['_source']['file_type']
            description = description if description else i['_source']['form']
            invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '.', '\n', ' ']
            for c in invalid_chars:
                description = description.replace(c, '-')
            output = f'd:/_code/spider_sec/files/{dir_name}/{date}--{description}.pdf'
            if os.path.exists(output):
                logger.info(f'{output}文件已存在')
                continue

            Playwright_.goto(url)

            page = Playwright_.page
            # 保存为 PDF，可自定义边距/纸张大小
            page.pdf(
                path=output,
                format="A4",
                margin={"top": "0.5in", "right": "0.5in", "bottom": "0.5in", "left": "0.5in"},
                print_background=True  # 保留背景色和样式
            )
            print(f"✅ 已保存为：{output}")

if __name__ == '__main__':
    run()