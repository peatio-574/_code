# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger
import time
import os
import requests
from ReadFile import ReadData

picture_dir = os.path.join(os.path.dirname(__file__), 'pictures')
os.makedirs(picture_dir, exist_ok=True)

proxy = {
    "server": 'http://127.0.0.1:7892',
    "username": '2953515027',
    "password": '121920.pS',
}

headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
}

def save_picture(picture_url, filename):
    picture_file = os.path.join(picture_dir, filename)
    try:
        with open(picture_file, 'wb') as f:
            f.write(requests.get(picture_url, headers=headers).content)
        return filename
    except Exception as e:
        logger.error(f'[{picture_url}] picture download failed: {e}')
        return picture_url


def get_main_info(url, product_id):
    Playwright_.goto(url, proxy=proxy)

    verify_ele = '//img[@id="captcha-verify-image"]'
    if Playwright_.get_count(verify_ele) == 1:
        exit('captcha required, please verify manually')

    Playwright_.wait_for_selector('//div[text()="登录"]', timeout=60* 1000)

    product_name = Playwright_.get_text('//h1/span')

    category_ele = '//ol/li/a/span'
    category_count = Playwright_.get_count(category_ele)
    category_list = [Playwright_.get_text(f'({category_ele})[{i}]') for i in range(1, category_count+1)]
    first_category = category_list[0]
    category = '>'.join(category_list)

    main_picture_ele = '//div[contains(@class, "relative overflow-visible")]/div/img'
    main_picture_count = Playwright_.get_count(main_picture_ele)
    main_picture_list = [Playwright_.get_attribute(f'({main_picture_ele})[{i}]', 'src') for i in range(1, main_picture_count+1)]
    real_main_pictures = []
    for idx, main_picture in enumerate(main_picture_list, start=1):
        real_main_picture= save_picture(main_picture, f'{product_id}_main_{idx}.webp')
        real_main_pictures.append(real_main_picture)

    first_main_picture = real_main_pictures[0]
    real_main_pictures = '\n'.join(real_main_pictures)

    more_ele = '//div[text()="View more"]'
    if Playwright_.get_count(more_ele) == 1:
        Playwright_.click(more_ele)
        time.sleep(1)
    if Playwright_.get_count(more_ele) == 1:
        Playwright_.click(more_ele)
        time.sleep(1)

    detail_ele = '//tbody/tr'
    detail_count = Playwright_.get_count(detail_ele)
    detail = '\n'.join([f'{Playwright_.get_text(f"({detail_ele})[{i}]/td[1]/span")}: {Playwright_.get_text(f"({detail_ele})[{i}]/td[2]/span")}' for i in range(1, detail_count+1)])

    describe_ele = '//div[contains(@class, "whitespace-normal")]'
    describe_count = Playwright_.get_count(describe_ele)
    describe = '\n'.join([Playwright_.get_text(f'({describe_ele})[{i}]') for i in range(1, describe_count+1)])
    return {
        'product_id': product_id,
        'product_name': product_name,
        'category': category,
        'first_category': first_category,
        'real_main_pictures': real_main_pictures,
        'first_main_picture': first_main_picture,
        'detail': detail,
        'describe': describe,
    }

def get_sku_info(product_id):
    sku_ele = '//div[contains(@class, "flex flex-row overflow-x-auto")]/div'
    sku_count = Playwright_.get_count(sku_ele)
    price_ele = '//span[@class="flex flex-row items-baseline"]/span/span'
    sku_info = []
    for i in range(1, sku_count+1):
        current_ele = f'({sku_ele})[{i}]'
        Playwright_.click(current_ele)
        time.sleep(2)

        sku_picture = Playwright_.get_attribute(f'{current_ele}/img', 'src')
        real_sku_picture = save_picture(sku_picture, f'{product_id}_sku_{i}.webp')

        sku_name = Playwright_.get_text(f'{current_ele}/span')

        price_count = Playwright_.get_count(price_ele)
        sku_price = [Playwright_.get_text(f'({price_ele})[{j}]') for j in range(1, price_count+1)]
        sku_price = ''.join(sku_price)

        sku_info.append({
            'sku_name': sku_name,
            'sku_price': sku_price,
            'sku_picture': real_sku_picture,
        })
    return sku_info

def resolve_short_link(short_url):
    """
    返回产品id
    """
    import re
    from urllib.parse import urljoin

    session = requests.Session()
    session.headers.update({
        'User-Agent': headers['user-agent'],
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    # proxy_url = proxy['server']
    # if proxy.get('username'):
    proxy_url = proxy['server'].replace('://', f'://{proxy["username"]}:{proxy["password"]}@')
    session.proxies = {'http': proxy_url, 'https': proxy_url}

    try:
        final_url = short_url
        for _ in range(10):
            resp = session.get(final_url, allow_redirects=False, timeout=15)
            if resp.status_code in {301, 302, 303, 307, 308}:
                final_url = urljoin(final_url, resp.headers.get('Location', ''))
            else:
                final_url = resp.url
                break

        # product PDP: /shop/pdp/.../id  or  H5: /view/product/{id}
        m = re.search(r'/pdp/(?:.+/)?(\d+)', final_url)
        if not m:
            m = re.search(r'/view/product/(\d+)', final_url)
        if m:
            logger.info(f'[{short_url}] product_id：{m.group(1)}')
            return m.group(1)

        # video link: /@user/video/{id}
        m = re.search(r'/@([^/]+)/video/(\d+)', final_url)
        if m:
            logger.warning(f'[video] not a product link! @{m.group(1)} video_id={m.group(2)}')
            return None

        logger.warning(f'unknown link type: {final_url}')
        return None

    except Exception as e:
        logger.error(f'resolve failed: {short_url} -> {e}')
        return None


def run():
    data_file = os.path.join(os.path.dirname(__file__), '链接.xlsx')
    links = ReadData.read_xlsx_col(data_file)['链接']
    for link in links:
        logger.info(f'开始处理链接：{link}')
        product_id = resolve_short_link(link)
        if product_id is None:
            continue
        product_url = f'https://shop.tiktok.com/my/pdp/x/{product_id}'
        main_info = get_main_info(product_url, product_id)
        main_info['source_url'] = link
        main_info['product_url'] = product_url

        logger.info(main_info)
        sku_info = get_sku_info(product_url)
        logger.info(sku_info)
        time.sleep(10000)





if __name__ == '__main__':
    run()