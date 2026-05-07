# -*- coding: utf-8 -*-

"""
小红书封装函数
"""
import re
import requests
from PlayWright import Playwright_
import time
from Logger import logger


host = 'https://www.xiaohongshu.com/'


def login():
    """小红薯登录"""
    logger.info('登录小红书....')
    location = '//li[5]/div/a[@title="我"]'
    key = 'login.xiaohongshu'
    Playwright_.login(host, location, key)
    logger.info('小红书登录成功')


def search(keyword):
    """搜索商品"""
    Playwright_.input('(//input[@placeholder="搜索小红书"])[2]', keyword, enter=True)
    time.sleep(10)

def get_search_info():
    """获取搜索后的页面信息"""
    count_location = '//section[@data-height]'
    count = Playwright_.get_count(count_location)
    infos = list()
    for number in range(1, count+1):
        # 判断是图文还是视频
        video = Playwright_.get_count(f'({count_location})[{number}]//span[@class="play-icon"]')
        product_type = 'video' if video == 1 else 'picture'

        # 主图
        main_picture = Playwright_.get_attribute(f'({count_location})[{number}]/div/a/img', 'src')

        # 标题
        title_location = f'({count_location})[{number}]//a[@class="title"]'
        title_count = Playwright_.get_count(title_location)
        title = Playwright_.get_text(f'({count_location})[{number}]//a[@class="title"]') if title_count == 1 else ''

        # 作者
        author = Playwright_.get_text(f'({count_location})[{number}]//div[@class="name"]')

        # 作者头像
        author_picture = Playwright_.get_attribute(f'({count_location})[{number}]//img[@class="author-avatar"]', 'src')

        # 作者主页链接
        author_url = Playwright_.get_attribute(f'({count_location})[{number}]//a[@class="author"]', 'href')
        author_url = 'https://www.xiaohongshu.com' + author_url

        # 发布时间
        publish_time = Playwright_.get_text(f'({count_location})[{number}]//div[@class="time"]')
        publish_time = deal_date(publish_time)

        # 点赞数
        like_count = Playwright_.get_text(f'({count_location})[{number}]//span[@class="count"]')

        # 详情链接
        detail_url = Playwright_.get_attribute(f'({count_location})[{number}]/div/a[2]', 'href')
        detail_url = 'https://www.xiaohongshu.com' + detail_url

        # 作品code
        uniqo_code = re.findall(r'search_result/(.*?)\?', detail_url)[0]
        info = {
            'title': title,
            'product_type': product_type,
            'main_picture': main_picture,
            'author': author,
            'author_picture': author_picture,
            'author_url': author_url,
            'publish_time': publish_time,
            'like_count': like_count,
            'detail_url': detail_url,
            'uniqo_code': uniqo_code
        }
        infos.append(info)
        print('搜索页', info)
    return infos

def get_product_info(url, product_type='picture'):
    """获取作品的详情"""
    Playwright_.goto(url)

    # 正文
    content_location = '(//div[@class="desc"]/span/a)[1]/preceding-sibling::span'
    content_count = Playwright_.get_count(content_location)
    content = Playwright_.get_text(content_location) if content_count == 1 else ''

    # 标签
    tag_location = '//a[@class="tag"]'
    tag_count = Playwright_.get_count(tag_location)
    tags = list()
    for tag_ in range(1, tag_count+1):
        tag = Playwright_.get_text(f'({tag_location})[{tag_}]')
        tags.append(tag)

    # 发布时间
    publish_time = Playwright_.get_text('//span[@class="date"]')
    publish_time = deal_date(publish_time)
    # 发布地点
    publish_addr = publish_time.split(' ')[-1]

    # 点赞数
    like_count = Playwright_.get_text('//div[@class="left"]/span[1]/span[2]')
    # 收藏数
    collect_count = Playwright_.get_text('//div[@class="left"]/span[2]/span')
    # 评论数
    comment_count = Playwright_.get_text('//div[@class="left"]/span[3]/span')

    # 作品图片
    pictures = list()
    picture_location = '//meta[@name="og:url"]/preceding-sibling::meta[@name="og:image"]'
    picture_count = Playwright_.get_count(picture_location)
    for picture_ in range(1, picture_count+1):
        picture = Playwright_.get_attribute(f'({picture_location})[{picture_}]', 'content')
        pictures.append(picture)

    product_info = {
        'content': content,
        'tags': tags,
        'publish_time': publish_time,
        'publish_addr': publish_addr,
        'like_count': like_count,
        'collect_count': collect_count,
        'comment_count': comment_count,
        'pictures': pictures
    }

    if product_type == 'video':
        video_url = Playwright_.get_attribute('//meta[@name="og:video"]', 'content')
        product_info['video_url'] = video_url
    print('详情页', product_info)

    return product_info

def deal_date(date):
    today = time.strftime('%Y-%m-%d', time.localtime())
    yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
    for i in range(1, 20):
        date = date.replace(f'{i}天前', time.strftime('%Y-%m-%d', time.localtime(time.time() - i * 86400)))
    date = date.replace('昨天', yesterday)
    date = date.replace('今天', today)
    return date

def get_product_comment():
    """获取作品的评论"""
    comment_location = '//div[@class="parent-comment"]'
    comment_count = Playwright_.get_count(comment_location)
    comments = list()
    for comment_ in range(1, comment_count+1):
        # 评论内容
        comment_msg_location = f'({comment_location})[{comment_}]/div[1]//div[@class="content"][1]/span/span'
        comment_msg_count = Playwright_.get_count(comment_msg_location)
        comment_text = ''
        for comment_msg_ in range(1, comment_msg_count+1):
            comment_msg = Playwright_.get_text(f'({comment_msg_location})[{comment_msg_}]')
            comment_text += comment_msg
        # 评论人
        comement_author = Playwright_.get_text(f'({comment_location})[{comment_}]/div[1]//div[@class="author"]/a')
        # 评论时间
        comment_time = Playwright_.get_text(f'({comment_location})[{comment_}]/div[1]//div[@class="date"]/span[1]')
        comment_time = deal_date(comment_time)
        # 评论地点
        comment_addr = Playwright_.get_text(f'({comment_location})[{comment_}]/div[1]//div[@class="date"]/span[2]')
        # 评论点赞数
        comment_like_count = Playwright_.get_text(f'({comment_location})[{comment_}]/div[1]//div[@class="like"]/span/span[2]')
        # 评论被回复数
        comment_replay_count = Playwright_.get_text(f'({comment_location})[{comment_}]/div[1]//div[@class="reply icon-container"]/span')
        comment_replay_count = comment_replay_count if comment_replay_count != '回复' else '0'

        comment_info = {
            'comnent_text': comment_text,
            'comement_author': comement_author,
            'comment_time': comment_time,
            'comment_addr': comment_addr,
            'comment_like_count': comment_like_count,
            'comment_replay_count': comment_replay_count
        }
        comments.append(comment_info)
    return comments

if __name__ == '__main__':
    login()
    search('成都')
    search_info = get_search_info()
    for search_ in search_info:
        url = search_['detail_url']
        product_type = search_['product_type']
        print(url)
        get_product_info(url, product_type)
        get_product_comment()

