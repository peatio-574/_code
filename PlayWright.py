# -*- coding: utf-8 -*-
import sys

import os
from pathlib import Path

# 把项目根目录 D:\robot 加入Python路径
sys.path.append(str(Path(__file__).parent.parent))

from Config import get_config_value, write_config_value


import time
import random
from playwright.sync_api import sync_playwright, TimeoutError
from screeninfo import get_monitors
from Logger import logger

class Playwright(object):
    """playwright登录实例"""
    def __init__(self):
        # 初始化playwright相关对象
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.exit = False

        self.browser_type = 'chrome'  # 浏览器类型 msedge

        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0'
        self.width = get_monitors()[0].width  # 当前屏幕分辨率width
        self.height = get_monitors()[0].height  # 当前屏幕分辨率height
        self.timeout = 10 * 1000  # 超时时间

    def start_borwser(self):
        """打开浏览器"""
        self.playwright = sync_playwright().start()
        browser_args = [
            # 禁用自动化检测（核心）
            '--disable-blink-features=AutomationControlled',
            # 禁用扩展/插件
            '--disable-extensions',
            '--disable-plugins',
            # 禁用GPU/WebGL指纹
            '--disable-gpu',
            '--disable-webgl',
            '--disable-webgl-image-chromium',
            # 禁用隐私模式提示
            '--no-pings',
            # 禁用弹窗拦截（模拟真实用户）
            '--disable-popup-blocking',
            # 禁用默认浏览器检查
            '--no-default-browser-check',
            # 禁用首次运行提示
            '--no-first-run',
            # 随机窗口尺寸（避免固定值）
            '--start-maximized'
            # '--window-size={},{}'.format(
            #     self.width + random.randint(-20, 20),
            #     self.height + random.randint(-20, 20)
            # ),
            # 模拟真实语言/地区
            '--lang=zh-CN,zh',
            # 禁用日志（减少特征）
            '--log-level=3',
            '--disable-logging',
            # 禁用密码保存提示
            '--disable-save-password-bubble',
            # 禁用自动填充
            '--disable-autofill',
        ]

        # 2. 启动浏览器（隐藏自动化标识）
        self.browser = self.playwright.chromium.launch(
            channel=self.browser_type,
            headless=False,
            args=browser_args,
            # 移除Playwright默认的自动化参数
            ignore_default_args=["--enable-automation"],
            # 随机放慢操作（模拟人类速度）
            slow_mo=random.randint(100, 300),
            # 禁用自动化相关日志
            # env={"GOOGLE_CHROME_BIN": ""}
        )
        # 创建上下文
        self.context = self.browser.new_context(
            viewport=None,
            user_agent=self.user_agent)
        # 创建页面
        self.page = self.context.new_page()
        self.page.set_viewport_size({"width": self.width, "height": self.height})
        js_code = """
        () => {
            // 唯一需要的核心操作：覆盖 getter
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true, // 确保可以被重新定义（虽然通常不需要再次定义）
                enumerable: false
            });

            // 其他伪装逻辑... (plugins, chrome object 等)
        }
        """
        self.page.add_init_script(js_code)

    def close(self):
        """关闭浏览器"""
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def goto(self, url, timeout=None):
        if not self.playwright:
            self.start_borwser()
        for i in range(3):
            try:
                self.page.goto(url, timeout=self.timeout if not timeout else timeout, wait_until='domcontentloaded')
                time.sleep(1)
                return True
            except Exception as e:
                print('%s地址访问失败：%s' % (url, e))
                continue
        return False

    def click(self, location, force=False):
        try:
            if force:
                self.page.locator(location).click(force=force)
            else:
                self.page.click(location, timeout=self.timeout)
            time.sleep(random.randint(0, 1))
        except Exception as e:
            os.makedirs('d:/_code/photo', exist_ok=True)
            os.makedirs('d:/_code/photo/error', exist_ok=True)
            file = f'd:/_code/photo/error/{time.strftime("%Y%m%d%H%M%S")}_error.png'
            logger.error( f'点击失败，截图：{file}\n{e}')
            self.exit = True

    def input(self, location, text, enter=False):
        self.page.fill(location, text)
        if enter:
            self.page.press(location, 'Enter')

    def wait_for_selector(self, location, state='visible', timeout=5*1000, way='xpath'):
        try:

            location = location if way == 'xpath' else f'{way}={location}'
            self.page.wait_for_selector(location, state=state, timeout=timeout)
            return True
        except TimeoutError:
            return False

    def reload(self):
        self.page.reload()

    def clear_cookie(self):
        self.context.clear_cookies()

    def add_cookie(self, cookie, clear=False):
        if not self.playwright:
            self.start_borwser()
        if clear:
            self.clear_cookie()
        if self.context.cookies() != cookie:
            self.context.add_cookies(cookie)

    def wait_for_timeout(self, timeout=3000):
       self.page.wait_for_timeout(timeout)

    def get_count(self, location):
        try:
            return self.page.locator(location).count()
        except Exception as e:
            logger.error(f'获取元素数量失败：{e}')
            return 0

    def get_text(self, location):
        return self.page.locator(location).text_content()

    def get_attribute(self, location, key):
        return self.page.locator(location).get_attribute(key)

    def switch_to_page(self):
        time.sleep(2)
        self.page = self.context.pages[-1]
        self.page.bring_to_front()
        time.sleep(3)

    def element_screenshot(self, location, file, right=0):
        ele = self.page.locator(location)
        box = ele.bounding_box()
        clip = {
            'x': 0,
            'y': 0,
            'width': box['width'] - right,
            'height': box['height'],
        }
        ele.screenshot(path=file, clip=clip)

    def screenshot(self,file):
        self.page.screenshot(path=file)

    def login(self, url, location, key='login.xiaohognshu', way='xpath'):
        """初始登录，并进行页面cookie、接口cookie持久化
        url 登录地址
        location 判断登录成功的元素定位
        way 元素定位方式，默认xpath
        key ini配置文件对应section及option，使用.进行分割
        """
        section, option = key.split('.')
        cookie = get_config_value(section, option)
        if cookie:
            Playwright_.add_cookie(eval(cookie))
        Playwright_.goto(url)
        time.sleep(5)
        element = Playwright_.wait_for_selector(location, timeout=3 * 60 * 1000, way=way)
        if not element:
            return False

        # 页面cookie
        cookie_list = Playwright_.context.cookies()

        # api_cookie
        api_cookie = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookie_list])
        write_config_value(section, {option: str(cookie_list), f'{option}_api': api_cookie})
        return True


Playwright_ = Playwright()