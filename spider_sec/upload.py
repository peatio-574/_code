# -*- coding: utf-8 -*-
import sys
import time


from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger, get_config_value
import os

def upload(file_path):
    try:
        url = 'https://app.gptzero.me/'
        login_location = '//div[@aria-label="Profile picture icon"]'
        key = 'login.me_cookie'
        Playwright_.login(url, login_location, key, storage=True)

        logger.info(f'开始上传文件：{file_path}')

        file_location = '(//input[@type="file"])[1]'
        Playwright_.page.locator(file_location).set_input_files(file_path)

        Playwright_.wait_for_selector('//div[@class="flex-1 overflow-auto"]', timeout=30*1000)

        Playwright_.page.click('(//span[text()="Scan"])[2]/../..')
        Playwright_.wait_for_selector('//div[@class="sm:h-full overflow-auto"]', timeout=30*1000)

    except Exception as e:
        logger.error(f'上传文件失败：{file_path}，失败原因：{e}')


def main():
    index = get_config_value('login', 'index_')

    dirname = 'd:/_code/spider_sec/files'
    infos = list()
    for dir_ in os.listdir(dirname):
        dir_path = os.path.join(dirname, dir_)
        line = list()
        for file_ in os.listdir(dir_path):
            file_date = file_[:10]
            if file_date < '2022-01-01':
                continue
            file_path = os.path.join(dir_path, file_)
            line.append(file_path)
        infos.append({dir_: line})

    for line in range(len(infos)):
        if line < int(index):
            continue
        company = list(infos[line].keys())[0]
        logger.info(f'开始上传{company}年报，共{len(infos[line][company])}个文件，索引：{line}')
        for file_path in infos[line][company]:
            upload(file_path)

if __name__ == '__main__':
    main()