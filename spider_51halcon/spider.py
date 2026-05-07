# -*- coding: utf-8 -*-
import sys
from pathlib import Path
# 将项目根目录添加到Python路径
sys.path.append(str(Path(__file__).parent.parent))

import time
from PlayWright import Playwright_, logger
import os
import base64


def save_complete_page(title, dirname):
    # 创建保存目录
    path = os.path.join(dirname, title)
    if os.path.exists(path):
        logger.error(f'{title}已爬取完成')
        return True
    os.makedirs(path, exist_ok=True)
    html_path = os.path.join(path, 'index.html')
    try:
        html = Playwright_.page.content()
        # 内容图片处理
        content_img_location = '//ignore_js_op/img[@file]'
        content_img_count = Playwright_.get_count(content_img_location)
        for pic_id in range(1, content_img_count + 1):
            img = Playwright_.get_attribute(f'({content_img_location})[{pic_id}]', 'file')
            new_img = save_img(img, title, type='内容', dirname=dirname, full=False)
            if new_img:
                html = html.replace(img, new_img)

        # 评论图片处理
        comment_img_location = '//div[@class="a_p"]//img[@src]'
        comment_img_count = Playwright_.get_count(comment_img_location)
        for pic_id_ in range(1, comment_img_count + 1):
            img = Playwright_.get_attribute(f'({comment_img_location})[{pic_id_}]', 'src')
            new_img = save_img(img, title, type='评论', dirname=dirname, full=True)
            if new_img:
                html = html.replace(img, new_img)
        # 保存html
        logger.info(f"保存html：{html_path}")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"✅ {title}保存完成！路径：{os.path.abspath(path)}")
        return True
    except Exception as e:
        logger.error(f"❌ {title}保存失败！错误信息：{e}")
        return False

def save_img(src, title, type='内容', dirname='d:/tmp/51/视觉硬件技术-硬件资料', full=False):
    url = 'https://www.51halcon.com/' + src if not full else src
    file = os.path.join(dirname, title, url.split('/')[-1])
    for i in range(3):
        try:
            img_base64 = Playwright_.page.evaluate("""(src) => {
                    return new Promise((resolve, reject) => {
                        const img = new Image();
                        img.crossOrigin = 'Anonymous';
                        img.onload = () => {
                            const canvas = document.createElement('canvas');
                            canvas.width = img.naturalWidth;
                            canvas.height = img.naturalHeight;
                            const ctx = canvas.getContext('2d');
                            ctx.drawImage(img, 0, 0);
                            resolve(canvas.toDataURL('image/png').split(',')[1]);
                        };
                        img.src = src;
                    });
                }""", url)
            # 保存到本地
            with open(file, "wb") as f:
                f.write(base64.b64decode(img_base64))
                logger.info(f"{type}图片{url}保存成功！")
                return file
        except Exception as e:
            logger.error(f"{type}图片{url}保存失败！失败原因：{e}")
            time.sleep(0.5)
    logger.error(f"❌ {type}图片{url}保存失败！")
    return  ''

def run(page_url, dirname, page=1, article_id=1):
    # page_url = 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=11'
    # dirname = 'd:/tmp/51/视觉硬件技术-硬件资料'
    Playwright_.goto(page_url)
    time.sleep(5)
    # page = 50
    # article_id = 979

    while True:
        # 每页帖子数量
        page_location = '//tbody[contains(@id, "normal")]'
        page_count = Playwright_.get_count(page_location)
        logger.info(f'第{page}页，帖子数量为{page_count}')
        for id_ in range(1, page_count + 1):
            article_location = f'({page_location})[{id_}]//a[@class="s xstt"]'

            # 标题
            title = Playwright_.get_text(article_location)
            invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '.', '\n']
            for c in invalid_chars:
                title = title.replace(c, '-')
            article_id += 1
            title = f'{article_id}_{title}'


            logger.info(f'\n开始爬取帖子：{title}')
            href = Playwright_.get_attribute(article_location, 'href')
            Playwright_.goto(href)
            # 保存数据
            save_complete_page(title, dirname)
            # 返回列表
            Playwright_.goto(page_url)
        # 点击下一页
        page += 1
        time.sleep(5)
        for i in range(5):
            next_page_location = f'(//div[@class="pg"])[1]/a[text()="{page}"]'
            next_page_count = Playwright_.get_count(next_page_location)
            if next_page_count:
                Playwright_.click(next_page_location)
            else:
                logger.error(f'第{page}页不存在')
                exit()
            success_click_location = f'(//div[@class="pg"])[1]/strong[text()="{page}"]'
            if Playwright_.get_count(success_click_location):
                page_url = Playwright_.page.url
                logger.info(f'已进入第{page}页')
                break
            time.sleep(1)

def check():
    dir1 = r'D:\tmp\51\视觉硬件技术-硬件资料'

    for i in os.listdir(dir1):
        files = os.listdir(os.path.join(dir1, i))
        if 'index.html' not in files:
            print(f'{i}爬取异常')
    info = [i.split('_', 1)[1] for i in os.listdir(dir1)]
    for i in info:
        count = info.count(i)
        if count > 1:
            print(f'{i}重复')


    pass


if __name__ == '__main__':
    all_info = {
        # '视觉硬件技术-视觉广场': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=13',
        '视觉软件技术-Halcon软件': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=21&page=50',
        '视觉软件技术-OpenCV软件': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=22',
        '视觉软件技术-C++_C#_Python软件': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=23',
        '视觉技能提升-2D_3D视觉': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=31',
        '视觉技能提升-AI_深度_大模型': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=32',
        '视觉技能提升-编程语言学习': 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=33',
    }
    for dirname, page_url in all_info.items():
        dirname = f'd:/tmp/51/{dirname}'
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        if page_url == 'https://www.51halcon.com/forum.php?mod=forumdisplay&fid=21&page=50':
            run(page_url, dirname, page=50, article_id=979)
        else:
            run(page_url, dirname)


