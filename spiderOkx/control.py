# coding='utf-8'
import sys
from pathlib import Path

# 把项目根目录加入Python路径
sys.path.append(str(Path(__file__).parent.parent))



from PlayWright import Playwright_, logger, get_config_value
import os
import time
from ReadFile import ReadData
from openpyxl import load_workbook, Workbook
import requests

configFile = os.path.join(os.path.dirname(__file__), 'config.ini')


def okxLogin():
    logger.info('开始登录欧易....')
    url = 'https://www.btmzhjpdgxc.com/zh-hans/orbit/feed'
    ele = '//a[text()="充币" and @class="deposit-btn"]'
    key = 'login.okxCookie'
    Playwright_.login(url, ele, key, file=configFile)
    logger.info('✅️ 欧易登录成功')


def getDatas():
    okxLogin()
    Playwright_.close()
    fileName = os.path.join(os.path.dirname(__file__), '欧易数据.xlsx')

    if os.path.exists(fileName):
        # 如果文件存在，加载现有工作簿
        wb = load_workbook(fileName)
        ws = wb.active
    else:
        headers = ['发布时间', '作者', '帖子内容', ]
        wb = Workbook()
        ws = wb.active
        ws.title = '数据'
        ws.append(headers)
        wb.save(fileName)


    existData = ReadData.read_xlsx_col(fileName)['发布时间']
    cursor = ''
    while True:
        if cursor == '0':
            logger.info('没有更多数据了')
            break
        cursor = getSinglePageInfo(ws, wb, fileName, existData, cursor)
        time.sleep(10)




def getSinglePageInfo(ws, wb, fileName, existData, cursor=''):
    logger.info(f'\n开始获取数据....cursor：{cursor}')
    ms_timestamp = int(time.time() * 1000)
    cursor = f'&cursor={cursor}' if cursor else ''

    url = f'https://www.btmzhjpdgxc.com/priapi/v5/rubik/public/content/feed/1?size=10{cursor}&t={ms_timestamp}'

    token = ''
    cookies = get_config_value('login', 'okxCookie', file=configFile)
    for cookie in eval(cookies):
        if cookie.get('name') == 'token':
            token = cookie.get('value')
    headers = {
        "Accept": "application/json",
        "content-type": "application/json;charset=UTF-8",
        "referer": "https://www.btmzhjpdgxc.com/zh-hans/orbit/feed",
        "app-type": "web",
        "x-id-group": "2130948145125530008-c-14",
        "devid": "afa0643a-cfee-4783-a5a2-29b321fd234d",
        "cookie": get_config_value('login', 'okxCookie_api', file=configFile),
        "authorization": token,
        # "x-fptoken-signature": "{P1363}QZeatxR9NsjI2VRNDzWgvlj9MZ+EaVifI5UXBex5fmrJu4+uBM1QLEVVtCijIELcW6H2Fd2ikZoVmsiqg2Rd+Q==",
        # "x-fptoken": "eyJraWQiOiIxNjgzMzgiLCJhbGciOiJFUzI1NiJ9.eyJpYXQiOjE3ODQ4MTQ1MTksImVmcCI6IkRKbm5VQ2h3MmJCWW9oTWlGdVVHUUpseHZJbTVUKys2eTliRGtISHBkdXBkSkRNZFRTK2hsRGZGMUptZDk1VFoiLCJkaWQiOiJhZmEwNjQzYS1jZmVlLTQ3ODMtYTVhMi0yOWIzMjFmZDIzNGQiLCJjcGsiOiJNRmt3RXdZSEtvWkl6ajBDQVFZSUtvWkl6ajBEQVFjRFFnQUUwU2k1d1BnVkhpaDBNSytqU3ZkUFVmaWs1MnpDcTBaZlVoNHhWY3lDc2dFbHNlODk5Sjl6Y1Fub3VMWEZRWmFEb1hQMmJTK3huS1oxWC9sNUgzT01rdz09In0.SyCAS4n9sFcxsOVth_JnU_t5ZcDOJVu38AfPn-Lve_xz_tjy_pB3EdzmAVsdPBaSHGEO5koEngBtzcl5rLXAGA",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0",

    }
    response = requests.get(url, headers=headers).json()['data']

    nextCursor = response['nextCursor']
    count = 0
    for row in response['dataList']:
        pubulishTime = row['contentData']['publishTime']

        if int(time.time() * 1000) - int(pubulishTime) > 3 * 24 * 60 * 60 * 1000:
            logger.info(f'数据不在三天之内，退出程序')
            exit()

        pubulishTime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(pubulishTime)/1000))

        if pubulishTime in existData:
            continue

        author = row['contentData']['author']['nickName']
        content = row['contentData']['content']
        logger.info(f'发布时间：{pubulishTime} 作者：{author} 内容：{content[:10]}')
        ws.append([pubulishTime, author, content])
        existData.append(pubulishTime)
        count += 1
    wb.save(fileName)
    logger.info(f'本次保存{count}条数据成功')
    return nextCursor

if __name__ == '__main__':
    getDatas()