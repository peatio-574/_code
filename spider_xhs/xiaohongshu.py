# -*- coding: utf-8 -*-

"""
小红书封装函数
"""
import re
from PlayWright import Playwright_, logger
import time
import requests
import os

host = 'https://www.xiaohongshu.com'

dirName = os.path.join(os.path.dirname(__file__), '数据')


def login():
    """小红薯登录"""
    logger.info('登录小红书....')
    ele = '//li/div/a//span[text()="我"]'
    key = 'login.xiaohongshu'
    Playwright_.login(host, ele, key)
    logger.info('小红书登录成功')


def search(keyword):
    """搜索商品"""
    Playwright_.input('(//div[@class="textarea-wrapper"])[2]/textarea', keyword, enter=True)
    time.sleep(5)


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
    comments = list()
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
                comments.append(comment_info)

        if record_count == len(comments):
            logger.info('当前没有新评论了，已获取所有评论')
            break

        record_count = len(comments)
        for i in range(5):
            Playwright_.page.keyboard.press('PageDown')
    return comments


def get_author_url():
    """获取博主url"""
    author_ele = '//div[@class="onebox"]/a'
    author_url = Playwright_.get_attribute(author_ele, 'href')
    author_url = host + author_url
    return author_url

def get_author_info():
    """获取博主信息"""
    user_name = Playwright_.get_text('//div[@class="user-name"]')

    user_code = Playwright_.get_text('//span[@class="user-redId"]')

    user_ip_ele = '//span[@class="user-IP"]'
    user_ip = Playwright_.get_text(user_ip_ele) if Playwright_.get_count(user_ip_ele) else ''

    user_description_ele = '//div[@class="user-desc"]'
    user_description = Playwright_.get_text(user_description_ele) if Playwright_.get_count(user_description_ele) else ''

    tag_ele = '//div[@class="tag-item"]/div[not(contains(@class,"gender"))]'
    tag_count = Playwright_.get_count(tag_ele)
    user_tag = ''
    if tag_count:
        for tag_ in range(1, Playwright_.get_count(tag_ele) + 1):
            user_tag += Playwright_.get_text(f'({tag_ele})[{tag_}]') + ','
        user_tag = user_tag[:-1]
    return {
        'user_name': user_name,
        'user_code': user_code,
        'user_ip': user_ip,
        'user_description': user_description,
        'user_tag': user_tag,
    }


def get_author_urls():
    urls = []
    record_count = 0
    while len(urls) < 100:
        time.sleep(3)
        product_ele = '//section[@data-height]'
        product_count = Playwright_.get_count(product_ele)
        if product_count == 0:
            break


        for product_ in range(1, product_count + 1):
            if len(urls) == 100:
                break
            title = Playwright_.get_text(f'({product_ele})[{product_}]/div/div/a[1]/span')
            product_url = Playwright_.get_attribute(f'({product_ele})[{product_}]/div/a[2]', 'href')
            product_url = host + product_url
            if product_url not in urls:
                urls.append([title, product_url])
        if record_count == len(urls):
            logger.info('当前没有新作品了，已获取所有作品链接')
            break

        record_count = len(urls)
        if len(urls) >= 100:
            break
        Playwright_.page.keyboard.press('PageDown')
        Playwright_.page.keyboard.press('PageDown')
        Playwright_.page.keyboard.press('PageDown')
    return urls


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


def get_product_info(url, currentDir='./数据'):
    """获取作品的详情"""
    try:
        Playwright_.goto(url)

        # 正文
        content_ele = '(//div[@class="desc"]/span/a)[1]/preceding-sibling::span'
        content_count = Playwright_.get_count(content_ele)
        content = Playwright_.get_text(content_ele) if content_count else ''

        # 标题
        title_ele = '//div[@class="note-content"]/div[@class="title"]'
        title = Playwright_.get_text(title_ele)

        # 标签
        tag_ele = '//a[@class="tag"]'
        tag_count = Playwright_.get_count(tag_ele)
        tags = list()
        for tag_ in range(1, tag_count + 1):
            tag = Playwright_.get_text(f'({tag_ele})[{tag_}]')
            tags.append(tag)

        # 发布时间
        publish_time = Playwright_.get_text('//span[@class="date"]')
        publish_time = deal_date(publish_time)

        # 点赞数
        like_count = Playwright_.get_text('//div[@class="left"]/span[1]/span[2]')
        # # 收藏数
        # collect_count = Playwright_.get_text('//div[@class="left"]/span[2]/span')
        # 评论数
        comment_count = Playwright_.get_text('//div[@class="left"]/span[3]/span')

        # 作品图片
        pictures = list()
        picture_ele = '//meta[@name="og:url"]/preceding-sibling::meta[@name="og:image"]'
        picture_count = Playwright_.get_count(picture_ele)
        picture_count = min(picture_count, 5)
        for picture_ in range(1, picture_count + 1):
            picture = Playwright_.get_attribute(f'({picture_ele})[{picture_}]', 'content')
            pictures_date = requests.get(picture).content

            pic_name = os.path.join(currentDir, f'{title[:18]}_{publish_time[:10]}_{picture_}.jpg')
            with open(pic_name, 'wb') as f:
                f.write(pictures_date)
            pictures.append(pic_name)

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




if __name__ == '__main__':
    login()
    search('909030373')
    author_url = get_author_url()
    logger.info(f'作者链接：{author_url}')
    Playwright_.goto(author_url)
    author_info = get_author_info()
    logger.info(f'作者信息：{author_info}')
    urls = get_author_urls()
    logger.info(f'作品链接：{urls[:5]}')
    for url in urls:
        product_info = get_product_info(url[1])
        logger.info(f'作品详情：{product_info}')
        coments = get_page_comment
        logger.info(f'作品评论：{coments}')

        break