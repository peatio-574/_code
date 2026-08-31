# -*- coding: utf-8 -*-
import sys

import os

if getattr(sys, 'frozen', False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _base)

from Config import get_config_value, write_config_value
import time
import random
from playwright.sync_api import sync_playwright
from screeninfo import get_monitors
from Logger import logger
import requests

class PlayWrightClass(object):
    """playwright登录实例"""
    def __init__(self):
        # 初始化playwright相关对象
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.exit = False

        self.browser_type = 'chrome'  # 浏览器类型 msedge
        self.edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0'
        self.width = get_monitors()[0].width  # 当前屏幕分辨率width
        self.height = get_monitors()[0].height  # 当前屏幕分辨率height
        self.timeout = 30 * 1000  # 超时时间

    def start_exists_browser(self, debug_port=9222):
        """连接已打开的本地Edge浏览器（通过CDP）"""
        import subprocess

        self.playwright = sync_playwright().start()

        # 检测Edge是否已开启调试端口
        edge_running = self._is_edge_running()
        need_restart = False

        if edge_running:
            # 检查调试端口是否可达
            import urllib.request
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/version", timeout=3)
                logger.info(f"Edge调试端口 {debug_port} 已就绪")
            except Exception as e:
                logger.info(f"Edge正在运行但未开启调试端口，正在重启...{e}")
                self._kill_edge()
                need_restart = True
        else:
            need_restart = True

        if need_restart:
            # 用调试端口启动Edge（复用原有用户数据目录）
            user_data_dir = self._get_user_data_dir()
            cmd = [
                self.edge_path,
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--start-maximized",
            ]
            logger.info(f"启动Edge: {cmd}")
            subprocess.Popen(cmd)
            time.sleep(8)

        # 通过CDP连接
        cdp_url = f"http://127.0.0.1:{debug_port}"
        logger.info(f"连接Edge: {cdp_url}")
        self.browser = self.playwright.chromium.connect_over_cdp(cdp_url)

        # 复用已有上下文
        self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()

        # 复用已有页面，没有则新建
        if self.context.pages:
            self.page = self.context.pages[0]
            # 关闭多余页面
            for p in self.context.pages[1:]:
                p.close()
        else:
            self.page = self.context.new_page()

        # 注入反检测脚本
        self.page.add_init_script("""
            () => {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true,
                    enumerable: false
                });
            }
        """)
        logger.info("Edge连接成功")

    def _is_edge_running(self):
        """检查Edge是否正在运行"""
        import subprocess
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq msedge.exe'],
            capture_output=True, text=True, creationflags=0x08000000
        )
        return 'msedge.exe' in result.stdout

    def _kill_edge(self):
        """关闭所有Edge进程"""
        import subprocess
        subprocess.run(
            ['taskkill', '/f', '/im', 'msedge.exe'],
            capture_output=True, creationflags=0x08000000
        )
        time.sleep(3)

    def _get_user_data_dir(self):
        """获取Edge用户数据目录（保留书签、密码等）"""
        return os.path.join(
            os.path.expanduser("~"),
            "AppData", "Local", "Microsoft", "Edge", "UserData"
        )


    def start_borwser(self, proxy=None):
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

        kwargs = {
            'headless': False,
            'args': browser_args,
            'ignore_default_args': ["--enable-automation"],  # 移除Playwright默认的自动化参数
            'slow_mo': random.randint(100, 300)  # 随机放慢操作（模拟人类速度）
        }

        if self.browser_type == 'chrome':  # chrome浏览器
            kwargs['channel'] = self.browser_type
        elif self.browser_type == 'msedge':
            kwargs['executable_path'] = self.edge_path  # edge浏览器

        self.browser = self.playwright.chromium.launch(**kwargs)


        # 创建上下文
        self.context = self.browser.new_context(
            viewport=None,
            user_agent=self.user_agent,
            accept_downloads=True,
            proxy=proxy,
            # extra_http_headers={
            #     'Accept-Language': 'en-US,en;q=0.9',
            # }  # 英文浏览
        )

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

    def goto(self, url, timeout=None, proxy=None, way='new'):
        """proxy格式：{'server': 'http://127.0.0.1:7892'}"""
        if not self.playwright:
            if way == 'new':
                self.start_borwser(proxy)
            else:
                self.start_exists_browser()
        for i in range(3):
            try:
                self.page.goto(url, timeout=self.timeout if not timeout else timeout, wait_until='commit')  # domcontentloaded
                time.sleep(5)
                return True
            except Exception as e:
                logger.info('%s地址访问失败：%s' % (url, e))
                continue
        return False

    def new_goto(self, url, timeout=None, close=True):
        """新开一个页面访问，并关闭上一个页面（若有）"""
        if not self.playwright:
            self.start_borwser()

        # 关闭上一个页面（如果存在）
        if self.page and close:
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
                self.page.goto(url, timeout=self.timeout if not timeout else timeout, wait_until='commit')
                time.sleep(1)
                return True
            except Exception as e:
                logger.error(f'{url}地址访问失败：{e}')
                continue
        return False

    def click(self, location, force=False, no_wait=False):
        try:
            if force:
                self.page.locator(location).click(force=force)
            else:
                self.page.locator(location).click(no_wait_after=no_wait, timeout=self.timeout)
            time.sleep(random.randint(0, 1))
        except Exception as e:
            pictureDir = os.path.join(os.path.dirname(__file__), 'photo')
            os.makedirs(pictureDir, exist_ok=True)
            errorDir = os.path.join(pictureDir, 'error')
            os.makedirs(errorDir, exist_ok=True)
            errorFile = os.path.join(errorDir, f'{time.strftime("%Y%m%d%H%M%S")}_error.png')
            logger.error(f'点击失败，截图：{errorFile}\n{e}')
            self.page.screenshot(path=errorFile, timeout=5000)


    def input(self, location, text, enter=False):
        self.page.locator(location).clear()
        self.page.fill(location, text)
        if enter:
            self.page.press(location, 'Enter')

    def slow_input(self, location, text, enter=False):
        """慢输入"""
        self.input(location, '')
        self.page.locator(location).press_sequentially(text)
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
        if str(self.context.cookies()) != str(cookie):
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
        element = self.page.locator(location)
        return element.inner_text()

    def get_attribute(self, location, key):
        return self.page.locator(location).get_attribute(key)

    def click_catch_new_page(self, location):
        """点击后调整新页面"""
        with self.context.expect_page() as new_page_info:
            # 执行打开新页面的操作
            PlayWright.click(location)
        # 获取新页面对象
        new_page = new_page_info.value

        # 等待新页面加载完成
        new_page.wait_for_load_state('networkidle')

    def switch_page(self, target='new', close=True):
        """页面切换，target:old new， close是否关闭当前页面"""
        time.sleep(2)
        pages = self.context.pages
        if len(pages) == 1:
            return False
        target_page = ''
        old_page = ''
        if target == 'new':
            target_page = pages[-1]
            old_page = pages[0]

        elif target == 'old':
            target_page = pages[0]
            old_page = pages[-1]

        self.page = target_page
        self.page.bring_to_front()
        self.page.wait_for_load_state('networkidle')
        if close:
            old_page.close()
        time.sleep(5)
        return True

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

    def upload_file(self, location, file_path):
        self.page.locator(location).set_input_files(file_path)

    def screenshot(self,file):
        self.page.screenshot(path=file)

    def login(self, url, location, key='login.xiaohognshu', way='xpath', storage=False, extra=None, file=None):
        """初始登录，并进行页面cookie、接口cookie持久化
        url 登录地址
        location 判断登录成功的元素定位
        way 元素定位方式，默认xpath
        key ini配置文件对应section及option，使用.进行分割
        """
        try:
            section, option = key.split('.')
            cookie = get_config_value(section, option, file)
            if cookie:
                self.add_cookie(eval(cookie))

            self.goto(url)
            if storage:
                storage_ = get_config_value(section, 'storage', file)
                if storage_:
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
                self.save_sessionstorage(key=f'{section}.storage', file=file)
            return True
        except Exception as e:
            logger.error(f'登录异常：{e}')
            return False

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
            time.sleep(random.uniform(0.1, 0.5))
            return True
        except Exception as e:
            logger.error(f'鼠标滑动失败：{e}')
            return False


class SpecialPlayWright(PlayWrightClass):
    def __init__(self):
        super().__init__()

        self.api_key = '4bdd79e53856dbe38d41313d0e7ac8020073e8a5bba7f1d9'

        self.headers = {'authorization': f'Bearer {self.api_key}'}

        self.environment_id = None

    def goto(self, url, timeout=None, proxy=None, way='new'):
        """重写goto，使用AdsPower指纹浏览器"""
        if not self.playwright:
            self.start_browser()
        for i in range(3):
            try:
                self.page.goto(url, timeout=self.timeout if not timeout else timeout, wait_until='commit')
                time.sleep(5)
                return True
            except Exception as e:
                logger.info('%s地址访问失败：%s' % (url, e))
                continue
        return False

    def new_goto(self, url, timeout=None, close=True):
        """重写new_goto，使用AdsPower指纹浏览器"""
        if not self.playwright:
            self.start_browser()

        if self.page and close:
            try:
                self.page.close()
            except Exception as e:
                logger.error(f'关闭旧页面失败：{e}')

        self.page = self.context.new_page()

        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            document.documentElement.lang = 'en-US';
            delete navigator.geolocation;
        """)

        for i in range(3):
            try:
                self.page.goto(url, timeout=self.timeout if not timeout else timeout, wait_until='commit')
                time.sleep(1)
                return True
            except Exception as e:
                logger.error(f'{url}地址访问失败：{e}')
                continue
        return False

    def create_enviroment(self, group_id='10238760'):
        random_id = random.randint(1,50000)
        try:
            url = 'http://127.0.0.1:50325/api/v1/user/create'

            params = {
                "name": f"新增环境{random_id}",
                "repeat_config": "",
                "username": "",
                "password": "",
                "ipchecker": "ip2location",
                "cookie": "",
                "group_id": group_id,
                "ip": "",
                # "user_proxy_config": {
                #     "proxy_soft": "other",
                #     "proxy_type": "http",
                #     "proxy_host": "127.0.0.1",
                #     "proxy_port": "7892",
                #     "proxy_user": "",
                #     "proxy_password": ""
                # },
                "country": "",
                "region": "",
                "city": "",
                "remark": "remark",
                "fingerlogger.info_config": {
                    "client_hints": {
                        "model": "",
                        "wow64": "",
                        "mobile": "",
                        "bitness": "64",
                        "platform": "macOS",
                        "architecture": "arm",
                        "ua_full_version": "150.0.7871.46",
                        "platform_version": "13.6.0"
                    },
                    "tls": "",
                    "automatic_timezone": "1",
                    "allow_scan_ports": "",
                    "dpr": 2,
                    "webgl": "0",
                    "audio": "0",
                    "webrtc": "local",
                    "flash": "block",
                    "location": "ask",
                    "accuracy": "1000",
                    "gpu": "2",
                    "gyroscope": "1",
                    "page_language": "native",
                    "client_rects": "1",
                    "webgl_config": {
                        "unmasked_vendor": "",
                        "unmasked_renderer": "",
                        "system": "",
                        "webgpu": {
                            "webgpu_switch": "1"
                        }
                    },
                    "do_not_track": "true",
                    "hardware_concurrency": "default",
                    "device_memory": "default",
                    "speech_switch": "1",
                    "scan_port_type": "1",
                    "device_name_switch": "2",
                    "device_name": "22101320I-Shanel",
                    "media_devices": "1",
                    "tls_switch": "0",
                    "canvas_id": "5055",
                    "webgl_image_id": "6474",
                    "audio_id": "706",
                    "client_rects_id": "-4660",
                    "language_switch": "1",
                    "page_language_switch": "1",
                    "location_switch": "1",
                    "longitude": "180",
                    "latitude": "90",
                    "canvas": "0",
                    "webgl_image": "0",
                    "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7871.46 Safari/537.36",
                    "screen_resolution": "none",
                    "sys_resolution": "",
                    "sys_dpr": "",
                    "mac_address_config": {
                        "model": "2",
                        "address": "ac:83:f3:a8:49:3a"
                    },
                    "browser_kernel_config": {
                        "version": "150",
                        "type": "chrome"
                    },
                    "network_information_type": "0"
                }
            }

            environment_id = requests.post(url, headers=self.headers, json=params).json()['data']['id']
            self.environment_id = environment_id
            return True
        except Exception as e:
            logger.error(f'创建环境失败：{e}')
            return None

    def stop_api(self):
        try:
            url = 'http://localhost:50325/api/v2/browser-profile/stop'

            params = {'profile_id': [self.environment_id]}

            response = requests.post(url, headers=self.headers, json=params).json()

            if response["msg"].lower() == "success":
                logger.info(f'环境关闭成功：{self.environment_id}')
                return True
            logger.info(f'{self.environment_id}环境关闭失败：{response}')
            return False
        except Exception as e:
            logger.error(f'{self.environment_id}环境关闭失败：{e}')


    def delete_enviroment(self):
        self.stop_api()
        time.sleep(5)
        try:
            url = 'http://localhost:50325/api/v2/browser-profile/delete'

            params = {'profile_id': [self.environment_id]}

            response = requests.post(url, headers=self.headers, json=params).json()

            if response["msg"].lower() == "success":
                logger.info(f'环境删除成功：{self.environment_id}')
                return True
            logger.info(f'{self.environment_id}环境删除失败：{response}')
            return False
        except Exception as e:
            logger.error(f'{self.environment_id}环境删除失败：{e}')

    def start_api(self):
        """启动指纹浏览器api"""
        try:
            # AdsPower Local API 地址
            api_url = "http://127.0.0.1:50325/api/v1/browser/start"

            # 请求启动浏览器环境
            response = requests.get(api_url, headers=self.headers, params={'user_id': self.environment_id})
            result = response.json()

            if result["code"] == 0:
                # 从返回数据中提取 WebSocket 地址，用于 Playwright 连接
                # 注意：接口返回的可能有 'ws' 或 'webdriver' 等字段，'ws' 通常用于 Playwright/Puppeteer
                ws_endpoint = result["data"]["ws"]["puppeteer"]
                logger.info(f"成功启动环境，连接地址: {ws_endpoint}")
                return ws_endpoint
            else:
                logger.error(f"环境启动失败: {result}")
                return False
        except Exception as e:
            logger.error(f'环境启动失败：{e}')
            return False

    def start_browser(self):
        if not self.playwright:
            self.create_enviroment()
            if not self.environment_id:
                return False
            ws_endpoint = self.start_api()
            if not ws_endpoint:
                return False

            self.playwright = sync_playwright().start()

            self.browser = self.playwright.chromium.connect_over_cdp(ws_endpoint)

            self.context = self.browser.contexts[-1]

        # 优先复用已有页面，没有则新建
        if self.context.pages:
            self.page = self.context.pages[-1]
            for page in self.context.pages:
                if page != self.page:
                    page.close()
        else:
            self.page = self.context.new_page()

        self.page.set_viewport_size({"width": self.width, "height": self.height})
        return True


PlayWright = PlayWrightClass()
