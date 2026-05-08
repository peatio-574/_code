# coding='utf-8'
"""
    @作者：彭帅
    @邮箱：acheng6@126.com
    @时间：2026/5/8 23:46
"""

from PlayWright import Playwright_
import time


def get_info(url):
    Playwright_.goto(url)
    time.sleep(3)
    video_location = '//div[@class="cg-video-wrapper "]'
    video_count = Playwright_.get_count(video_location)
    video = 1 if video_count != 0 else video_count
    text_location = '//div[@class="text  en"]/p'
    content = str()
    text_count = Playwright_.get_count(text_location)
    for text_ in range(1, text_count+1):
        text = Playwright_.get_text(f'({text_location})[{text_}]')
        content += text + '\n'
    content = content.strip('\n')
    return content, str(video)

def main():
    pass


