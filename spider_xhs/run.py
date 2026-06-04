# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger
import os
import time
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment
import json
from xhs import deal_str, deal_date, get_page_comment
import requests

dirName = os.path.join(os.path.dirname(__file__), '数据')
os.makedirs(dirName, exist_ok=True)
config_file = os.path.join(os.path.dirname(__file__), 'config.ini')

host = 'https://www.xiaohongshu.com'


def login():
    """小红薯登录"""
    logger.info('=' * 80)
    logger.info('开始登录小红书....')
    ele = '//li/div/a//span[text()="我"]'
    key = 'login.xiaohongshu1'
    try:
        Playwright_.login(host, ele, key, file=config_file)
        logger.info('✓ 小红书登录成功')
        return True
    except Exception as e:
        logger.error(f'✗ 小红书登录失败：{e}')
        return False


def search(keyword):
    """搜索用户"""
    logger.info(f'开始搜索用户：{keyword}')
    keyword = str(keyword)
    input_ele = '(//input[@placeholder="搜索或输入任何问题"])[2]'
    if Playwright_.get_count(input_ele):
        Playwright_.input(input_ele, keyword, enter=True)
        logger.info(f'已输入搜索关键词：{keyword}')
    else:
        input_ele = '(//div[@class="textarea-wrapper"])[2]/textarea'
        if Playwright_.get_count(input_ele):
            Playwright_.input(input_ele, keyword, enter=True)
            logger.info(f'已输入搜索关键词：{keyword}')
        else:
            logger.warning('未找到搜索输入框')
    time.sleep(5)


def get_author_url():
    """获取博主url"""
    logger.info('正在获取博主主页链接...')
    author_ele = '//div[@class="onebox"]/a'
    if Playwright_.get_count(author_ele) == 0:
        logger.warning('未找到博主主页链接')
        return ''
    author_url = Playwright_.get_attribute(author_ele, 'href')
    author_url = host + author_url
    logger.info(f'✓ 获取到博主主页链接：{author_url}')
    return author_url


def get_author_info():
    """获取博主信息"""
    logger.info('正在获取博主详细信息...')
    try:
        user_name = Playwright_.get_text('//div[@class="user-name"]')
        user_name = user_name.replace(r'\\', '').replace(r'\n', '').replace(r'\r', '').replace(r'\t', '').strip()

        user_code = Playwright_.get_text('//span[@class="user-redId"]')

        user_ip_ele = '//span[@class="user-IP"]'
        user_ip = Playwright_.get_text(user_ip_ele) if Playwright_.get_count(user_ip_ele) else ''
        user_ip = user_ip.strip()

        user_description_ele = '//div[@class="user-desc"]'
        user_description = Playwright_.get_text(user_description_ele) if Playwright_.get_count(
            user_description_ele) else ''

        tag_ele = '//div[@class="tag-item"]/div[not(contains(@class,"gender"))]'
        tag_count = Playwright_.get_count(tag_ele)
        user_tag = ''
        if tag_count:
            for tag_ in range(1, Playwright_.get_count(tag_ele) + 1):
                user_tag += Playwright_.get_text(f'({tag_ele})[{tag_}]') + ','
            user_tag = user_tag[:-1]

        logger.info(f'✓ 博主信息获取成功：{user_name} ({user_code})')
        return {
            'user_name': user_name,
            'user_code': user_code,
            'user_ip': user_ip,
            'user_description': user_description,
            'user_tag': user_tag,
        }
    except Exception as e:
        logger.error(f'✗ 获取博主信息失败：{e}')
        return None


def get_author_title_urls():
    """获取博主作品链接列表"""
    logger.info('开始获取博主作品链接...')
    urls = []
    record_count = 0
    max_urls = 80

    while len(urls) < max_urls:
        time.sleep(3)
        product_ele = '//section[@data-height]'
        product_count = Playwright_.get_count(product_ele)
        if product_count == 0:
            logger.info('当前页面没有作品')
            break

        new_count = 0
        for product_ in range(1, product_count + 1):
            if len(urls) >= max_urls:
                break
            try:
                title = Playwright_.get_text(f'({product_ele})[{product_}]/div/div/a[1]/span')
                product_url = Playwright_.get_attribute(f'({product_ele})[{product_}]/div/a[2]', 'href')
                product_url = host + product_url
                if [title, product_url] not in urls:
                    urls.append([title, product_url])
                    new_count += 1
            except Exception as e:
                logger.warning(f'获取第{product_}个作品链接失败：{e}')
                continue

        logger.info(f'当前已获取 {len(urls)}/{max_urls} 个作品链接，本次新增 {new_count} 个')

        if record_count == len(urls):
            logger.info('没有新的作品链接，已获取所有作品')
            break

        record_count = len(urls)
        if len(urls) >= max_urls:
            break

        logger.info('向下滚动页面加载更多内容...')
        Playwright_.page.keyboard.press('PageDown')
        Playwright_.page.keyboard.press('PageDown')
        Playwright_.page.keyboard.press('PageDown')

    logger.info(f'✓ 作品链接获取完成，共 {len(urls)} 个')
    return urls


def prepare(keywords):
    """准备数据：获取博主信息和作品链接"""
    logger.info('=' * 80)
    logger.info(f'开始批量处理 {len(keywords)} 个关键词')
    logger.info('=' * 80)

    if not login():
        logger.error('登录失败，终止执行')
        return

    success_count = 0
    fail_count = 0

    for idx, keyword in enumerate(keywords, 1):
        logger.info('\n' + '=' * 80)
        logger.info(f'处理进度：[{idx}/{len(keywords)}]')
        logger.info(f'开始处理关键词：{keyword}')
        logger.info('=' * 80)

        try:
            search(keyword)
            author_url = get_author_url()
            if not author_url:
                logger.warning(f'✗ 关键词 {keyword}：未找到博主，跳过')
                fail_count += 1
                continue

            Playwright_.goto(author_url)
            author_info = get_author_info()
            if not author_info:
                logger.warning(f'✗ 关键词 {keyword}：获取博主信息失败，跳过')
                fail_count += 1
                continue

            product_info = get_author_title_urls()

            userCode = author_info['user_code']
            userName = author_info['user_name']
            userName_clean = deal_str(userName)

            currentDate = time.strftime('%Y-%m-%d', time.localtime())
            currentDir = os.path.join(dirName, f'{userCode}_{userName_clean}_{currentDate}')
            os.makedirs(currentDir, exist_ok=True)

            imageDir = os.path.join(currentDir, 'images')
            os.makedirs(imageDir, exist_ok=True)

            filename = os.path.join(currentDir, f'{userCode}_{userName_clean}_{currentDate}.xlsx')

            if os.path.exists(filename):
                wb = load_workbook(filename)
                ws = wb.active
                logger.info(f'加载已有 Excel 文件：{filename}')
            else:
                headers = ['用户ID', '用户名称', 'IP属地', '用户简介', '用户标签',
                           '笔记标题', '编辑时间', '正文文本', '标签', '点赞数',
                           '评论数', '评论列表', '笔记图片']
                wb = Workbook()
                ws = wb.active
                ws.title = '小红书笔记数据'
                ws.append(headers)
                logger.info(f'创建新 Excel 文件：{filename}')
            wb.save(filename)

            # 设置表头样式
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center', vertical='center')

            infoText = os.path.join(dirName, f'{keyword}.json')
            info_dict = {
                '关键词': keyword,
                '博主': author_info['user_name'],
                '博主id': author_info['user_code'],
                '博主链接': author_url,
                '博主详情': author_info,
                '作品': product_info,
                '图片保存目录': imageDir,
                '信息保存目录': filename,
            }

            with open(infoText, 'w', encoding='utf-8') as f:
                json.dump(info_dict, f, ensure_ascii=False, indent=4)
            logger.info(f'✓ JSON 数据已保存：{infoText}')
            logger.info(f'✓ 关键词 {keyword} 处理成功')
            success_count += 1

        except Exception as e:
            logger.error(f'✗ 关键词 {keyword} 处理失败：{e}')
            fail_count += 1

        time.sleep(20)

    logger.info('\n' + '=' * 80)
    logger.info(f'批量处理完成！成功：{success_count}，失败：{fail_count}')
    logger.info('=' * 80)


def get_product_info(title, imageDir):
    """获取作品的详情"""
    try:
        error_ele = '//div[text()="访问频繁，请稍后再试"]'
        if Playwright_.get_count(error_ele):
            logger.error('❌️ 访问频繁，请稍后再试')
            exit()

        close_ele = '//div[contains(@class, "close-button")]'
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
        publish_time = Playwright_.get_text('//span[@class="date"]', timeout=5 * 1000)
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
            pic_name = os.path.join(imageDir, pic)
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


def run(keyword):
    """运行单个用户的数据采集"""
    logger.info('\n' + '=' * 80)
    logger.info(f'开始处理用户：{keyword}')
    logger.info('=' * 80)

    if not login():
        logger.error('登录失败，终止执行')
        return None

    search(keyword)
    author_url = get_author_url()

    if not author_url:
        logger.info(f'✗ 用户 {keyword}：作者不存在')
        return None

    Playwright_.goto(author_url)
    author_info = get_author_info()

    if not author_info:
        logger.error(f'✗ 用户 {keyword}：获取博主信息失败')
        return None

    userCode = author_info['user_code']
    userName = author_info['user_name']
    userName_clean = deal_str(userName)
    userIp = author_info['user_ip']
    userDescription = author_info['user_description']
    userTag = author_info['user_tag']

    logger.info(f'博主信息：{userName} ({userCode})')
    logger.info(f'IP属地：{userIp}')

    currentDate = time.strftime('%Y-%m-%d', time.localtime())
    currentDir = os.path.join(dirName, f'{userCode}_{userName_clean}_{currentDate}')
    os.makedirs(currentDir, exist_ok=True)

    filename = os.path.join(currentDir, f'{userCode}_{userName_clean}_{currentDate}.xlsx')

    imageDir = os.path.join(currentDir, 'images')
    os.makedirs(imageDir, exist_ok=True)

    if os.path.exists(filename):
        wb = load_workbook(filename)
        ws = wb.active
        logger.info(f'加载已有 Excel 文件：{filename}')
    else:
        headers = ['用户ID', '用户名称', 'IP属地', '用户简介', '用户标签',
                   '笔记标题', '编辑时间', '正文文本', '标签', '点赞数',
                   '评论数', '评论列表', '笔记图片']
        wb = Workbook()
        ws = wb.active
        ws.title = '小红书笔记数据'
        ws.append(headers)
        logger.info(f'创建新 Excel 文件：{filename}')
    wb.save(filename)

    # 设置表头样式
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center', vertical='center')

    product = []
    record = 0
    max_products = 80

    logger.info(f'开始采集作品数据，目标数量：{max_products}')

    while len(product) < max_products:
        time.sleep(8)
        product_ele = '//section[@data-height]'
        product_count = Playwright_.get_count(product_ele)
        if product_count == 0:
            logger.info(f'当前没有更多作品，已采集 {len(product)} 个')
            break

        logger.info(f'当前页面有 {product_count} 个作品')

        for product_ in range(1, product_count + 1):
            if len(product) >= max_products:
                break

            logger.info(f'\n--- 处理第 {len(product) + 1}/{max_products} 个作品 ---')

            try:
                title = Playwright_.get_text(f'({product_ele})[{product_}]/div/div/a[1]/span')
                logger.info(f'作品标题：{title}')

                Playwright_.click(f'({product_ele})[{product_}]')
                time.sleep(3)

                product_info = dict()
                for roll in range(5):
                    product_info = get_product_info(title, imageDir)
                    if product_info:
                        logger.info(f'✓ 作品详情获取成功（尝试第{roll + 1}次）')
                        break
                    logger.warning(f'作品详情获取失败，重试第{roll + 1}次...')

                if not product_info:
                    logger.error(f'✗ 作品 "{title}" 获取详情失败')
                    Playwright_.page.mouse.click(60, 300, button='left', click_count=1)
                    continue

                if product_info in product:
                    logger.info('作品已存在，跳过')
                    Playwright_.page.mouse.click(60, 300, button='left', click_count=1)
                    continue

                logger.info(f'正在获取评论数据...')
                coments = get_page_comment()
                logger.info(f'✓ 获取到 {len(coments)} 条评论')

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
                product.append(product_info)
                logger.info(f'✓ 数据已保存，当前共 {len(product)} 个作品')

            except Exception as e:
                logger.error(f'处理作品失败：{e}')
                Playwright_.page.mouse.click(60, 300, button='left', click_count=1)
                continue

            Playwright_.page.mouse.click(60, 300, button='left', click_count=1)

            if record == len(product):
                logger.info('没有新数据，结束采集')
                break
            record = len(product)

        if len(product) >= max_products:
            logger.info(f'已达到目标数量 {max_products}，结束采集')
            break

        logger.info('向下滚动页面加载更多作品...')
        Playwright_.page.keyboard.press('PageDown')
        Playwright_.page.keyboard.press('PageDown')

    logger.info(f'\n✓ 用户 {userName} 数据采集完成，共 {len(product)} 个作品')
    return True


if __name__ == '__main__':
    import pandas

    data_file = './第一批200用户2026.6.3.xlsx'
    data_ids = pandas.read_excel(data_file, sheet_name=0)['user_id']

    logger.info('=' * 80)
    logger.info(f'开始批量处理 {len(data_ids)} 个用户')
    logger.info('=' * 80)

    success_count = 0
    fail_count = 0

    for idx, user_id in enumerate(data_ids, 1):
        logger.info('\n' + '=' * 80)
        logger.info(f'总体进度：[{idx}/{len(data_ids)}]')
        logger.info('=' * 80)

        try:
            result = run(user_id)
            if result:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f'✗ 用户 {user_id} 处理异常：{e}')
            fail_count += 1

    logger.info('\n' + '=' * 80)
    logger.info(f'全部处理完成！')
    logger.info(f'成功：{success_count} 个用户')
    logger.info(f'失败：{fail_count} 个用户')
    logger.info('=' * 80)
