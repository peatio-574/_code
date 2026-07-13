# coding='utf-8'
import sys

from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger
import time


def getInvestingInfo():
    url = 'https://cn.investing.com/search/?q=%E7%87%83%E6%96%99%E6%B2%B9&tab=news'

    Playwright_.goto(url)

    rollTime = 0
    rowsInfo = []
    while rollTime < 5:
        time.sleep(5)
        rowEle = '//div[@class="js-section-content largeTitle"]/div'
        rowCount = Playwright_.get_count(rowEle)
        logger.info(f'rowCount: {rowCount}')


        for rowId in range(1, rowCount + 1):
            date = Playwright_.get_text(f'{rowEle}[{rowId}]//time')
            titleEle = f'{rowEle}[{rowId}]//a[@class="title"]'
            title = Playwright_.get_text(titleEle)
            href = Playwright_.get_attribute(titleEle, 'href')
            # content = Playwright_.get_text(f'{rowEle}[{rowId}]//p[@class="js-news-item-content"]')
            rowInfo = {
                'date': date,
                'title': title,
                'href': href,
                # 'content': content
            }
            if rowInfo not in rowsInfo:
                logger.info(rowInfo)
                rowsInfo.append(rowInfo)
        Playwright_.page.keyboard.press("End")  # 滚动
        rollTime += 1
    return rowsInfo


def getRowDetail(rowInfo):
    base = 'https://cn.investing.com'
    link = base + rowInfo['href']
    Playwright_.goto(link)
    time.sleep(5)
    contentEle = '//div[@class="paywall"]/div/div[1]/p'
    contentCount = Playwright_.get_count(contentEle)
    contents = []
    for contentId in range(1, contentCount + 1):
        content = Playwright_.get_text(f'{contentEle}[{contentId}]')
        contents.append(content)
    contents = '\n'.join(contents)
    rowInfo['contents'] = contents
    return rowInfo

def getRowsDetail():
    rowsInfo = getInvestingInfo()
    for rowInfo in rowsInfo:
        rowInfo = getRowDetail(rowInfo)
        logger.info(rowInfo)



if __name__ == '__main__':
    getInvestingInfo()