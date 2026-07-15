# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import os

# 获取当前可执行文件或脚本所在的目录（兼容开发环境与打包后的 exe）
def getBaseDir():
    if getattr(sys, 'frozen', False):
        # 打包后，sys.executable 指向 exe 的路径
        return os.path.dirname(sys.executable)
    else:
        # 开发环境，直接使用脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))
baseDir = getBaseDir()
sys.path.append(str(Path(baseDir).parent))


import time
from PlayWright import logger, Playwright_
from ReadFile import ReadData


configFile = os.path.join(baseDir, 'config.ini')
fileName = os.path.join(baseDir, '博主链接.xlsx')


def douYinLogin(account):
    url = 'https://www.douyin.com/user/self'
    ele = '(//div[@class="arXOQVuK"]/../div)[last()]/div/a'
    key = f'login.douYinCookie{account}'
    try:
        logger.info(f'开始登录抖音第{account}个账号....')
        loginStatus = Playwright_.login(url, ele, key, file=configFile)
        if loginStatus:
            logger.info(f'✅️ 第{account}个抖音账号登录成功')
        else:
            logger.error(f'❌ 第{account}个抖音账号登录失败，未获取到元素')
    except Exception as e:
        logger.error(f'❌ 第{account}个抖音账号登录失败：{e}')
        return False
    return loginStatus


def control(url):
    try:
        Playwright_.goto(url)
        Playwright_.wait_for_selector('//div[@id="tooltip"]/button/span', timeout=30*1000)
        time.sleep(3)
        closeEle = '//span[text()="取消"]'
        if Playwright_.get_count(closeEle):
            Playwright_.click(closeEle)

        Playwright_.click('//div[@id="tooltip"]/button/span')
        Playwright_.click('//li[text()="举报账号"]')
        Playwright_.click('//div[text()="举报原因"]/../../div[2]/div[1]/div')  # 举报原因
        Playwright_.click('//div[text()="举报原因"]/../../div[4]/div[1]/div')  # 具体类型

        text = '不好'
        Playwright_.input('//textarea[contains(@placeholder, "举报原因")]', text)  # 描述

        Playwright_.click('//button[text()="提交"]')
        time.sleep(2)
        logger.info(f'✅️ 抖音博主举报成功：{url}\n')
    except Exception as e:
        logger.error(f'❌ 抖音博主举报失败：{e}\n{url}\n')


def execute():
    accounts = input('请输入登录账号个数：')
    if not accounts.isdigit():
        exit('请输入正确的数字!!!')
    urls = ReadData.read_xlsx_col(file=fileName)['博主链接']
    logger.info(f'共需要执行{len(urls)}个任务')

    for idx, url in enumerate(urls, 1):
        logger.info(f'开始执行第{idx}个任务：{url}')
        for account in range(1, int(accounts)+1):
            status = douYinLogin(account=account)
            if status:
                control(url)


if __name__ == '__main__':
    execute()