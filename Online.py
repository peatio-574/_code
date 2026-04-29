# -*- coding: utf-8 -*-

from Config import get_config_value, write_config_value
from PlayWright import Playwright_
import time

def login():
    cookie = get_config_value('new', 'web_cookie')
    if cookie:
        Playwright_.add_cookie(eval(cookie))
    url = 'https://wares-jdm.jd.com/'
    Playwright_.goto(url)
    time.sleep(5)
    element = Playwright_.wait_for_selector('找客服', timeout=3 * 60 * 1000, way='text')
    if not element:
        return False
    cookie_list = Playwright_.context.cookies()
    write_config_value('new', {'web_cookie': str(cookie_list)})
    return True


def main():
    login()
    Playwright_.goto('https://wares-jdm.jd.com/popPublish/?categoryId=46603&newFlow=1&newSource=true&locType=0&uuid=d88be993-8a6b-4493-a12d-1164909d6251&cateList=1319%2C1523%2C31762%2C46603&source=1&logUuid=18c48f721df4422fb4e75802deec4f05&vId=267869916&publishType=1&publishPageType=1')
    # print('点击添加新商品')
    # Playwright_.goto('https://wares-jdm.jd.com/ware/wareList?activeTab=OnsaleWare&businessModel=0')
    # Playwright_.click('//span[text()=" 添加新商品"]')
    # print('切换到最新窗口')
    # Playwright_.switch_to_page()
    # print('选择类目')
    # catalogue = '儿童驼奶粉'
    # Playwright_.input('//input[@placeholder="您当前在全部类目下搜索"]', catalogue)
    # print('选择第一个')
    # Playwright_.click('(//ul/li)[1]')
    # # 选择第一项
    # print('点击确认，下一步')
    # Playwright_.click('//span[text()=" 确认，下一步 "]')
    # print('点击确认离开')
    # try:
    #     Playwright_.page.get_by_text("离开").click()
    # except:
    #     pass
    time.sleep(5)
    print('选择品牌')
    location = '//input[@placeholder="请搜索或选择"]'
    locator = Playwright_.page.locator(location)
    Playwright_.page.evaluate('''(locator) => {
        locator.removeAttribute('readonly');
        locator.focus();
    }''', locator.element_handle())

    kind = '儿童驼奶粉'
    if kind:
        Playwright_.input(location, kind)
        time.sleep(1)
        print('选择对应品牌')
        Playwright_.page.keyboard.press('ArrowDown')
        # Playwright_.page.keyboard.press('ArrowDown')
        Playwright_.page.keyboard.press('Enter')

    print('输入标题')
    title = '测试标题'
    Playwright_.input('//input[@placeholder="请输入商品标题"]', title)
    # time.sleep(1000)

    # print('点击上传主图')
    # Playwright_.click('(//ul[@class="shop-img-upload__upload"])[1]')
    # print('点击本地上传')
    # file_inputs = Playwright_.page.locator('input[type="file"]')
    # # 2. 获取第一个 file input 并上传
    # file_input = file_inputs.first
    # # Playwright_.page.evaluate('''(input) => {
    # #     input.removeAttribute('webkitdirectory');
    # #     input.removeAttribute('directory');
    # # }''', file_input.element_handle())
    #
    # file_input.set_input_files(r'D:\tmp\新接口\001-10217915450417\main')


    print('点击图文编辑')
    Playwright_.click('//span[text()="图文编辑"]')
    time.sleep(1000)

if __name__ == '__main__':

    main()