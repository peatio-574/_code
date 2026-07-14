# coding='utf-8'
import sys

from pathlib import Path

# 把项目根目录 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger
import time
import csv
import os


t = time.localtime(time.time() - 86400)
year = t.tm_year
month = t.tm_mon
day = t.tm_mday

def matchDate(date):
    """匹配前一天以及..小时以前的时间，返回bool"""
    templateDate = ['以前', f'{year}年{month}月{day}日']
    for template in templateDate:
        if template in date:
            return True
    return False


def getInvestingInfo():
    """循环滚动，获取符合条件的标题、链接"""
    url = 'https://cn.investing.com/search/?q=%E7%87%83%E6%96%99%E6%B2%B9&tab=news'

    Playwright_.goto(url)
    time.sleep(5)
    Playwright_.mouse_wheel(200)
    Playwright_.click('(//span[@class="datePickerIcon"])[1]')
    Playwright_.input('//input[@id="startDate"]', '')
    Playwright_.page.locator('//input[@id="startDate"]').press_sequentially(f'{str(year)[-2:]}/{month:02d}/{day:02d}')
    # Playwright_.input('//input[@id="endDate"]', time.strftime("%y/%m/%d", time.localtime()))
    Playwright_.click('//a[@id="applyBtn"]')
    time.sleep(3)
    rowEle = '//div[@class="js-section-content largeTitle"]/div'
    rowCount = Playwright_.get_count(rowEle)

    rowsInfo = []

    for rowId in range(1, rowCount + 1):
        date = Playwright_.get_text(f'{rowEle}[{rowId}]//time')
        if not matchDate(date):
            continue

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
            # logger.info(rowInfo)
            rowsInfo.append(rowInfo)
    return rowsInfo


def getRowDetail(rowInfo):
    base = 'https://cn.investing.com'
    link = base + rowInfo['href']
    Playwright_.goto(link)
    time.sleep(5)
    publishTime = Playwright_.get_text('(//div[@class="flex flex-row items-center"])[2]/span')
    if f'{year}-{month}-{day}' not in publishTime:
        return rowInfo

    contentEle = '//div[contains(@class, "article")]/div[1]/p'
    contentCount = Playwright_.get_count(contentEle)
    contents = []
    for contentId in range(1, contentCount + 1):
        content = Playwright_.get_text(f'({contentEle})[{contentId}]')
        contents.append(content)
    contents = '\n'.join(contents)

    authorEle= '//span[@class="flex flex-row text-xs"]/a/span'
    author = Playwright_.get_text(authorEle) if Playwright_.get_count(authorEle) else ''
    rowInfo['contents'] = contents
    rowInfo['publishTime'] = publishTime[5:]
    rowInfo['author'] = author
    return rowInfo

def getRowsDetail():
    csvFile = os.path.join(os.path.dirname(__file__), 'Investing.csv')
    fileHeader = ['发布时间', '标题', '作者', '正文']
    fileExists = os.path.exists(csvFile)
    rowsInfo = getInvestingInfo()
    logger.info(f'共{len(rowsInfo)}条数据')
    with open(csvFile, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fileHeader, extrasaction='ignore')

        # 文件不存在时才写入表头（追加模式不重复写入表头）
        if not fileExists:
            writer.writeheader()

        # 遍历处理每一行数据
        for rowInfo in rowsInfo:
            logger.info(f'爬取详情：{rowInfo}')
            rowInfo = getRowDetail(rowInfo)

            # 只处理有发布时间的数据
            if rowInfo.get('publishTime'):


                # 构造符合表头格式的数据字典
                csv_row = {
                    '发布时间': rowInfo.get('publishTime', ''),
                    '标题': rowInfo.get('title', ''),
                    '作者': rowInfo.get('author', ''),
                    '正文': rowInfo.get('contents', '')
                }

                # 逐行追加写入CSV
                logger.info(rowInfo)
                writer.writerow(csv_row)

                # 可选：立即刷新到磁盘，防止数据丢失
                f.flush()



if __name__ == '__main__':
    getRowsDetail()
    # row = {'date': '15 小时以前', 'title': '乌克兰在亚速海袭击多艘俄罗斯油轮和货船', 'href': '/news/economy-news/article-93CH-3458011'}
    # getRowDetail(row)