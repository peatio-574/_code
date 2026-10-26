# -*- coding: utf-8 -*-
"""PatchRight 反检测浏览器实例（独立模块，不依赖 newPlayWright）

与 newPlayWright.PlayWrightClass 的用法保持一致，但内部用 patchright
（playwright 的反检测分支）启动浏览器，并自带常用的页面操作方法，
因此本文件可以单独拷贝使用，不需要 newPlayWright.py。

浏览器选择可配置：
    browser_type = 'msedge'  用系统 Edge（走 edge_path）
    browser_type = 'chrome'  用系统 Chrome（走 channel）
    其他                     用 patchright/playwright 内置 chromium

用法：
    from PatchRight import PatchRight
    pw = PatchRight()
    pw.start_browser()            # 打开浏览器并创建 page
    pw.goto('https://example.com')
    pw.login('https://...', '//span[@id="user"]', key='login.boss_cookie', file=ini)
    pw.close()
"""
import os
import random
import re
import sys
import time

if getattr(sys, 'frozen', False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.abspath(__file__))
if _base not in sys.path:
    sys.path.insert(0, _base)

from Config import get_config_value, write_config_value
from Logger import logger


from patchright.sync_api import sync_playwright as _sync_playwright
from screeninfo import get_monitors



class PatchRightClass(object):
    """patchright 反检测浏览器实例（自包含，无外部基类依赖）。"""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self.timeout = 30 * 1000          # 默认超时(ms)

        # ==================== 浏览器选择（与 PlayWrightClass 配置方式一致） ====================
        self.browser_type = 'msedge'      # 'msedge' / 'chrome' / 其他=内置 chromium
        self.edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

        # UA 末尾的 Edg/<版本> 由 resolve_user_agent 按真实浏览器版本对齐
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
        )

        # 屏幕分辨率（部分场景需要按屏幕尺寸设置窗口）
        if get_monitors is not None:
            try:
                monitor = get_monitors()[0]
                self.width, self.height = monitor.width, monitor.height
            except Exception:
                self.width, self.height = 1920, 1080
        else:
            self.width, self.height = 1920, 1080

    # ==================== 启动参数 ====================

    def build_launch_kwargs(self, headless=False):
        """按 browser_type 组装 launch 参数。"""
        kwargs = {
            'headless': headless,
            'args': [
                "--disable-blink-features=AutomationControlled",   # 去掉自动化标识
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--lang=zh-CN,zh",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            'ignore_default_args': ["--enable-automation"],
        }
        if self.browser_type == 'chrome':
            kwargs['channel'] = self.browser_type
        elif self.browser_type == 'msedge':
            kwargs['executable_path'] = self.edge_path
        # 其他值：不传 channel/executable_path，使用内置 chromium
        return kwargs

    def resolve_user_agent(self):
        """按实际浏览器校正 UA。

        UA 仍由 self.user_agent 配置，这里只做两件必要的对齐：
          1. browser_type 不是 Edge 时去掉 Edg/ 段（否则 Chromium 自称 Edge）
          2. UA 里的版本号换成真实浏览器版本，避免「浏览器 156 却声称 143」
        """
        ua = (self.user_agent or '').strip()
        if not ua:
            return ua

        if self.browser_type != 'msedge' and 'Edg/' in ua:
            ua = re.sub(r'\s*Edg/[\d.]+', '', ua).strip()
            logger.info('browser_type=%s，UA 已去掉 Edg 标识' % self.browser_type)

        version = ''
        try:
            version = (self.browser.version or '').strip()
        except Exception:
            pass
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', version):
            ua = re.sub(r'Chrome/[\d.]+', 'Chrome/%s' % version, ua)
            ua = re.sub(r'Edg/[\d.]+', 'Edg/%s' % version, ua)
        return ua

    # ==================== 启动 / 关闭 ====================

    def start_browser(self, proxy=None, headless=False):
        """打开浏览器并创建 context / page。"""
        if self.playwright:
            return

        self.playwright = _sync_playwright().start()
        kwargs = self.build_launch_kwargs(headless=headless)
        logger.info('启动浏览器：browser_type=%s%s'
                    % (self.browser_type,
                       '  path=%s' % self.edge_path if 'executable_path' in kwargs else ''))

        try:
            self.browser = self.playwright.chromium.launch(**kwargs)
        except Exception as e:
            # Edge 路径不对时给出明确提示，而不是只抛 playwright 的原始报错
            logger.error('启动浏览器失败（browser_type=%s）：%s' % (self.browser_type, e))
            self.playwright.stop()
            self.playwright = None
            raise

        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=self.resolve_user_agent(),
            accept_downloads=True,
            proxy=proxy,
        )
        self.page = self.context.new_page()

        # 反检测注入脚本
        self.page.add_init_script(r"""
            () => {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true,
                    enumerable: false,
                });
                if (!window.chrome) { window.chrome = { runtime: {} }; }
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
            }
        """)

    # 兼容基类的拼写错误调用方
    def start_borwser(self, proxy=None):
        self.start_browser(proxy)

    def close(self):
        """关闭浏览器"""
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        self.page = self.context = self.browser = self.playwright = None

    # ==================== 页面操作 ====================

    def goto(self, url, timeout=None, proxy=None):
        """打开地址；way 参数保留以兼容基类调用（本类只需 'new'）。"""
        if not self.playwright:
            self.start_browser(proxy)
        for _ in range(3):
            try:
                self.page.goto(url,
                               timeout=self.timeout if not timeout else timeout,
                               wait_until='domcontentloaded')
                time.sleep(5)
                return True
            except Exception as e:
                logger.info('%s地址访问失败：%s' % (url, e))
                continue
        return False

    def new_goto(self, url, timeout=None, close=True):
        """新开页面访问（关闭上一个页面）。"""
        if not self.playwright:
            self.start_browser()
        if self.page and close:
            try:
                self.page.close()
            except Exception as e:
                logger.error('关闭旧页面失败：%s' % e)
        self.page = self.context.new_page()
        try:
            self.page.goto(url,
                           timeout=self.timeout if not timeout else timeout,
                           wait_until='domcontentloaded')
            return True
        except Exception as e:
            logger.info('%s地址访问失败：%s' % (url, e))
            return False

    def reload(self):
        self.page.reload()

    def wait_for_timeout(self, timeout=3000):
        self.page.wait_for_timeout(timeout)

    def wait_for_selector(self, location, state='visible', timeout=5 * 1000, way='xpath'):
        try:
            selector = location if way != 'xpath' else location
            self.page.wait_for_selector(selector, state=state, timeout=timeout)
            return True
        except Exception as e:
            logger.error('等待元素失败：%s' % e)
            return False

    def click(self, location, force=False, no_wait=False):
        try:
            if force:
                self.page.locator(location).click(force=True)
            else:
                self.page.locator(location).click(no_wait_after=no_wait,
                                                  timeout=self.timeout)
            time.sleep(random.randint(0, 1))
            return True
        except Exception as e:
            logger.error('点击失败：%s' % e)
            return False

    def input(self, location, text, enter=False):
        self.page.locator(location).clear()
        self.page.fill(location, text)
        if enter:
            self.page.press(location, 'Enter')

    def get_count(self, location):
        try:
            return self.page.locator(location).count()
        except Exception as e:
            logger.error('获取元素数量失败：%s' % e)
            return 0

    def get_text(self, location):
        return self.page.locator(location).inner_text()

    def get_attribute(self, location, key):
        return self.page.locator(location).get_attribute(key)

    def screenshot(self, file):
        self.page.screenshot(path=file)

    def mouse_wheel(self, delta_y, delta_x=0):
        self.page.mouse.wheel(delta_x, delta_y)

    # ==================== Cookie ====================

    def clear_cookie(self):
        self.context.clear_cookies()

    def add_cookie(self, cookie, clear=False):
        if not self.playwright:
            self.start_browser()
        if clear:
            self.clear_cookie()
        if str(self.context.cookies()) != str(cookie):
            self.context.add_cookies(cookie)

    # ==================== 登录（Cookie 持久化到 ini） ====================

    def login(self, url, location, key='login.order_cookie', way='xpath', extra=None, file=None):
        """打开登录页，等待登录成功，并把 cookie 写回 ini。

        url      登录地址
        location 判定登录成功的元素（xpath）
        key      ini 的 section.option，用 . 分隔
        file     ini 路径，None 则用 Config 默认路径
        """
        try:
            section, option = key.split('.')
            cookie = get_config_value(section, option, file)
            if cookie:
                try:
                    self.add_cookie(eval(cookie))
                except Exception as e:
                    logger.warning('注入历史 cookie 失败：%s' % e)

            self.goto(url)
            time.sleep(5)
            if self.get_count(location) == 0:
                logger.info('请登录......')
            element = self.wait_for_selector(location, timeout=3 * 60 * 1000, way=way)
            if not element:
                return False

            if extra and self.get_count(extra):
                self.click(extra)
                time.sleep(3)

            cookie_list = self.context.cookies()
            api_cookie = '; '.join('%s=%s' % (c['name'], c['value']) for c in cookie_list)
            write_config_value(section,
                               {option: str(cookie_list), '%s_api' % option: api_cookie},
                               file)
            logger.info('登录成功')
            return True
        except Exception as e:
            logger.error('登录异常：%s' % e)
            return False
