# coding='utf-8'
import sys
import os

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(BASE_DIR, '..', ))

from newPlayWright import PlayWright, logger
import time
import csv
import requests



def matchDate(date, startDate):
    """匹配前一天以及..小时以前的时间，返回bool"""
    year, month, day = startDate.split('-')
    month = month if not month.startswith('0') else month[1]
    day = day if not day.startswith('0') else day[1]
    templateDate = ['以前', f'{year}年{month}月{day}日']
    for template in templateDate:
        if template in date:
            return True
    return False


def getPageInfo(startDate, vpn):
    """循环滚动，获取符合条件的标题、链接"""
    url = 'https://www.investing.com/search/?q=fuel oil&tab=news'

    PlayWright.goto(url, proxy={'server': f'http://{vpn}'})
    time.sleep(5)
    if PlayWright.get_count('//button[text()="I Accept"]'):
        PlayWright.click('//button[text()="I Accept"]')
        time.sleep(10)
    if PlayWright.get_count('//i[@class="popupCloseIcon largeBannerCloser"]'):
        PlayWright.click('//i[@class="popupCloseIcon largeBannerCloser"]')
        time.sleep(10)
    if PlayWright.get_count('//button[@aria-label="Close Modal"]'):
        PlayWright.click('//button[@aria-label="Close Modal"]')
        time.sleep(3)
    PlayWright.mouse_wheel(200)
    PlayWright.click('(//span[@class="datePickerIcon"])[1]')

    endDate = time.strftime('%Y-%m-%d', time.localtime(time.mktime(time.strptime(startDate, "%Y-%m-%d")) + 86400))
    # endDate = time.strftime('%Y-%m-%d', time.localtime(time.time()))
    startStr = startDate.split('-')
    startStr = rf'{startStr[1]}/{startStr[2]}/{startStr[0][2:]}'

    endStr = endDate.split('-')
    endStr = rf'{endStr[1]}/{endStr[2]}/{endStr[0][2:]}'
    PlayWright.slow_input('//input[@id="startDate"]', startStr)
    time.sleep(1)
    PlayWright.slow_input('//input[@id="endDate"]', endStr, enter=True)
    time.sleep(5)

    rowEle = '//div[@class="js-section-content largeTitle"]/div'

    rowsInfo = []

    rowCount = PlayWright.get_count(rowEle)

    for rowId in range(1, rowCount + 1):
        date = PlayWright.get_text(f'{rowEle}[{rowId}]//time')
        if not matchDate(date, startDate):
            continue

        titleEle = f'{rowEle}[{rowId}]//a[@class="title"]'
        title = PlayWright.get_text(titleEle)
        href = PlayWright.get_attribute(titleEle, 'href')
        # content = PlayWright.get_text(f'{rowEle}[{rowId}]//p[@class="js-news-item-content"]')
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


def getRowDetail(rowInfo, startDate):
    base = 'https://www.investing.com'
    link = base + rowInfo['href']
    for roll in range(1, 4):
        status = PlayWright.goto(link)
        if status:
            break
    time.sleep(5)

    publishTime = PlayWright.get_text('(//div[@class="flex flex-row items-center"])[2]/span')
    year, month, day = startDate.split('-')
    month = month if not month.startswith('0') else month[1]
    day = day if not day.startswith('0') else day[1]

    if f'{year}-{month}-{day}' not in publishTime:
        return rowInfo

    contentEle = '//div[contains(@class, "article")]/div[1]/p'
    contentCount = PlayWright.get_count(contentEle)
    contents = []
    for contentId in range(1, contentCount + 1):
        content = PlayWright.get_text(f'({contentEle})[{contentId}]')
        contents.append(content)
    contents = '\n'.join(contents)

    authorEle= '//span[@class="flex flex-row text-xs"]/a/span'
    author = PlayWright.get_text(authorEle) if PlayWright.get_count(authorEle) else ''
    rowInfo['contents'] = contents
    rowInfo['publishTime'] = publishTime[5:]
    rowInfo['author'] = author
    rowInfo['url'] = link
    return rowInfo


def getRowsDetail(startDate, vpn):
    csvFile = os.path.join(BASE_DIR, 'yesterday.csv')
    fileHeader = ['title', 'date', 'url', 'author', 'content']
    fileExists = os.path.exists(csvFile)
    rowsInfo = getPageInfo(startDate, vpn)
    logger.info(f'共{len(rowsInfo)}条数据')
    with open(csvFile, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fileHeader, extrasaction='ignore')

        # 文件不存在时才写入表头（追加模式不重复写入表头）
        if not fileExists:
            writer.writeheader()

        # 遍历处理每一行数据
        for rowInfo in rowsInfo:
            logger.info(f'爬取详情：{rowInfo}')
            rowInfo = getRowDetail(rowInfo, startDate)

            # 只处理有发布时间的数据
            if rowInfo.get('publishTime'):
                # 构造符合表头格式的数据字典
                csv_row = {
                    'title': rowInfo.get('title', ''),
                    'date': rowInfo.get('publishTime', ''),
                    'url': rowInfo.get('url', ''),
                    'author': rowInfo.get('author', ''),
                    'content': rowInfo.get('contents', '')
                }

                # 逐行追加写入CSV
                logger.info(rowInfo)
                writer.writerow(csv_row)

                # 可选：立即刷新到磁盘，防止数据丢失
                f.flush()

def download(url, file, vpn=None):
    file = file.replace('/', '-').replace(' ', '-')
    for roll in range(1, 4):
        try:
            logger.info(f'开始第{roll}次尝试下载{file}....')
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            fileName = os.path.join(BASE_DIR, file)
            with open(fileName, 'wb') as f:
                if vpn:
                    f.write(requests.get(url, headers=headers, proxies={'http': f'http://{vpn}',  'https': f'http://{vpn}'}).content)
                else:
                    f.write(requests.get(url, headers=headers).content)
                logger.info(f'{file}保存成功\n')
                break
        except Exception as e:
            logger.error(f'{file}下载失败：{e}\n')
        finally:
            time.sleep(2)


def getOpecReport(vpn):
    t = time.localtime(time.time() - 86400*30)
    lastMonth = t.tm_mon
    lastYear = t.tm_year
    lastMonthEn = time.strftime("%B", time.localtime(time.mktime((lastYear, lastMonth, 1, 0, 0, 0, 0, 0, 0)))).lower()

    url = f'https://www.opec.org/assets/assetdb/momr-{lastMonthEn}-{lastYear}.pdf'
    file = f'opec_{lastYear}_{lastMonth}.pdf'
    download(url, file, vpn)


def getEivlist(vpn):
    PlayWright.goto('https://www.eia.gov/reports/#/T198,T1255', proxy={'server': f'http://{vpn}'})
    time.sleep(10)
    t = time.localtime(time.time() - 86400*30)
    lastMonth = t.tm_mon
    lastYear = t.tm_year

    lastMonthEn = time.strftime("%B", time.localtime(time.mktime((lastYear, lastMonth, 1, 0, 0, 0, 0, 0, 0)))).lower()

    rowEle = '//div[@class="b_content"]'
    rowsCount = PlayWright.get_count(rowEle)
    data = []
    for rowIdx in range(1, rowsCount + 1):
        publishTime = PlayWright.get_text(f'({rowEle})[{rowIdx}]/h4[@class="dat bookshelf"]')
        if lastMonthEn in publishTime.lower() and str(lastYear) in publishTime:
            pdfEle = f'({rowEle})[{rowIdx}]//a[@class="ico pdf"]'
            htmlEle = f'({rowEle})[{rowIdx}]//a[@class="ico html"]'

            title = publishTime + PlayWright.get_text(f'({rowEle})[{rowIdx}]/h3/a')
            extraEle = f'({rowEle})[{rowIdx}]/h3/em'
            if PlayWright.get_count(extraEle):
                title += PlayWright.get_text(extraEle)

            if PlayWright.get_count(pdfEle):
                file = title + '.pdf'
                url = 'https://www.eia.gov' + PlayWright.get_attribute(pdfEle, 'href')
                logger.info(f'{title}存在pdf数据')
                download(url, file, vpn)
                data.append(url)
            elif PlayWright.get_count(htmlEle):
                # file = title + '.html'
                url = 'https://www.eia.gov' + PlayWright.get_attribute(htmlEle, 'href')
                logger.info(f'{title}存在html数据，请手动复制链接\n{url}\n')
                # download(url, file, vpn)
                data.append(url)
    if not data:
        logger.info(f'{lastYear} {lastMonth}暂无匹配数据')

def getJianXinDaily(startDate):
    PlayWright.goto('https://www.ccbfutures.com/main/research/research_report/survey_studies/chemical_industry/index.shtml')
    time.sleep(15)
    rowEle = '//div[@class="imp_news clearfix"]/ul/li'
    rowsCount = PlayWright.get_count(rowEle)
    for rowIdx in range(1, rowsCount + 1):
        publishTime = PlayWright.get_text(f'({rowEle})[{rowIdx}]/span[@class="time"]')
        titleEle = f'({rowEle})[{rowIdx}]/a'
        title = PlayWright.get_text(titleEle)[4:]
        if '原油日评' not in title or publishTime not in startDate:
            continue
        href = 'https://www.ccbfutures.com' + PlayWright.get_attribute(titleEle, 'href')
        download(href, title)
    # PlayWright.click(f'//a[@class="ddd" and text()="{page}"]')




if __name__ == '__main__':
    while True:
        step = input('请输入操作步骤(1获取投资信息，2获取OPEC月度报告，3获取eiv月度报告，4获取建信日评)：')
        if step == '1':
            startDate = input('请输入指定日期(例如：2026-07-17)：')
            vpn = input('请输入VPN代理(例如：127.0.0.1:7892)：')
            getRowsDetail(startDate, vpn)
        elif step == '2':
            vpn = input('请输入VPN代理(例如：127.0.0.1:7892)：')
            getOpecReport(vpn)
        elif step == '3':
            vpn = input('请输入VPN代理(例如：127.0.0.1:7892)：')
            getEivlist(vpn)
        elif step == '4':
            # startDate = input('请输入指定日期(例如：2026-07-17)：')
            startDate = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
            getJianXinDaily(startDate)

            
            


