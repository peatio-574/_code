
import requests, os, time
from PlayWright import Playwright_, logger

url = 'https://tgb.cn/topic/lookUserTopic?topicID=1424851&lookUserID=308803&pageNo=2'

content_file = os.path.join(os.path.dirname(__file__), 'content.txt')
if not os.path.exists(content_file):
    with open(content_file, 'w', encoding='utf-8') as f:
        pass

def write_content(content):
    with open(content_file, 'a', encoding='utf-8') as f:
        f.write(content)
        f.write('\n')
        f.close()

def get_info():
    row_ele = '//div[contains(@class,"comment-data user")]'
    row_count = Playwright_.get_count(row_ele)
    for row in range(1, row_count + 1):
        content_ele = f'({row_ele})[{row}]//div[@class="comment-data-text"]'
        content = Playwright_.get_text(content_ele)
        write_content(content)
        img_ele = f'({row_ele})[{row}]//img[@data-type="contentImage"]'
        img_count = Playwright_.get_count(img_ele)
        for img in range(1, img_count + 1):
            img_url = Playwright_.get_attribute(f'({img_ele})[{img}]', 'src')
            img_name = img_url.split('/')[-4:]
            img_name = '_'.join(img_name)
            with open(img_name, 'wb') as f:
                f.write(requests.get(img_url).content)
                logger.info(f'保存图片成功：{img_name}')

def main():
    url = 'https://tgb.cn/topic/lookUserTopic?topicID=1424851&lookUserID=308803'
    for i in range(1, 51):
        url = url if i == 1 else f'{url}&pageNo={i}'
        Playwright_.goto(url)
        time.sleep(30)
        get_info()
