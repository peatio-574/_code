# -*- coding: utf-8 -*-

"""
小红书封装函数
"""
import re
from PlayWright import Playwright_, logger
import time

host = 'https://www.xiaohongshu.com'
comment_ids = list()


def login():
    """小红薯登录"""
    logger.info('登录小红书....')
    ele = '//li/div/a//span[text()="我"]'
    key = 'login.xiaohongshu'
    Playwright_.login(host, ele, key)
    logger.info('小红书登录成功')


def search(keyword):
    """搜索商品"""
    Playwright_.input('(//input[@placeholder="搜索小红书"])[2]', keyword, enter=True)
    time.sleep(5)


def get_search_info():
    """获取搜索后的页面信息"""
    count_ele = '//section[@data-height]'
    count = Playwright_.get_count(count_ele)
    infos = list()
    for number in range(1, count + 1):
        # 判断是图文还是视频
        video = Playwright_.get_count(f'({count_ele})[{number}]//span[@class="play-icon"]')
        product_type = 'video' if video == 1 else 'picture'

        # 主图
        main_picture = Playwright_.get_attribute(f'({count_ele})[{number}]/div/a/img', 'src')

        # 标题
        title_ele = f'({count_ele})[{number}]//a[@class="title"]'
        title_count = Playwright_.get_count(title_ele)
        title = Playwright_.get_text(f'({count_ele})[{number}]//a[@class="title"]') if title_count == 1 else ''

        # 作者
        author = Playwright_.get_text(f'({count_ele})[{number}]//div[@class="name"]')

        # 作者头像
        author_picture = Playwright_.get_attribute(f'({count_ele})[{number}]//img[@class="author-avatar"]', 'src')

        # 作者主页链接
        author_url = Playwright_.get_attribute(f'({count_ele})[{number}]//a[@class="author"]', 'href')
        author_url = 'https://www.xiaohongshu.com' + author_url

        # 发布时间
        publish_time = Playwright_.get_text(f'({count_ele})[{number}]//div[@class="time"]')
        publish_time = deal_date(publish_time)

        # 点赞数
        like_count = Playwright_.get_text(f'({count_ele})[{number}]//span[@class="count"]')

        # 详情链接
        detail_url = Playwright_.get_attribute(f'({count_ele})[{number}]/div/a[2]', 'href')
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
        # logger.info('搜索页', info)
    return infos


def get_product_info(url, product_type='picture'):
    """获取作品的详情"""
    try:
        Playwright_.goto(url)

        # 正文
        content_ele = '(//div[@class="desc"]/span/a)[1]/preceding-sibling::span'
        content_count = Playwright_.get_count(content_ele)
        content = Playwright_.get_text(content_ele) if content_count == 1 else ''

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
        picture_ele = '//meta[@name="og:url"]/preceding-sibling::meta[@name="og:image"]'
        picture_count = Playwright_.get_count(picture_ele)
        for picture_ in range(1, picture_count + 1):
            picture = Playwright_.get_attribute(f'({picture_ele})[{picture_}]', 'content')
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
        logger.info(f'作品详情：{product_info}')
        return product_info
    except Exception as e:
        logger.error(f'获取作品详情失败：{e}')
        return dict()


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


def get_reply(comment_ele, comment_, reply_):
    """获取单条回复信息，返回字典"""
    try:
        tmp_ele = f'(({comment_ele})[{comment_}]/div[2]/div/div)[{reply_}]/div/div[2]'
        # 回复内容
        reply_text_ele = f'{tmp_ele}/div/span/*'
        reply_text_count = Playwright_.get_count(reply_text_ele)
        reply_text = ''
        for reply_text_ in range(1, reply_text_count + 1):
            reply_text += Playwright_.get_text(f'{reply_text_ele}[{reply_text_}]')

        # 回复人
        reply_author = Playwright_.get_text(f'{tmp_ele}//div[@class="author"]/a')
        # 回复人链接
        reply_author_url = Playwright_.get_attribute(f'{tmp_ele}/../div[1]/a', 'href')
        # 回复时间
        reply_time = Playwright_.get_text(f'{tmp_ele}//div[@class="date"]/span[1]')
        reply_time = deal_date(reply_time)
        # 回复地点
        reply_addr = Playwright_.get_text(f'{tmp_ele}//span[@class="location"]')
        # 回复点赞数
        reply_like_count = Playwright_.get_text(f'{tmp_ele}//div[@class="like"]/span/span[2]')
        reply_like_count = reply_like_count if reply_like_count != '赞' else '0'
        reply_info = {
            'reply_text': reply_text,
            'reply_author': reply_author,
            'reply_author_url': reply_author_url,
            'reply_time': reply_time,
            'reply_addr': reply_addr,
            'reply_like_count': reply_like_count
        }
        logger.info(f'第{comment_}条评论的第{reply_}条回复：{reply_info["reply_text"]}')
        return reply_info
    except Exception as e:
        logger.error(f'第{comment_}条评论的第{reply_}条回复信息，获取失败：{e}')
        return dict()


def reply_click_expand(comment_ele, comment_):
    """回复区点击查看更多，返回bool"""
    try:
        expand_ele = f'({comment_ele})[{comment_}]/div[2]/div[2]'
        time_ = 0
        while True:
            expand_count = Playwright_.get_count(expand_ele)
            if expand_count == 0 or time_ == 8:
                break
            Playwright_.click(expand_ele)  # 点击展开查看更多
            time_ += 1
            # logger.info(f'第{comment_}条评论，第{time_}次点击<查看更多回复>按钮')
            time.sleep(1)
        logger.info(f'第{comment_}条评论，点击<查看更多回复信息>成功')
        return True
    except Exception as e:
        logger.error(f'第{comment_}条评论，点击<查看更多回复信息>失败：{e}')
        return False


def get_comment(comment_ele, comment_):
    """获取单条评论信息（不含回复信息），返回字典"""
    global comment_ids
    try:
        # 评论id
        comment_id_ele = f'({comment_ele})[{comment_}]/div[1]'
        comment_id = Playwright_.get_attribute(comment_id_ele, 'id')

        # 立即检查是否已存在，避免重复处理
        if comment_id in comment_ids:
            logger.debug(f'id为{comment_id}的评论已获取，跳过')
            return None

        # 评论内容
        comment_msg_ele = f'({comment_ele})[{comment_}]/div[1]//div[@class="content"][1]/span/span'
        comment_msg_count = Playwright_.get_count(comment_msg_ele)
        comment_text = ''
        for comment_msg_ in range(1, comment_msg_count + 1):
            comment_msg = Playwright_.get_text(f'({comment_msg_ele})[{comment_msg_}]')
            comment_text += comment_msg
        # 评论人
        comment_author = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="author"]/a')
        # 评论人链接
        comment_author_url = Playwright_.get_attribute(f'({comment_ele})[{comment_}]/div[1]//div[@class="author"]/a',
                                                       'href')
        # 评论时间
        comment_time = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="date"]/span[1]')
        comment_time = deal_date(comment_time)
        # 评论地点
        comment_addr = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="date"]/span[2]')
        # 评论点赞数
        comment_like_count = Playwright_.get_text(
            f'({comment_ele})[{comment_}]/div[1]//div[@class="like"]/span/span[2]')
        # 评论回复数
        comment_replay_count = Playwright_.get_text(
            f'({comment_ele})[{comment_}]/div[1]//div[@class="reply icon-container"]/span')
        comment_replay_count = comment_replay_count if comment_replay_count != '回复' else '0'

        comment_info = {
            'comment_id': comment_id,
            'comment_text': comment_text,
            'comment_author': comment_author,
            'comment_author_url': comment_author_url,
            'comment_time': comment_time,
            'comment_addr': comment_addr,
            'comment_like_count': comment_like_count,
            'comment_replay_count': comment_replay_count,
        }
        logger.info(f'第{comment_}条，id为{comment_id}的评论：{comment_info["comment_text"]}')

        # 立即更新comment_ids，防止重复
        comment_ids.append(comment_id)

        return comment_info
    except Exception as e:
        logger.error(f'第{comment_}条评论信息获取失败：{e}')
        return None


def get_page_comment(reply_flag=False):
    """获取当前页评论"""
    comment_ele = '//div[@class="parent-comment"]'
    comment_count = Playwright_.get_count(comment_ele)
    comments = list()
    for comment_ in range(1, comment_count + 1):
        # 获取评论信息
        comment_info = get_comment(comment_ele, comment_)

        # 跳过已存在的评论或获取失败的评论
        if comment_info is None:
            continue

        if not reply_flag:
            comments.append(comment_info)
            continue

        comment_replay_count = comment_info.get('comment_replay_count', '0')

        # 没有回复
        if comment_replay_count == '0':
            comment_info['reply_details'] = list()
            comment_info['expand'] = False
            comment_info['reply_count'] = 0
            comments.append(comment_info)
            continue

        # 有回复，点击展开查看更多
        expand = reply_click_expand(comment_ele, comment_)

        # 获取回复信息
        reply_ele = f'({comment_ele})[{comment_}]/div[2]/div[1]/div'
        reply_count = Playwright_.get_count(reply_ele)  # 回复数量

        reply_details = list()
        for reply_ in range(1, reply_count):
            # 单条回复信息
            reply_info = get_reply(comment_ele, comment_, reply_)
            reply_details.append(reply_info)

        comment_info['reply_details'] = reply_details
        comment_info['reply_count'] = len(reply_details)
        comment_info['expand'] = expand
        comments.append(comment_info)
    return comments


def reset_comment_ids():
    """重置评论ID列表，用于新的爬取任务"""
    global comment_ids
    comment_ids = list()
    logger.info('评论ID列表已重置')


def get_all_comments():
    """获取作品所有评论"""
    page_roll = Playwright_.click('//div[@class="comments-container"]/..')
    page_roll.click()
    end_ele = '//div[@class="end-container"]'

    all_comments = list()
    page_num = 0

    while True:
        page_num += 1
        # 获取单页评论
        page_comments = get_page_comment(reply_flag=True)
        all_comments.extend(page_comments)

        logger.info(f'第{page_num}页，当前已获取 {len(all_comments)} 条评论')

        end_count = Playwright_.get_count(end_ele)
        if end_count:
            logger.info('已到达评论区底部')
            break
        for i in range(11):
            Playwright_.page.keyboard.press('PageDown')
        time.sleep(1)

    logger.info(f'总共获取 {len(all_comments)} 条评论')
    return all_comments

def get_author_url():
    """获取博主url"""
    author_ele = '//div[@class="onebox"]/a'
    author_url = Playwright_.get_attribute(author_ele, 'href')
    author_url = host + author_url
    return author_url

def get_author_info():
    user_name = Playwright_.get_text('//div[@class="user-name"]')
    user_code = Playwright_.get_text('//span[@class="user-redId"]')
    user_ip = Playwright_.get_text('//span[@class="user-IP"]')
    user_description = Playwright_.get_text('//div[@class="user-desc"]')
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
            product_url = Playwright_.get_attribute(f'({product_ele})[{product_}]/div/a[2]', 'href')
            product_url = host + product_url
            if product_url not in urls:
                print(product_url)
                urls.append(product_url)
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






if __name__ == '__main__':
    login()
    url = 'https://www.xiaohongshu.com/user/profile/63bd52fc0000000028018127?xsec_token=ABL7P0uZWxdbWlv2P-i7_SqhLf8a9zrzRTmPHTY9JIjqs%3D&xsec_source=pc_search'
    Playwright_.goto(url)
    get_author_urls()