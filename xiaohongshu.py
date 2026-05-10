# -*- coding: utf-8 -*-

"""
小红书封装函数
"""
import re
from PlayWright import Playwright_, logger
import time

host = 'https://www.xiaohongshu.com/'
comment_ids = list()


def login():
    """小红薯登录"""
    logger.info('登录小红书....')
    ele = '//li[5]/div/a[@title="我"]'
    key = 'login.xiaohongshu'
    Playwright_.login(host, ele, key)
    logger.info('小红书登录成功')


def search(keyword):
    """搜索商品"""
    Playwright_.input('(//input[@placeholder="搜索小红书"])[2]', keyword, enter=True)
    time.sleep(10)

def get_search_info():
    """获取搜索后的页面信息"""
    count_ele = '//section[@data-height]'
    count = Playwright_.get_count(count_ele)
    infos = list()
    for number in range(1, count+1):
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
        for tag_ in range(1, tag_count+1):
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
        for picture_ in range(1, picture_count+1):
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
        for reply_text_ in range(1, reply_text_count+1):
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
        return  dict()

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
        if comment_id in comment_ids:
            # logger.info(f'id为{comment_id}的评论已获取，跳过')
            return dict()

        # 评论内容
        comment_msg_ele = f'({comment_ele})[{comment_}]/div[1]//div[@class="content"][1]/span/span'
        comment_msg_count = Playwright_.get_count(comment_msg_ele)
        comment_text = ''
        for comment_msg_ in range(1, comment_msg_count + 1):
            comment_msg = Playwright_.get_text(f'({comment_msg_ele})[{comment_msg_}]')
            comment_text += comment_msg
        # 评论人
        comement_author = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="author"]/a')
        # 评论人链接
        comement_author_url = Playwright_.get_attribute(f'({comment_ele})[{comment_}]/div[1]//div[@class="author"]/a',
                                                        'href')
        # 评论时间
        comment_time = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="date"]/span[1]')
        comment_time = deal_date(comment_time)
        # 评论地点
        comment_addr = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="date"]/span[2]')
        # 评论点赞数
        comment_like_count = Playwright_.get_text(f'({comment_ele})[{comment_}]/div[1]//div[@class="like"]/span/span[2]')
        # 评论回复数
        comment_replay_count = Playwright_.get_text(
            f'({comment_ele})[{comment_}]/div[1]//div[@class="reply icon-container"]/span')
        comment_replay_count = comment_replay_count if comment_replay_count != '回复' else '0'

        comment_info = {
            'comment_id': comment_id,
            'comnent_text': comment_text,
            'comement_author': comement_author,
            'comement_author_url': comement_author_url,
            'comment_time': comment_time,
            'comment_addr': comment_addr,
            'comment_like_count': comment_like_count,
            'comment_replay_count': comment_replay_count,
        }
        logger.info(f'id为{comment_id}的评论：{comment_info["comnent_text"]}')
        return comment_info
    except Exception as e:
        logger.error(f'第{comment_}条评论信息获取失败：{e}')
        return dict()

def get_page_comment(reply_falg=False):
    """获取当前页评论"""
    comment_ele = '//div[@class="parent-comment"]'
    comment_count = Playwright_.get_count(comment_ele)
    comments = list()
    for comment_ in range(1, comment_count+1):
        # 获取评论信息
        comment_info = get_comment(comment_ele, comment_)
        if not reply_falg:
            comments.append(comment_info)
            continue

        comment_replay_count = comment_info.get('comment_replay_count', '0')

        # 没有回复
        if comment_replay_count == '0':
            comment_info['reply_details'] = list()
            comment_info['expand'] = False
            comment_info['reply_count'] = 0
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

def get_all_comments():
    """获取作品所有评论"""
    page_roll_ele = '//div[@class="comments-container"]/..'
    page_roll = Playwright_.page.locator(page_roll_ele)
    page_roll.click()
    end_ele = '//div[@class="end-container"]'

    global comment_ids

    while True:
        # 获取单页评论数量
        comments = get_page_comment(reply_falg=True)
        comment_ids += [comment.get('comment_id', '') for comment in comments]
        comment_ids = list(set(comment_ids))

        end_count = Playwright_.get_count(end_ele)
        if end_count:
            time.sleep(1000)
            break
        for i in range(11):
            Playwright_.page.keyboard.press('PageDown')
        time.sleep(1)

if __name__ == '__main__':
    login()
    url = 'https://www.xiaohongshu.com/explore/69e0b0cf000000001b001ba3?xsec_token=ABT97hHGpC3Ci_HspNOJ1LviYm7K8ezD33S6zGzWadYwo=&xsec_source=pc_cfeed'

    Playwright_.goto(url)
    get_product_info(url, 'video')
    get_all_comments()

    # search('成都')
    # search_info = get_search_info()
    # for search_ in search_info:
    #     if search_ == search_info[2]:
    #         url = search_['detail_url']
    #         product_type = search_['product_type']
    #         logger.info(url)
    #         get_product_info(url, product_type)
    #         get_all_comments()
    #         break

