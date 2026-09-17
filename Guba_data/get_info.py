# coding='utf-8'
import sys
import time

import re
import os
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from Logger import logger
import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from bs4 import BeautifulSoup
import json


HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
}

# 每一行帖子：<tr class="listitem"> 内依次是 read / reply / title / author / update
# re.S 让 . 能跨行匹配
ITEM_RE = re.compile(
    r'<tr class="listitem">.*?'
    r'<div class="read">(\d+)</div>.*?'                                # 1 阅读量
    r'<div class="reply">(\d+)</div>.*?'                               # 2 评论量
    r'<div class="title"><a [^>]*href="([^"]+)"[^>]*>[^<]*</a></div>.*?'   # 3 帖子链接
    r'<div class="author"><a [^>]*>([^<]*)</a></div>.*?'               # 4 作者
    r'<div class="update">([^<]*)</div>.*?'                            # 5 发帖时间
    r'</tr>',
    re.S,
)



def set_column_style(data_file):
    """设置表头格式"""
    XLSX_HEADERS = [
        '链接', '阅读量', '评论量', '作者', '正文', '发帖时间', '是否转载', '是否视频', '是否图片'
    ]
    wb = load_workbook(filename=data_file) if os.path.exists(data_file) else Workbook()
    ws = wb.active
    ws.title = "股吧数据"

    ws.freeze_panes = 'A2'
    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")

    THIN_BORDER = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    for col, header in enumerate(XLSX_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = THIN_BORDER
    wb.save(data_file)
    return wb, ws


def get_page_info(page_id):
    """根据页码获取列表页数据：链接 / 阅读量 / 评论量 / 作者 / 发帖时间"""
    page_str = '' if page_id == 1 else f'_{page_id}'
    url = f'https://guba.eastmoney.com/list,zssh000001,f{page_str}.html'

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.encoding = 'utf-8'
        text = response.text

        soup = BeautifulSoup(text, 'lxml')
        rows = []
        for tr in soup.select('tr.listitem'):
            title_a = tr.select_one('div.title a')
            if not title_a:
                continue
            link = title_a.get('href')
            if not link:
                continue
            link = 'https://guba.eastmoney.com' + link if not link.startswith('//') else 'https:' + link

            read_num = tr.select_one('div.read').get_text(strip=True) if tr.select_one('div.read') else ''
            replay_num = tr.select_one('div.reply').get_text(strip=True) if tr.select_one('div.reply') else ''
            author = tr.select_one('div.author a').get_text(strip=True) if tr.select_one('div.author a') else ''
            if not title_a:  # 跳过不规范的行
                continue
            row = [link, read_num, replay_num, author]
            rows.append(row)
        logger.info(f'第{page_id}页解析到 {len(rows)} 条')
        return rows
    except Exception as e:
        logger.error(f'第{page_id}页链接及基本信息爬取异常：{e}')
        return []


def save_base_info(file):
    """获取指定页面范围的基本信息"""
    wb, ws = set_column_style(file)
    # 已存在link
    exists_link = [c.value for c in ws['A'][1:]]

    start_page = input('请输入开始页码：')
    end_page = input('请输入结束页码：')
    for page_id in range(int(start_page), int(end_page) + 1):
        page_info = get_page_info(page_id)
        if not page_info:
            continue
        for row in page_info:
            if row[0] in exists_link:
                logger.info(f'{row[0]}数据已存在')
                continue  # 去重
            ws.append(row)
        wb.save(file)


def html_get_json(url, html, var_name='post_article'):
    """取页面里 var <var_name>={...} 的值并解析为 dict"""
    try:
        prefix = f'var {var_name}='
        i = html.find(prefix) + len(prefix)

        depth = 0
        in_str = False
        esc = False
        for k in range(i, len(html)):
            ch = html[k]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(html[i:k + 1])
        return {}
    except Exception as e:
        logger.error(f'【{url}】数据解析异常：{e}')
        return {}


def get_guba_info(url, text):
    content_json = html_get_json(url, text, var_name='post_article')
    try:
        content_html = content_json.get('post_content') or ''
        content = BeautifulSoup(content_html, 'html.parser').get_text(separator='\n', strip=True)

        publish_time = content_json.get('post_publish_time', '')

        has_pic = bool(
            content_json.get('post_has_pic')
            or content_json.get('post_pic_url')
            or '<img' in content_html.lower()
        )
        has_pic = '是' if has_pic else '否'

        has_video = bool(
            content_json.get('post_video_url')
            or '<video' in content_html.lower()
            or '<iframe' in content_html.lower()
        )
        has_video = '是' if has_video else '否'

        is_repost = bool(
            (content_json.get('source_post_id') or 0)
            or content_json.get('source_post_title')
            or content_json.get('source_post_content')
        )
        is_repost = '是' if is_repost else '否'

        return [content, publish_time, is_repost, has_video, has_pic]
    except Exception as e:
        logger.error(f'【{url}】数据解析后获取详情异常：{e}')
        return []


def get_caifuhao_info(url, text):
    try:
        result = re.findall('articleTxt = "(.*)"', text)[0]
        content_html = result.replace('\\"', '"').replace('\\/', '/')     # 还原成真正的 HTML
        content = BeautifulSoup(content_html, 'html.parser').get_text(separator='\n', strip=True)

        is_repost = '否'

        has_video = '是' if re.search(r'<img', content_html, re.I) else '否'

        has_pic = '是' if re.search(r'<video', content_html, re.I) else '否'

        publish_time_str = re.findall(r'"ArtCode":"(\d*)",', text)[0][:14]
        publish_time = time.strftime('%Y-%m-%d %H:%M:%S', time.strptime(str(publish_time_str)[:14], '%Y%m%d%H%M%S'))

        return [content, publish_time, is_repost, has_video, has_pic]
    except Exception as e:
        logger.error(f'【{url}】获取详情异常：{e}')
        return []


def get_detail(url):
    """根据链接，获取帖子详情"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.encoding = 'utf-8'
        text = response.text

        # 股吧
        if url.startswith('https://guba.eastmoney.com'):
            info = get_guba_info(url, text)
        # 财富号
        else:
            info = get_caifuhao_info(url, text)
        return info
    except Exception as e:
        logger.error(f'获取【{url}】帖子内容异常：{e}')
        return []


def get_all_contents(file):
    """获取所有帖子详情，并保存"""
    wb, ws = set_column_style(file)
    # 获取已存在的正文
    exists_content = [c.value for c in ws['E'][1:]]
    # 保存标识
    flag = 0
    # 行id从第二行开始
    for row_id, content in enumerate(exists_content, start=2):
        if content:
            continue
        # 根据链接获取详情
        url = ws['A'][row_id-1].value
        logger.info(f'开始获取第{row_id-1}条：【{url}】详情')
        detail = get_detail(url)
        # 保存数据，从第二列开始
        column_id = 5
        for value in detail:
            ws.cell(row=row_id, column=column_id).value = value
            column_id += 1
        flag += 1
        if flag % 5 == 0:
            wb.save(file)
            exit()
    wb.save(file)


if __name__ == '__main__':
    while True:
        file = os.path.join(os.path.dirname(__file__), '股吧数据.xlsx')
        step= input('请输入操作步骤（1.爬取帖子链接，2.爬取帖子内容）：')
        if step == '1':
            save_base_info(file)
        else:
            get_all_contents(file)

