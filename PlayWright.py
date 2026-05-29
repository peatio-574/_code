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

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

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
            # '--start-maximized',
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
            executable_path=EDGE_PATH,
            # channel=self.browser_type,
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
            user_agent=self.user_agent,
            accept_downloads=True)
        # 创建页面
        self.page = self.context.new_page()
        # self.page.set_viewport_size({"width": self.width, "height": self.height})
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

    def new_goto(self, url, timeout=None):
        """新开一个页面访问，并关闭上一个页面（若有）"""
        if not self.playwright:
            self.start_borwser()

        # 关闭上一个页面（如果存在）
        if self.page:
            try:
                self.page.close()
            except Exception as e:
                logger.error(f'关闭旧页面失败：{e}')

        # 创建新页面
        self.page = self.context.new_page()

        # 添加初始化脚本（与start_borwser中保持一致）
        self.page.add_init_script("""
            // 禁用 webdriver 检测
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            // 强制语言为英文
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            // 设置文档语言
            document.documentElement.lang = 'en-US';
            // 删除定位 API
            delete navigator.geolocation;
        """)

        # 访问新URL
        for i in range(3):
            try:
                self.page.goto(url, timeout=self.timeout if not timeout else timeout, wait_until='domcontentloaded')
                time.sleep(1)
                return True
            except Exception as e:
                logger.error(f'{url}地址访问失败：{e}')
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
        except Exception as e:
            logger.error(f'等待元素失败：{e}')
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
        old_page = self.page
        if len(self.context.pages) > 1:
            self.page = self.context.pages[-1]
            self.page.bring_to_front()
            old_page.close()
            time.sleep(5)

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

    def login(self, url, location, key='login.xiaohognshu', way='xpath', storage=False, extra=None, file=None):
        """初始登录，并进行页面cookie、接口cookie持久化
        url 登录地址
        location 判断登录成功的元素定位
        way 元素定位方式，默认xpath
        key ini配置文件对应section及option，使用.进行分割
        """
        section, option = key.split('.')
        cookie = get_config_value(section, option, file)
        if cookie:
            self.add_cookie(eval(cookie))

        self.goto(url)
        if storage:
            storage = get_config_value(section, 'storage', file)
            if storage:
                self.add_storage(key=f'{section}.storage')
        time.sleep(5)
        count = self.get_count(location)
        if count == 0:
            logger.info('请登录......')
        element = self.wait_for_selector(location, timeout=3 * 60 * 1000, way=way)
        if not element:
            return False

        if extra:
            if self.get_count(extra):
                self.click(extra)
                time.sleep(3)

        # 页面cookie
        cookie_list = self.context.cookies()

        # api_cookie
        api_cookie = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookie_list])
        write_config_value(section, {option: str(cookie_list), f'{option}_api': api_cookie}, file)

        if storage:
            self.save_sessionstorage(key=f'{section}.storage')

        return True

    def save_sessionstorage(self, key='login.storage', file=None):
        section, option = key.split('.')
        data = self.page.evaluate("""() => {
            let data = {};
            for (let i = 0; i < localStorage.length; i++) {
                let key = localStorage.key(i);
                data[key] = localStorage.getItem(key);
            }
            return data;
        }""")
        write_config_value(section, {option: data}, file)

    def add_storage(self, key='login.storage', file=None):
        section, option = key.split('.')
        data = get_config_value(section, option, file)
        self.page.evaluate("""(storage) => {
                Object.entries(storage).forEach(([k, v]) => {
                    localStorage.setItem(k, v);
                });
            }""", eval(data))

    def mouse_wheel(self, delta_y, delta_x=0):
        """鼠标滚轮滑动
        delta_y: 垂直滑动距离，正数向下滚动，负数向上滚动
        delta_x: 水平滑动距离（可选），正数向右，负数向左
        """
        try:
            self.page.mouse.wheel(delta_x, delta_y)
            time.sleep(random.uniform(0.5, 1.0))
            return True
        except Exception as e:
            logger.error(f'鼠标滑动失败：{e}')
            return False



Playwright_ = Playwright()