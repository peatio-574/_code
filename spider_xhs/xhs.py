# -*- coding: utf-8 -*-

"""
小红书封装函数
"""


import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from PlayWright import Playwright_, logger
import time
import requests
import os
import json
from openpyxl import load_workbook



config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

host = 'https://www.xiaohongshu.com'

dirName = os.path.join(os.path.dirname(__file__), '数据')
os. makedirs(dirName, exist_ok=True)


def login():
    """小红薯登录"""
    logger.info('登录小红书....')
    ele = '//li/div/a//span[text()="我"]'
    key = 'login.xiaohongshu'
    Playwright_.login(host, ele, key, file=config_file)
    logger.info('小红书登录成功')


def get_comment(comment_ele, comment_):
    """获取单条评论信息（不含回复信息），返回字典"""
    comment_str = ''
    try:
        # 评论内容
        comment_msg_ele = f'({comment_ele})[{comment_}]/div[1]//div[@class="content"][1]/span/span'
        comment_msg_count = Playwright_.get_count(comment_msg_ele)
        comment_text = ''
        for comment_msg_ in range(1, comment_msg_count + 1):
            comment_msg = Playwright_.get_text(f'({comment_msg_ele})[{comment_msg_}]')
            comment_text += comment_msg
        # 评论人
        comment_author = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="author"]/a')

        # 评论时间
        comment_time = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="date"]/span[1]')
        comment_time = deal_date(comment_time)
        # 评论地点
        comment_addr = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="date"]/span[2]')
        comment_str = f'用户：{comment_author}|内容：{comment_text}|时间：{comment_time}|IP：{comment_addr}'
        return comment_str
    except Exception as e:
        logger.error(f'第{comment_}条评论信息获取失败：{e}')
        return comment_str


def get_page_comment():
    """获取20条评论"""
    comment_ele = '//div[@class="parent-comment"]'
    comments = []
    record_count = 0
    while len(comments) < 20:
        comment_count = Playwright_.get_count(comment_ele)
        for comment_ in range(1, comment_count + 1):
            # 获取评论信息
            comment_info = get_comment(comment_ele, comment_)

            # 跳过已存在的评论或获取失败的评论
            if comment_info is None:
                continue
            if comment_info not in comments:
                logger.info(comment_info)
                comments.append(comment_info)

        if record_count == len(comments):
            # logger.info('当前没有新评论了，已获取所有评论')
            break

        record_count = len(comments)
        for i in range(5):
            Playwright_.page.keyboard.press('PageDown')
    return comments


def deal_date(date):
    """处理发布、评论、回复时间"""
    today = time.strftime('%Y-%m-%d', time.localtime())
    yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
    for i in range(1, 20):
        date = date.replace(f'{i}天前', time.strftime('%Y-%m-%d', time.localtime(time.time() - i * 86400)))
        date = date.replace(f'前{i}天', time.strftime('%Y-%m-%d', time.localtime(time.time() - i * 86400)))
    date = date.replace('昨天', yesterday)
    date = date.replace('今天', today)
    return date


def deal_str(title_text):
    import re
    pattern = r'[^\u4e00-\u9fa5a-zA-Z0-9_\-=\+\.,，。&~！!()（） ]'
    title_text = re.sub(pattern, '', title_text)
    return title_text


def get_product_info(url, title, currentDir):
    """获取作品的详情"""
    try:
        Playwright_.goto(url)
        time.sleep(3)
        close_ele = '//div[contains(@class, "close-button")]'

        error_ele = '//div[text()="访问频繁，请稍后再试"]'
        if Playwright_.get_count(error_ele):
            logger.error('❌️ 访问频繁，请稍后再试')
            exit()

        if Playwright_.get_count(close_ele):
            Playwright_.click(close_ele)

        # 正文
        content_ele = '//div[@class="desc"]/span/span'
        content_count = Playwright_.get_count(content_ele)
        content = ''
        for content_ in range(1, content_count + 1):
            content += Playwright_.get_text(f'({content_ele})[{content_}]')

        # 标签
        tag_ele = '//a[@class="tag"]'
        tag_count = Playwright_.get_count(tag_ele)
        tags = list()
        for tag_ in range(1, tag_count + 1):
            tag = Playwright_.get_text(f'({tag_ele})[{tag_}]')
            tags.append(tag)
        tags = '，'.join(tags)

        # 发布时间
        publish_time = Playwright_.get_text('//span[@class="date"]', timeout=5*1000)
        publish_time = deal_date(publish_time)

        # 点赞数
        like_count = Playwright_.get_text('//div[@class="left"]/span[1]/span[2]')
        like_count = like_count if like_count != '点赞' else '0'

        # 评论数
        comment_count = Playwright_.get_text('//div[@class="left"]/span[3]/span')
        comment_count = comment_count if comment_count != '评论' else '0'

        # 作品图片
        pictures = list()
        picture_ele = '//meta[@name="og:url"]/preceding-sibling::meta[@name="og:image"]'
        picture_count = Playwright_.get_count(picture_ele)
        picture_count = min(picture_count, 3)
        for picture_ in range(1, picture_count + 1):
            picture = Playwright_.get_attribute(f'({picture_ele})[{picture_}]', 'content')
            pictures_date = requests.get(picture).content

            title_text = deal_str(title)
            pic = f'{title_text[:18]}_{publish_time[:10]}_{picture_}.jpg'
            pic_name = os.path.join(currentDir, pic)
            with open(pic_name, 'wb') as f:
                f.write(pictures_date)
            pictures.append(pic)
        pictures = ','.join(pictures)

        product_info = {
            'content': content,
            'tags': tags,
            'publish_time': publish_time,
            'like_count': like_count,
            'comment_count': comment_count,
            'pictures': pictures
        }
        return product_info
    except Exception as e:
        logger.error(f'获取作品详情失败：{e}')
        return dict()


def run(keyword, extra: list):
    # Playwright_.clear_cookie()
    keyword = f'{str(keyword)}.json'
    file = [file for file in os.listdir(dirName) if keyword in file]
    if not file:
        logger.info(f'{keyword}搜索无结果')
        return
    with open(os.path.join(dirName, file[0]), 'r', encoding='utf-8') as f:
        text = json.load(f)

    author_url = text['博主链接']
    author_info = text['博主详情']
    urls = text['作品'][:80]
    imageDir = text['图片保存目录']
    filename = text['信息保存目录']

    logger.info(f'当前关键字：{keyword}')
    logger.info(f'博主链接：{author_url}')
    logger.info(f'博主详情：{author_info}')
    logger.info(f'共{len(urls)}条作品链接')

    userCode = author_info['user_code']
    userName = author_info['user_name']
    userIp = author_info['user_ip']
    userDescription = author_info['user_description']
    userTag = author_info['user_tag']

    wb = load_workbook(filename)
    ws = wb.active

    start_id = 0
    if extra[1]:
        if extra[0] in keyword:
            start_id = extra[1]
    for idx_, title_url in enumerate(urls[start_id:], start=start_id+1):
        logger.info('\n')
        logger.info('='*80)
        title, url = title_url
        logger.info(f'关键词：{keyword}，当前博主：{userName}，当前标题：{title}')
        logger.info(f'共{len(urls)}条链接，第{idx_}条作品链接：{url}')
        product_info = dict()
        for roll in range(5):
            product_info = get_product_info(url, title, imageDir)
            if product_info:
                break

        if not product_info:
            logger.error(title)
            logger.error('获取作品详情失败')
            continue

        logger.info(f'作品详情：{product_info}')
        coments = get_page_comment()

        row_data = [
            userCode,
            userName,
            userIp,
            userDescription,
            userTag,
            title,
            product_info['publish_time'],
            product_info['content'],
            product_info['tags'],
            product_info['like_count'],
            product_info['comment_count'],
            '\n'.join(coments),
            product_info['pictures']
        ]
        ws.append(row_data)
        wb.save(filename)
        logger.info(f'保存数据成功：{row_data}')
    os.remove(os.path.join(dirName, file[0]))
        # sleep_sec = 5
        # logger.info(f'等待{sleep_sec}秒')
        # time.sleep(sleep_sec)

if __name__ == '__main__':
    import pandas
    data_file = './第一批200用户2026.6.3.xlsx'
    data_ids = pandas.read_excel(data_file, sheet_name=0)['user_id']
    extra = ['123464203', 48]
    login()
    for keyword in data_ids:
        run(keyword, extra)