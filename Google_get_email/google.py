# coding='utf-8'
"""Google 关键词采集：搜索关键词 -> 抓取前 N 页搜索结果 -> 逐个访问网页 -> 提取联系方式

输出字段：关键词、国家、网站名称、网站链接、邮箱、电话
    · 首页缺电话或邮箱时，会自动补看「联系我们 / 关于我们」页面；
      补看页同样用接口抓取（必要时用浏览器再分析），
      若仍然没有数据，对应单元格写「暂无匹配数据」，不再输出补看链接。

本模块只负责「采集 + 写表」，界面在 run.py，Facebook 采集在 facebook.py。

用法：
    python run.py                                   图形界面（推荐，可切 Google / Facebook）
    python google.py -k "灯具厂家,LED供应商" -p 127.0.0.1:7892
    python google.py -k "灯饰" --no-proxy --pages 5 --max-sites 30 -o out.xlsx

另外，本文件同时是「通用层」的所在地：
结果表读写（open_workbook / save_records）、运行时钩子（set_runtime_hooks /
report_progress / stop_requested）、以及国家识别（detect_country）。
facebook.py 直接复用这些，保证两个采集源写进同一套 xlsx、列结构只维护一处。

流程：
    1. 用 Google 搜索关键词，翻 max_pages 页（默认 10 页），
       每页条数由 per_page 控制（默认 10，对应 Google 的 num 参数）
    2. 收集结果链接（跳过 Google 自家、社交平台、文件类链接）
       注意 Google 结果页的 href 现在是 /goto?url=<protobuf 加密串>，解不出目标地址，
       必须用每条结果下方 <cite> 里显示的真实域名来还原（见 resolve_result_url），
       老格式 /url?q=<目标> 也能自动还原
    3. 优先用 requests 接口逐个抓取网页；JS 渲染 / 反爬站点
       再用浏览器兜底（见 USE_HTTP_FIRST），
       从 tel:/mailto: 链接、JSON-LD、页面正文里提取电话 / 邮箱 / 公司名
    4. 首页缺电话或邮箱时，自动再打开「联系我们 / 关于我们」页补抓（见 VISIT_CONTACT_PAGE）
    5. 同一域名合并成一条记录，写成 xlsx（每条落盘，中断不丢）
    6. 按页面地址 / 电话号码判断所属国家（见 detect_country）

说明：
    * Google 需要代理，界面上会提示输入（格式 127.0.0.1:7892）
    * 浏览器用系统 Edge/Chrome，遇到人机验证请在窗口里手动点一下
    * 采集有随机间隔，避免被 Google 判定为异常流量
"""
import os
import re
import sys
import time
import json
import random
import argparse
from html.parser import HTMLParser
from html import unescape as html_unescape
from urllib.parse import urlparse, urljoin, quote_plus, parse_qs, unquote

try:
    import requests
except ImportError:                       # 没装 requests 时退回纯浏览器模式
    requests = None

def _app_dirs():
    """返回两个目录：(可写目录, 资源目录)。

    PyInstaller 打包后 __file__ 指向临时解包目录 _MEIPASS（每次启动都不一样、
    进程退出就被删掉），所以必须区分开：

      · 可写目录：结果 xlsx、日志这类要留给用户的东西 → exe 所在目录
      · 资源目录：app.ico 这类只读资源 → _MEIPASS（跟着 exe 一起解包）

    直接跑 .py 时两者都是脚本所在目录，行为和以前完全一致。
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return exe_dir, getattr(sys, '_MEIPASS', exe_dir)
    here = os.path.dirname(os.path.abspath(__file__))
    return here, here


BASE_DIR, RES_DIR = _app_dirs()
# 用 BASE_DIR 推出项目根目录：直接运行脚本时 __file__ 可能是相对路径，
# Path(__file__).parent.parent 会指到当前目录，导致找不到 newPlayWright。
# 打包后 newPlayWright 已经打进 exe，这一行只是无害的兜底。
sys.path.append(os.path.dirname(BASE_DIR))

from newPlayWright import PlayWright, logger

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

# 浏览器操作可能抛出的异常：Playwright 自己的 Error、超时，以及页面被关闭 /
# 导航中断等引起的 OSError / RuntimeError。收敛成元组，避免到处写
# except Exception 把真正的代码错误也吞掉。
#
# 浏览器统一走 newPlayWright（底层 playwright），没有第二套实现。
from playwright.sync_api import Error as _BrowserError

BROWSER_ERRORS = (_BrowserError, OSError, RuntimeError, ValueError)

if requests is not None:
    try:
        # 部分企业站证书过期，关闭校验时不想刷满警告
        requests.packages.urllib3.disable_warnings()
    except AttributeError:
        pass


# ==================== 采集参数（按需改这里） ====================
MAX_SERP_PAGES = 10          # Google 搜索结果最多翻几页（每页约 10 条）
MAX_SITES = 100              # 最多访问多少个网页（防止跑飞）
PAGE_DELAY = (1.5, 3.5)      # 用浏览器访问时的随机等待（接口抓取不等待）
SERP_DELAY = (2.5, 5.0)      # 每翻一页搜索结果的随机等待（秒）
PAGE_TIMEOUT = 25000         # 单个网页加载超时（毫秒）
OUT_NAME = '结果.xlsx'
NUM_PER_PAGE = 10            # Google 每页返回多少条（URL 里的 num 参数）

# ==================== 进度与停止（供 GUI 调用） ====================
# CLI 下这些都是空的，不产生任何额外开销；
# GUI 启动采集前用 set_runtime_hooks() 注入回调与停止信号。
PROGRESS_HOOK = None         # callable(stage, current, total, text)
RECORD_HOOK = None           # callable(dict)  每采到一个网站就回调一次
LINK_HOOK = None             # callable(dict)  搜到一条结果链接就回调一次
STOP_EVENT = None            # threading.Event 实例


def set_runtime_hooks(progress=None, stop_event=None, record=None,
                      link=None):
    """安装 / 卸载进度回调、停止信号、实时记录/链接回调（GUI 用）。"""
    global PROGRESS_HOOK, STOP_EVENT, RECORD_HOOK, LINK_HOOK
    PROGRESS_HOOK = progress
    STOP_EVENT = stop_event
    RECORD_HOOK = record
    LINK_HOOK = link


def report_progress(stage, current=0, total=0, text=''):
    """上报进度。GUI 传进来的回调必须不能把采集搞崩，所以这里兜住异常。"""
    if PROGRESS_HOOK is None:
        return
    try:
        PROGRESS_HOOK(stage, current, total, text)
    except Exception:          # noqa: BLE001  界面异常不该中断采集
        pass


def report_record(rec):
    """上报一条刚采到的记录（GUI 用来实时刷表格）。"""
    if RECORD_HOOK is None:
        return
    try:
        RECORD_HOOK(rec)
    except Exception:          # noqa: BLE001
        pass


def report_link(url, title='', site_name='', keyword='', seq=0):
    """上报一条搜到的结果链接。

    让界面在「还没开始访问」时就把链接列出来，用户能立刻看到进度，
    而不是等所有网站都跑完才一次性冒出来。
    """
    if LINK_HOOK is None:
        return
    try:
        LINK_HOOK({
            'keyword': keyword,
            'url': url,
            'title': title or '',
            'site_name': site_name or '',
            'seq': seq,
        })
    except Exception:          # noqa: BLE001
        pass


def stop_requested():
    """用户点了「停止」没有"""
    return STOP_EVENT is not None and STOP_EVENT.is_set()

# 首页电话/邮箱任一项缺失时，是否再打开「联系我们 / 关于我们」页面补抓
# 很多企业官网只在联系页留联系方式，这一步能明显提高命中率
VISIT_CONTACT_PAGE = True
CONTACT_PAGE_LIMIT = 2       # 每个网站最多补看几个联系页（别设太大，会变慢）

# 既没有电话、也没有邮箱、也没判出国家的网站，是否也写入结果表
#   True（默认）：只要访问过就写入 —— 没采到的单元格显示「暂无匹配数据」/「未知」，
#                结果表就是一份完整的「访问过哪些网站」清单
#   False        ：不写入，日志会列出跳过了哪些站点
WRITE_NO_CONTACT = True

# 同一域名只访问一个搜索结果。访站时本来就会自动补看「联系/关于」页，
# 同一个站被搜到多个页面时重复访问收益很低，跳过可明显缩短整体耗时。
ONE_RESULT_PER_DOMAIN = True

# 表格里已经有相同链接时，不再访问该链接（忽略 www. 和末尾斜杠差异）
SKIP_EXISTING_LINKS = True

# ==================== 接口抓取（requests） ====================
# 优先用 requests 直接抓 HTML，比浏览器快一个数量级；
# 遇到 JS 渲染 / 反爬拦截 / 证书错误时再退回浏览器。
USE_HTTP_FIRST = True
HTTP_FALLBACK_TO_BROWSER = True   # 接口失败时是否用浏览器重试
HTTP_FALLBACK_IF_EMPTY = False    # 接口成功但没采到联系方式时，是否再用浏览器兜底
BROWSER_RETRY_CHECKED_PAGES = True  # 补看页接口仍无邮箱时，用浏览器再分析补看页
HTTP_TIMEOUT = 12                 # 单次请求超时（秒）
# 接口抓取固定串行（一次一个网站）：
# 行为可预测，出问题能直接定位到是哪个 URL，也不需要线程池。
HTTP_VERIFY_SSL = False           # 部分企业站证书异常，默认不校验

# 最终没有采集到数据时，单元格显示的文字
NO_DATA_TEXT = '暂无匹配数据'
# 国家判断不出来时的显示文字
UNKNOWN_COUNTRY = '未知'

# 接口返回这些内容说明被反爬/人机验证拦住了，改用浏览器
HTTP_BLOCK_MARKERS = (
    'cf-browser-verification', 'just a moment', 'attention required',
    'enable javascript and cookies', 'checking your browser',
    'captcha', 'access denied', '人机验证', '安全验证', '请开启javascript',
)

# ==================== 弹窗处理 ====================
# 很多网站一进去就是 Cookie 同意框、订阅弹窗、年龄验证、满屏广告遮罩，
# 不关掉会挡住正文（有些站还锁住滚动、关掉之前不渲染内容），导致采不到联系方式。
CLOSE_POPUPS = True          # 是否自动关闭弹窗
POPUP_ROUNDS = 3             # 最多关几轮（有的站一层套一层）
POPUP_MAX_CLICKS = 6         # 每轮最多点几个关闭按钮
POPUP_WAIT = 0.35            # 每轮之间的等待（秒），给关闭动画留时间

# 判定「联系我们」页面的关键词（出现在链接地址或链接文字里）
CONTACT_KEYWORDS = (
    '联系', '联系我们', '联系方式', '关于我们', '公司简介',
    'contact', 'contact-us', 'contactus', 'about', 'about-us',
    'lianxi', 'lxwm', 'gywm',
)

# 不做联系信息采集的域名（大型平台、聚合站、社交、电商、Google 自家）
#
# 判定方式是「域名本身或它的子域」命中即跳过，所以只写主域名即可：
#   'youtube.com' 同时会挡掉 www.youtube.com / m.youtube.com
#
# 这些站点要么是平台型内容（找不到真实业务联系方式），
# 要么是电商/社交媒体（采到的是平台客服，对拓客没用），
# 要么本身就有强反爬，白耗时间。
SKIP_DOMAINS = (
    # ---------- Google / 搜索引擎 ----------
    'google.com', 'googleusercontent.com', 'gstatic.com', 'goo.gl',
    'bing.com', 'yahoo.com', 'duckduckgo.com', 'yandex.com', 'baidu.com',
    'sogou.com', 'so.com', 'bing.net',

    # ---------- 视频 / 图片 / 音频平台 ----------
    'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com', 'twitch.tv',
    'bilibili.com', 'douyin.com', 'tiktok.com', 'kuaishou.com',
    'iqiyi.com', 'youku.com', 'qq.com', 'v.qq.com', 'ixigua.com',
    'soundcloud.com', 'spotify.com', 'podcast.google.com',

    # ---------- 社交 / 社区 ----------
    'facebook.com', 'fb.com', 'instagram.com', 'twitter.com', 'x.com',
    'linkedin.com', 'pinterest.com', 'reddit.com', 'tumblr.com',
    'snapchat.com', 'telegram.org', 't.me', 'discord.com', 'discord.gg',
    'whatsapp.com', 'wechat.com', 'weibo.com', 'zhihu.com', 'douban.com',
    'tieba.baidu.com', 'quora.com', 'medium.com', 'substack.com',
    'vk.com', 'line.me', 'kakao.com',

    # ---------- 电商 / 平台 ----------
    'amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.co.jp',
    'amazon.ca', 'amazon.fr', 'amazon.es', 'amazon.it', 'amazon.in',
    'amazon.com.au', 'amazon.com.mx', 'amazon.com.br', 'amazon.nl',
    'amazon.se', 'amazon.pl', 'amazon.ae', 'amazon.sg', 'amazon.sa',
    'ebay.com', 'ebay.co.uk', 'ebay.de', 'ebay.com.au',
    'alibaba.com', 'aliexpress.com', '1688.com', 'taobao.com',
    'tmall.com', 'jd.com', 'pinduoduo.com', 'suning.com', 'vip.com',
    'walmart.com', 'target.com', 'bestbuy.com', 'costco.com',
    'homedepot.com', 'lowes.com', 'ikea.com', 'etsy.com', 'shopify.com',
    'wish.com', 'temu.com', 'rakuten.com', 'mercadolibre.com',
    'flipkart.com', 'lazada.com', 'shopee.com',
    'shopee.cn', 'tokopedia.com', 'coupang.com', 'cdiscount.com',
    'otto.de', 'zalando.com', 'argos.co.uk', 'johnlewis.com',

    # ---------- 知识 / 百科 / 问答（内容站，无业务联系方式） ----------
    'wikipedia.org', 'wikimedia.org', 'wikihow.com', 'fandom.com',
    'britannica.com', 'baike.baidu.com', 'baike.com', 'zh.wikihow.com',
    'answers.com', 'ehow.com',

    # ---------- 博客 / 建站平台（子域是别人的内容） ----------
    'blogger.com', 'blogspot.com', 'wordpress.com', 'tumblr.com',
    'wixsite.com', 'weebly.com', 'squarespace.com', 'github.io',
    'gitlab.io', 'notion.site', 'myshopify.com', 'business.site',

    # ---------- 代码 / 技术社区 ----------
    'github.com', 'gitlab.com', 'bitbucket.org', 'stackoverflow.com',
    'stackexchange.com', 'gitee.com', 'npmjs.com', 'pypi.org',
    'readthedocs.io', 'sourceforge.net',

    # ---------- 新闻 / 门户 / 招聘 / 点评（聚合信息） ----------
    'news.google.com', 'cnn.com', 'bbc.com', 'bbc.co.uk', 'nytimes.com',
    'forbes.com', 'bloomberg.com', 'reuters.com', 'theguardian.com',
    'foxnews.com', 'wsj.com', 'economist.com', '163.com', 'sina.com.cn',
    'sohu.com', 'ifeng.com', 'thepaper.cn', 'toutiao.com',
    'indeed.com', 'glassdoor.com', 'monster.com', 'zhaopin.com',
    '51job.com', 'lagou.com', 'bosszhipin.com', 'liepin.com',
    'tripadvisor.com', 'yelp.com', 'dianping.com', 'meituan.com',
    'yellowpages.com', 'yell.com', 'crunchbase.com',

    # ---------- 地图 / 黄页 / B2B 目录（列的是别人，不是自己） ----------
    'mapquest.com', 'maps.google.com', 'maps.apple.com', 'bing.com/maps',
    'openstreetmap.org', 'manta.com', 'hotfrog.com', 'cylex.com',
    'brownbook.net', 'tuugo.com', 'fyple.com', 'yellowpages.ca',
    'kompass.com', 'europages.com', 'thomasnet.com', 'globalspec.com',
    'made-in-china.com', 'tradeindia.com', 'ec21.com',
    'exportersindia.com', 'b2bmatch.com', 'dnb.com', 'zoominfo.com',

    # ---------- 网盘 / 工具 / 短链 ----------
    'dropbox.com', 'box.com', 'drive.google.com', 'onedrive.live.com',
    'wetransfer.com', 'mega.nz', 'bit.ly', 'tinyurl.com', 't.co',
    'archive.org', 'web.archive.org', 'slideshare.net', 'scribd.com',
    'issuu.com', 'calameo.com',

    # ---------- 云服务 / 基础设施（企业站常挂在这些子域上） ----------
    # 注意：这些是「托管域名」，子域属主可能是真实企业，
    # 所以这里只挡主站本身，不挡子域 —— 见 _is_platform_only()
    'azurewebsites.net', 'cloudfront.net', 'herokuapp.com',
    'netlify.app', 'vercel.app', 'pages.dev', 'workers.dev',
)

# 上面这些「托管平台」只跳过主站本身，子域仍可能是真实企业
PLATFORM_HOSTS_ONLY = (
    'azurewebsites.net', 'cloudfront.net', 'herokuapp.com',
    'netlify.app', 'vercel.app', 'pages.dev', 'workers.dev',
)

# 这些子域前缀通常不是网站首页（邮箱服务器、文件服务器、CDN 等），
# 访问它们只会拿到登录页或空目录。
# 例：mail.hobbyaction.com、webmail.xxx.com、cdn.xxx.com
SKIP_HOST_PREFIXES = (
    'mail', 'webmail', 'email', 'smtp', 'imap', 'pop', 'pop3',
    'mx', 'mx1', 'mx2', 'ns', 'ns1', 'ns2', 'dns',
    'cdn', 'static', 'assets', 'img', 'images', 'media',
    'ftp', 'sftp', 'files', 'download', 'downloads',
    'api', 'admin', 'cpanel', 'whm', 'vpn', 'remote',
)

# 站点名里出现这些词，说明是大型平台/聚合站，不该进结果表
# （和 SKIP_DOMAINS 是两道防线：域名过滤挡链接，这里挡站点名称）
SKIP_NAME_KEYWORDS = (
    # 视频/社交
    'youtube', 'facebook', 'instagram', 'twitter', 'tiktok', 'linkedin',
    'pinterest', 'reddit', 'quora', 'weibo', 'wechat', 'whatsapp',
    'telegram', 'discord', 'snapchat', 'twitch', 'vimeo', 'dailymotion',
    'bilibili', 'douyin', 'kuaishou', 'iqiyi', 'youku', '微博', '抖音',
    '快手', '哔哩哔哩', '爱奇艺',
    # 电商
    'amazon', 'ebay', 'alibaba', 'aliexpress', 'taobao', 'tmall', 'jd.com',
    'walmart', 'target', 'best buy', 'etsy', 'shopee', 'lazada', 'temu',
    'wish.com', 'rakuten', 'flipkart', '淘宝', '天猫', '京东', '拼多多',
    '1688',
    # 百科/内容
    'wikipedia', 'wikihow', 'fandom', 'britannica', '百度百科', '维基',
    # 代码/技术
    'github', 'gitlab', 'stack overflow', 'stackoverflow', 'npm', 'pypi',
    # 新闻/门户/招聘/点评
    'cnn', 'bbc', 'nytimes', 'forbes', 'bloomberg', 'reuters',
    'the guardian', 'wall street journal', '新浪', '网易', '搜狐',
    '腾讯', '今日头条', 'indeed', 'glassdoor', 'tripadvisor', 'yelp',
    '大众点评', '美团',
    # 网盘/工具
    'dropbox', 'google drive', 'wetransfer', 'scribd', 'slideshare',
    'archive.org',
)

# 常见的「网站名称」噪声：这些不是公司名，是页面套路词
# 整串等于其中任意一个 → 丢弃
BAD_SITE_NAMES = {
    'home', 'homepage', 'index', 'untitled', 'welcome', 'official site',
    'official website', 'website', 'shop', 'store', 'online store',
    'contact us', 'about us', 'products', 'services', 'blog', 'news',
    '首页', '主页', '官网', '官方网站', '商城', '旗舰店', '联系我们',
}

# 站点名里只要包含这些片段，就说明是套路词而不是公司名
BAD_NAME_FRAGMENTS = (
    '官方旗舰店', '旗舰店', '专卖店', '官方网站', '官网首页',
    'contact us', 'about us', 'official site', 'official website',
    'online shopping', 'best deals', 'free shipping',
)

# 文件类后缀：不是业务站点，直接跳过
SKIP_SUFFIXES = (
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.rar', '.7z', '.exe', '.dmg', '.apk',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp4', '.mp3',
)

# 邮箱里出现这些顶级域说明是图片/脚本路径，不是真实邮箱
BAD_EMAIL_TLD = (
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'css', 'js', 'ico',
    'woff', 'woff2', 'ttf', 'eot', 'map',
)

# 常见的占位邮箱，去掉
BAD_EMAILS = {
    'example@example.com', 'test@test.com', 'name@domain.com',
    'your@email.com', 'user@example.com', 'info@example.com',
}

# 占位/示例域名与错误监控域名：这些地址不是真实联系方式
BAD_EMAIL_DOMAINS = {
    'example.com', 'example.org', 'example.net', 'domain.com',
    'yourdomain.com', 'email.com', 'test.com', 'sentry.io',
}

# Google 各国家/地区站点域名。搜索结果页里的 <a href> 基本都是
# https://www.google.com/url?q=<目标站> 这种跳转链接，
# 必须先还原成真实地址，否则会被 SKIP_DOMAINS 里的 google.com 全部挡掉。
GOOGLE_SEARCH_HOSTS = (
    'google.com', 'google.com.hk', 'google.com.tw', 'google.com.sg',
    'google.com.br', 'google.com.mx', 'google.com.au', 'google.com.tr',
    'google.co.jp', 'google.co.uk', 'google.co.kr', 'google.co.in',
    'google.co.nz', 'google.co.za', 'google.co.th', 'google.co.id',
    'google.de', 'google.fr', 'google.es', 'google.it', 'google.nl',
    'google.ru', 'google.ca', 'google.cn', 'google.be', 'google.at',
    'google.ch', 'google.se', 'google.pl', 'google.dk', 'google.fi',
    'google.no', 'google.pt', 'google.gr', 'google.cz', 'google.ie',
    'google.ae', 'google.sa', 'google.com.eg', 'google.com.vn',
    'google.com.ph', 'google.com.my', 'google.com.ar', 'google.com.co',
    'google.com.pe', 'google.com.ua', 'google.com.pk',
)


# ==================== 正则 ====================
RE_EMAIL = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}')
# 中国大陆手机号
RE_MOBILE_CN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
# 400 / 800 服务热线
RE_TEL_SERVICE = re.compile(r'(?<!\d)(?:400|800)[\-\s]?\d{3}[\-\s]?\d{4}(?!\d)')
# 国内固话：区号-号码（可带分机）
RE_LANDLINE = re.compile(
    r'(?<!\d)0\d{2,3}[\-\s]\d{7,8}(?:[\-\s]?\d{1,6})?(?!\d)')
# 国际号码：+国家码 后接 2~4 组数字
RE_INTL = re.compile(
    r'(?<!\d)\+\d{1,3}[\-\s]?\(?\d{1,4}\)?[\-\s]?\d{3,4}[\-\s]?\d{3,4}(?!\d)')
# 国际号码的另一种写法：00 + 国家码（欧洲/亚洲企业站很常见）
#   例：0086-755-83210457、0044 20 7946 0958
RE_INTL_00 = re.compile(
    r'(?<!\d)00\d{1,3}[\-\s]?\(?\d{1,4}\)?[\-\s]?\d{3,4}[\-\s]?\d{2,4}(?!\d)')


# ==================== 文本清洗 ====================
# 空格分隔的混淆邮箱：只匹配「一个词 at 域名」这种明确形态，
# 避免把 "contact us at info@abc.com" 里的 " at " 误替换成 @
RE_OBF_EMAIL_FULL = re.compile(
    r'([A-Za-z0-9._%+\-]+)\s+at\s+([A-Za-z0-9.\-]+)\s+dot\s+([A-Za-z]{2,12})',
    re.I)
RE_OBF_EMAIL_PART = re.compile(
    r'([A-Za-z0-9._%+\-]+)\s+at\s+([A-Za-z0-9\-]+\.[A-Za-z]{2,12})',
    re.I)


def deobfuscate(text):
    """还原常见的邮箱反爬写法：name(at)site(dot)com、name at site dot com"""
    if not text:
        return ''
    t = text
    # (at) [at] {at} AT => @
    t = re.sub(r"\s*[\(\[\{]\s*at\s*[\)\]\}]\s*", '@', t, flags=re.I)
    t = re.sub(r'\s*[\(\[\{]\s*dot\s*[\)\]\}]\s*', '.', t, flags=re.I)
    # 全角
    t = t.replace('＠', '@')
    # 空格分隔（先匹配完整的 a at b dot com，再匹配 a at b.com）
    t = RE_OBF_EMAIL_FULL.sub(r'\1@\2.\3', t)
    t = RE_OBF_EMAIL_PART.sub(r'\1@\2', t)
    return t


def clean_emails(candidates):
    """过滤掉图片路径、占位地址等假邮箱，返回去重后的列表"""
    out = []
    for raw in candidates:
        email = str(raw or '').strip().strip('.,;:<>()[]{}"\'')
        if not email or '@' not in email:
            continue
        local, _, domain = email.partition('@')
        if not local or not domain or '.' not in domain:
            continue
        tld = domain.rsplit('.', 1)[-1].lower()
        if tld in BAD_EMAIL_TLD:
            continue
        if domain.lower() in BAD_EMAIL_DOMAINS:
            continue
        if len(local) > 64 or len(email) > 100:
            continue
        if email.lower() in BAD_EMAILS:
            continue
        if email not in out:
            out.append(email)
    return out


def clean_phones(candidates):
    """规整并去重电话，过滤掉日期、纯数字串等误命中"""
    out = []
    for raw in candidates:
        p = str(raw or '').strip()
        if not p:
            continue
        digits = re.sub(r'\D', '', p)
        # 太短或太长都不像电话
        if len(digits) < 7 or len(digits) > 16:
            continue
        # 排除像日期的（20261026 这种 8 位纯数字）
        if re.fullmatch(r'(19|20)\d{6}', digits):
            continue
        # 排除整数金额/编号（7~8 位纯数字且无分隔符）
        if digits == p and len(digits) <= 8:
            continue
        norm = p if re.search(r'[\-\s+]', p) else digits
        norm = re.sub(r'\s+', ' ', norm).strip()
        if norm not in out:
            out.append(norm)
    return out


def find_contacts(text, extra_emails=None, extra_phones=None):
    """从一段文本里提取邮箱与电话"""
    text = deobfuscate(text or '')

    emails = list(extra_emails or [])
    emails += RE_EMAIL.findall(text)

    phones = list(extra_phones or [])
    phones += RE_TEL_SERVICE.findall(text)
    phones += RE_MOBILE_CN.findall(text)
    phones += RE_LANDLINE.findall(text)
    phones += RE_INTL.findall(text)
    phones += RE_INTL_00.findall(text)

    return clean_emails(emails), clean_phones(phones)


# ---------- 网站名称 ----------
def is_platform_name(name):
    """站点名是不是大型平台/套路词（这类名字不该进结果表）。

    例：'YouTube' / 'Amazon.com' / 'Facebook' / 'Home' / '官方旗舰店'

    大小写：所有比较都先转小写，'YouTube' / 'youtube' / 'YOUTUBE' 一视同仁。
    空白：中文站名里常有全角空格、不间断空格，一并归一成半角再比。
    """
    s = (name or '')
    # 归一化：全角空格 / 不间断空格 → 普通空格；多个空格合一；转小写
    s = s.replace('\u3000', ' ').replace('\xa0', ' ')
    s = re.sub(r'\s+', ' ', s).strip().lower()
    if not s:
        return False

    if s in BAD_SITE_NAMES:
        return True
    # 去掉常见后缀再比一次：'Amazon.com: Online Shopping' -> 'amazon'
    core = re.sub(r'[\.。](com|cn|net|org|co\.uk|de|jp|fr|co|io|shop)\b.*$',
                  '', s).strip()
    if core and core in BAD_SITE_NAMES:
        return True

    # 包含匹配（关键词表本身已是小写）
    for kw in SKIP_NAME_KEYWORDS:
        if kw in s:
            return True
    for frag in BAD_NAME_FRAGMENTS:
        if frag in s:
            return True
    return False


def pick_site_name(meta, title, url):
    """网站名称：优先 og:site_name，其次 <title> 去掉常见后缀，最后用域名

    命中大型平台名（YouTube / Amazon / Facebook...）时返回空串 ——
    这类结果本来就会被 is_acceptable() 按域名丢掉，名称也不该留。
    """
    name = (meta.get('og:site_name') or meta.get('application-name')
            or meta.get('apple-mobile-web-app-title') or '').strip()
    if not name and title:
        t = re.sub(r'\s+', ' ', title).strip()
        # 去掉 "xxx - Home" / "xxx | Official Site" / "xxx – Contact Us"
        parts = re.split(r'\s*[|\-–—·•]\s*', t)
        if parts and 1 < len(parts[0]) <= 40:
            name = parts[0].strip()
        elif len(t) <= 60:
            name = t
    # 平台名不收
    if name and is_platform_name(name):
        return ''
    if not name:
        name = urlparse(url).netloc.replace('www.', '')
        if is_platform_name(name):
            return ''
    return name.strip()


def jsonld_contacts(ld_blocks):
    """从 JSON-LD 结构化数据里取公司名 / 电话 / 邮箱 / 国家（最准）"""
    names, phones, emails, countries = [], [], [], []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                low = str(key).lower()
                if low == 'name' and isinstance(value, str) and value.strip():
                    names.append(value.strip())
                elif low == 'telephone' and isinstance(value, str):
                    phones.append(value.strip())
                elif low == 'email' and isinstance(value, str):
                    emails.append(value.replace('mailto:', '').strip())
                elif low == 'addresscountry':
                    # 可能是 "CN" / "United States"，也可能是 {"name": "..."}
                    if isinstance(value, str) and value.strip():
                        countries.append(value.strip())
                    elif isinstance(value, dict):
                        nm = value.get('name')
                        if isinstance(nm, str) and nm.strip():
                            countries.append(nm.strip())
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in ld_blocks or []:
        try:
            walk(json.loads(block))
        except (ValueError, TypeError):
            continue
    return names, phones, emails, countries


# ==================== 国家识别 ====================
# 依据（按可靠度从高到低）：
#   1. JSON-LD 里的 addressCountry（结构化数据，最准）
#   2. 电话号码的国际区号（+86 / 0086 这种最明确）
#   3. 页面「地址」文字里出现的国名
#   4. 地址的结构特征（中国省市+区/路/号、美国 州+ZIP、日本〒、加拿大 A1A 1A1）
#   5. 中国境内号码形态（11 位手机、400/800 热线）
#
# 原则：判断不出来就返回空（界面显示「未知」）。
# 错的国家比没有更糟 —— 客户名单上标错国别会直接误导业务。

# 国际电话区号 → 国家（1~3 位，匹配时按 1/2/3 位依次尝试）
CALLING_CODES = {
    '1': '美国',            # +1 需再看区号区分加拿大
    '7': '俄罗斯',
    '20': '埃及', '27': '南非', '30': '希腊', '31': '荷兰', '32': '比利时',
    '33': '法国', '34': '西班牙', '36': '匈牙利', '39': '意大利',
    '40': '罗马尼亚', '41': '瑞士', '43': '奥地利', '44': '英国',
    '45': '丹麦', '46': '瑞典', '47': '挪威', '48': '波兰', '49': '德国',
    '51': '秘鲁', '52': '墨西哥', '54': '阿根廷', '55': '巴西',
    '56': '智利', '57': '哥伦比亚', '58': '委内瑞拉',
    '60': '马来西亚', '61': '澳大利亚', '62': '印度尼西亚',
    '63': '菲律宾', '64': '新西兰', '65': '新加坡', '66': '泰国',
    '81': '日本', '82': '韩国', '84': '越南', '86': '中国',
    '90': '土耳其', '91': '印度', '92': '巴基斯坦', '94': '斯里兰卡',
    '95': '缅甸', '98': '伊朗',
    '212': '摩洛哥', '213': '阿尔及利亚', '216': '突尼斯',
    '234': '尼日利亚', '254': '肯尼亚',
    '351': '葡萄牙', '352': '卢森堡', '353': '爱尔兰', '354': '冰岛',
    '355': '阿尔巴尼亚', '356': '马耳他', '357': '塞浦路斯',
    '358': '芬兰', '359': '保加利亚',
    '370': '立陶宛', '371': '拉脱维亚', '372': '爱沙尼亚',
    '373': '摩尔多瓦', '374': '亚美尼亚', '375': '白俄罗斯',
    '380': '乌克兰', '381': '塞尔维亚', '385': '克罗地亚',
    '386': '斯洛文尼亚', '387': '波黑',
    '420': '捷克', '421': '斯洛伐克',
    '852': '中国香港', '853': '中国澳门', '886': '中国台湾',
    '880': '孟加拉国', '886 ': '中国台湾',
    '962': '约旦', '965': '科威特', '966': '沙特阿拉伯',
    '971': '阿联酋', '972': '以色列', '973': '巴林',
    '974': '卡塔尔', '977': '尼泊尔',
    '992': '塔吉克斯坦', '993': '土库曼斯坦',
    '994': '阿塞拜疆', '995': '格鲁吉亚', '998': '乌兹别克斯坦',
}

# +1 时用区号区分加拿大（这些是加拿大专用区号）
CA_AREA_CODES = frozenset((
    '204', '226', '236', '249', '250', '263', '289', '306', '343', '354',
    '365', '367', '368', '382', '387', '403', '416', '418', '428', '431',
    '437', '438', '450', '468', '474', '506', '514', '519', '548', '579',
    '581', '584', '587', '604', '613', '639', '647', '672', '683', '705',
    '709', '742', '753', '778', '780', '782', '807', '819', '825', '867',
    '873', '879', '902', '905',
))

# 国名别名表。顺序很重要：香港/澳门/台湾必须排在「中国」之前，
# 否则 "Hong Kong, China" 会被判成中国。
COUNTRY_ALIASES = (
    ('中国香港', ('中国香港', '中國香港', '香港', 'hong kong', 'hongkong',
                  'h.k.')),
    ('中国澳门', ('中国澳门', '中國澳門', '澳门', '澳門', 'macau', 'macao')),
    ('中国台湾', ('中国台湾', '中國台灣', '台湾', '台灣', '臺灣', 'taiwan')),
    ('中国', ('中国', '中國', '中华人民共和国', '中華人民共和國', 'china',
              'prc', "people's republic of china", 'p.r. china',
              'p.r.china', 'mainland china')),
    ('美国', ('美国', 'united states of america', 'united states',
              'u.s.a.', 'u.s.a', 'u.s.', 'usa')),
    ('加拿大', ('加拿大', 'canada')),
    ('墨西哥', ('墨西哥', 'mexico')),
    ('巴西', ('巴西', 'brazil')),
    ('阿根廷', ('阿根廷', 'argentina')),
    ('智利', ('智利', 'chile')),
    ('哥伦比亚', ('哥伦比亚', 'colombia')),
    ('秘鲁', ('秘鲁', 'peru')),
    ('英国', ('英国', 'united kingdom', 'great britain', 'u.k.', 'uk',
              'england', 'scotland', 'wales', 'northern ireland')),
    ('爱尔兰', ('爱尔兰', 'ireland')),
    ('德国', ('德国', 'germany', 'deutschland')),
    ('法国', ('法国', 'france')),
    ('意大利', ('意大利', 'italy')),
    ('西班牙', ('西班牙', 'spain')),
    ('葡萄牙', ('葡萄牙', 'portugal')),
    ('荷兰', ('荷兰', 'netherlands', 'holland')),
    ('比利时', ('比利时', 'belgium')),
    ('卢森堡', ('卢森堡', 'luxembourg')),
    ('瑞士', ('瑞士', 'switzerland')),
    ('奥地利', ('奥地利', 'austria')),
    ('瑞典', ('瑞典', 'sweden')),
    ('挪威', ('挪威', 'norway')),
    ('丹麦', ('丹麦', 'denmark')),
    ('芬兰', ('芬兰', 'finland')),
    ('冰岛', ('冰岛', 'iceland')),
    ('波兰', ('波兰', 'poland')),
    ('捷克', ('捷克', 'czech republic', 'czechia')),
    ('斯洛伐克', ('斯洛伐克', 'slovakia')),
    ('匈牙利', ('匈牙利', 'hungary')),
    ('罗马尼亚', ('罗马尼亚', 'romania')),
    ('保加利亚', ('保加利亚', 'bulgaria')),
    ('希腊', ('希腊', 'greece')),
    ('克罗地亚', ('克罗地亚', 'croatia')),
    ('斯洛文尼亚', ('斯洛文尼亚', 'slovenia')),
    ('塞尔维亚', ('塞尔维亚', 'serbia')),
    ('波黑', ('波黑', 'bosnia')),
    ('阿尔巴尼亚', ('阿尔巴尼亚', 'albania')),
    ('俄罗斯', ('俄罗斯', 'russia', 'russian federation')),
    ('乌克兰', ('乌克兰', 'ukraine')),
    ('白俄罗斯', ('白俄罗斯', 'belarus')),
    ('立陶宛', ('立陶宛', 'lithuania')),
    ('拉脱维亚', ('拉脱维亚', 'latvia')),
    ('爱沙尼亚', ('爱沙尼亚', 'estonia')),
    ('摩尔多瓦', ('摩尔多瓦', 'moldova')),
    ('土耳其', ('土耳其', 'turkey', 'turkiye', 'türkiye')),
    ('塞浦路斯', ('塞浦路斯', 'cyprus')),
    ('马耳他', ('马耳他', 'malta')),
    ('日本', ('日本', 'japan')),
    ('韩国', ('韩国', 'south korea', 'republic of korea', 'korea')),
    ('新加坡', ('新加坡', 'singapore')),
    ('马来西亚', ('马来西亚', 'malaysia')),
    ('泰国', ('泰国', 'thailand')),
    ('越南', ('越南', 'vietnam', 'viet nam')),
    ('印度尼西亚', ('印度尼西亚', '印尼', 'indonesia')),
    ('菲律宾', ('菲律宾', 'philippines')),
    ('印度', ('印度', 'india')),
    ('巴基斯坦', ('巴基斯坦', 'pakistan')),
    ('孟加拉国', ('孟加拉国', '孟加拉', 'bangladesh')),
    ('斯里兰卡', ('斯里兰卡', 'sri lanka')),
    ('尼泊尔', ('尼泊尔', 'nepal')),
    ('缅甸', ('缅甸', 'myanmar', 'burma')),
    ('阿联酋', ('阿联酋', '阿拉伯联合酋长国', 'united arab emirates',
                'u.a.e.', 'uae', 'dubai', 'abu dhabi')),
    ('沙特阿拉伯', ('沙特阿拉伯', '沙特', 'saudi arabia', 'saudi')),
    ('卡塔尔', ('卡塔尔', 'qatar')),
    ('科威特', ('科威特', 'kuwait')),
    ('巴林', ('巴林', 'bahrain')),
    ('约旦', ('约旦', 'jordan')),
    ('以色列', ('以色列', 'israel')),
    ('伊朗', ('伊朗', 'iran')),
    ('埃及', ('埃及', 'egypt')),
    ('摩洛哥', ('摩洛哥', 'morocco')),
    ('阿尔及利亚', ('阿尔及利亚', 'algeria')),
    ('突尼斯', ('突尼斯', 'tunisia')),
    ('南非', ('南非', 'south africa')),
    ('尼日利亚', ('尼日利亚', 'nigeria')),
    ('肯尼亚', ('肯尼亚', 'kenya')),
    ('澳大利亚', ('澳大利亚', '澳洲', 'australia')),
    ('新西兰', ('新西兰', 'new zealand')),
    ('乌兹别克斯坦', ('乌兹别克斯坦', 'uzbekistan')),
    ('哈萨克斯坦', ('哈萨克斯坦', 'kazakhstan')),
    ('阿塞拜疆', ('阿塞拜疆', 'azerbaijan')),
    ('格鲁吉亚', ('格鲁吉亚', 'georgia')),
)

# 只有命中这些词的文本片段才会被当成「地址」来分析。
# 不加这层限制的话，正文里随便一句 "we ship to USA" 就会把国别判错。
ADDRESS_HINTS = (
    'address', 'add:', 'addr', 'adress', 'headquarters', 'head office',
    'registered office', 'office:', 'located in', 'located at',
    'our location', 'find us', 'visit us', 'postal', 'zip', 'p.o. box',
    'p.o.box', 'p.o box',
    '地址', '公司地址', '办公地址', '所在地', '住址', '厂址', '厂区地址',
    '邮编', '联系地址', '注册地址',
)

# 地址结构特征
US_STATES = (
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID',
    'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS',
    'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK',
    'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV',
    'WI', 'WY', 'DC',
)
# 「州简称 + 5 位 ZIP」：例如 CA 90210、NY 10001-1234
RE_US_ZIP = re.compile(
    r'\b(?:%s)\s+\d{5}(?:-\d{4})?\b' % '|'.join(US_STATES))
# 日本邮编：〒123-4567
RE_JP_ZIP = re.compile(r'〒\s?\d{3}-?\d{4}')
# 加拿大邮编：A1A 1A1
RE_CA_ZIP = re.compile(r'\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b')
# 中国地址：省/自治区 + 市，或 市 + 区/县，或 路/街 + 号
RE_CN_ADDR_PROV = re.compile(
    r'[\u4e00-\u9fa5]{2,12}(?:省|自治区)[\u4e00-\u9fa5]{2,12}(?:市|州|盟)')
RE_CN_ADDR_CITY = re.compile(
    r'[\u4e00-\u9fa5]{2,12}市[\u4e00-\u9fa5]{1,12}(?:区|县|镇)')
RE_CN_ADDR_ROAD = re.compile(
    r'[\u4e00-\u9fa5]{2,20}(?:路|街|大道|大街)[\u4e00-\u9fa5\d]{0,8}\d+\s*号')
# 中文 + 「XX市」但没有区县（如「深圳市」「广州市」），单独作为弱信号
RE_CN_CITY_ONLY = re.compile(r'[\u4e00-\u9fa5]{2,10}市')
# ICP 备案号：粤ICP备17041818号 / 京ICP证000001号 / 沪ICP备...
# 这是中国大陆网站独有的强制备案号，比任何地址文字都可靠
RE_CN_ICP = re.compile(r'[\u4e00-\u9fa5]{1,2}ICP(?:备|证|许)\s*\d{4,}')
# 「城市, 州简称」：Brooklyn, NY / Austin, TX
RE_US_STATE_COMMA = re.compile(
    r',\s*(?:%s)(?!\w)' % '|'.join(US_STATES))
# 美国州全名的「城市, 州」写法：Brooklyn, New York
US_STATE_NAMES = (
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
    'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
    'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana',
    'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota',
    'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
    'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
    'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon',
    'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
    'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington',
    'West Virginia', 'Wisconsin', 'Wyoming',
)
RE_US_STATE_FULL = re.compile(
    r',\s*(?:%s)(?!\w)' % '|'.join(US_STATE_NAMES))
# 「based in / located in / headquartered in + 国名」这类明确表述。
# 刻意不含 made in / manufactured in：那说的是产地，不等于公司所在地，
# 容易把「Made in China」当成中国公司。
RE_IN_COUNTRY = re.compile(
    r'\b(?:based|located|headquartered|headquarters|hq|offices?|'
    r'address(?:ed)?\s+in)\b[^.\n]{0,40}?\bin\s+(?:the\s+)?'
    r'([A-Za-z][A-Za-z ]{2,29})',
    re.I)


def _build_country_patterns():
    """把别名表编译成正则：英文按单词边界匹配，中文按子串匹配。"""
    out = []
    for canon, aliases in COUNTRY_ALIASES:
        for alias in aliases:
            if not alias:
                continue
            if alias.isascii():
                pat = re.compile(r'(?<![a-z])' + re.escape(alias) +
                                 r'(?![a-z])', re.I)
            else:
                pat = re.compile(re.escape(alias))
            out.append((pat, canon))
    return tuple(out)


COUNTRY_PATTERNS = _build_country_patterns()


def match_country_name(text):
    """在一段文本里找国名，返回中文国名；找不到返回空串。"""
    if not text:
        return ''
    for pat, canon in COUNTRY_PATTERNS:
        if pat.search(text):
            return canon
    return ''


def address_segments(text, limit=150):
    """从正文里挑出像「地址」的片段。

    只取含地址关键词的行，避免把营销文案里的国名当成公司所在地。
    """
    out = []
    for line in re.split(r'[\r\n]+', text or ''):
        s = line.strip()
        if not s or len(s) > 500:
            continue
        low = s.lower()
        if any(h in low for h in ADDRESS_HINTS):
            out.append(s)
            if len(out) >= limit:
                break
    return out


def _intl_country_from_digits(digits):
    """按 1/2/3 位前缀匹配国际区号，返回国家名。"""
    for n in (1, 2, 3):
        code = digits[:n]
        if code in CALLING_CODES:
            if code == '1':
                # +1 需要靠区号区分美国 / 加拿大
                area = digits[1:4]
                return '加拿大' if area in CA_AREA_CODES else '美国'
            return CALLING_CODES[code]
    return ''


def country_from_phone(phones):
    """从电话号码的国际区号判断国家（只看 + 或 00 开头的明确国际号码）。"""
    for raw in phones or []:
        s = str(raw or '').strip()
        if not s:
            continue
        if s.lower().startswith('tel:'):
            s = s[4:]
        digits = re.sub(r'\D', '', s)
        if len(digits) < 7:
            continue
        body = ''
        if s.lstrip().startswith('+'):
            body = digits
        elif digits.startswith('00') and len(digits) > 9:
            body = digits[2:]
        if not body:
            continue
        name = _intl_country_from_digits(body)
        if name:
            return name
    return ''


def _has_cn_mobile(phones):
    """是否有中国境内号码形态（11 位手机 / 400 或 800 热线）。

    这两种形态在其他国家极少见，可以当作「中国」的弱信号。
    不带 +86 的固话（如 0755-88886666）不在此列 —— 英国/日本的区号
    也是 0 开头，容易误判。
    """
    for raw in phones or []:
        digits = re.sub(r'\D', '', str(raw or ''))
        if re.match(r'^1[3-9]\d{9}$', digits):
            return True
        if re.match(r'^(?:400|800)\d{7}$', digits):
            return True
    return False


def country_from_text(text):
    """从页面正文的地址信息判断国家。"""
    if not text:
        return ''
    # ① 地址行里出现国名（最直接）
    for seg in address_segments(text):
        hit = match_country_name(seg)
        if hit:
            return hit
    # ② ICP 备案号：中国大陆网站独有，比地址文字更可靠
    if RE_CN_ICP.search(text):
        return '中国'
    # ③ 地址结构特征：即使没有「地址」字样也能认出来
    if RE_CN_ADDR_PROV.search(text) or RE_CN_ADDR_CITY.search(text) \
            or RE_CN_ADDR_ROAD.search(text):
        return '中国'
    if RE_JP_ZIP.search(text):
        return '日本'
    if RE_US_ZIP.search(text):
        return '美国'
    if RE_US_STATE_COMMA.search(text) or RE_US_STATE_FULL.search(text):
        return '美国'
    if RE_CA_ZIP.search(text):
        return '加拿大'
    # ④ 「based in / located in / made in + 国名」这类明确表述
    for m in RE_IN_COUNTRY.finditer(text):
        hit = match_country_name(m.group(1))
        if hit:
            return hit
    return ''


def detect_country(text='', phones=None, ld_countries=None):
    """综合判断国家；判断不出来返回空串。"""
    # ① JSON-LD 的 addressCountry（最准）
    for raw in ld_countries or []:
        name = match_country_name(str(raw))
        if name:
            return name
        s = str(raw).strip().upper()
        # 两位国家码兜底
        code_map = {'CN': '中国', 'HK': '中国香港', 'MO': '中国澳门',
                    'TW': '中国台湾', 'US': '美国', 'CA': '加拿大',
                    'GB': '英国', 'UK': '英国', 'DE': '德国', 'FR': '法国',
                    'IT': '意大利', 'ES': '西班牙', 'NL': '荷兰',
                    'BE': '比利时', 'CH': '瑞士', 'AT': '奥地利',
                    'SE': '瑞典', 'NO': '挪威', 'DK': '丹麦',
                    'FI': '芬兰', 'PL': '波兰', 'CZ': '捷克',
                    'PT': '葡萄牙', 'GR': '希腊', 'IE': '爱尔兰',
                    'RU': '俄罗斯', 'UA': '乌克兰', 'TR': '土耳其',
                    'JP': '日本', 'KR': '韩国', 'SG': '新加坡',
                    'MY': '马来西亚', 'TH': '泰国', 'VN': '越南',
                    'ID': '印度尼西亚', 'PH': '菲律宾', 'IN': '印度',
                    'PK': '巴基斯坦', 'BD': '孟加拉国', 'LK': '斯里兰卡',
                    'AE': '阿联酋', 'SA': '沙特阿拉伯', 'IL': '以色列',
                    'EG': '埃及', 'ZA': '南非', 'NG': '尼日利亚',
                    'KE': '肯尼亚', 'MA': '摩洛哥', 'AU': '澳大利亚',
                    'NZ': '新西兰', 'MX': '墨西哥', 'BR': '巴西',
                    'AR': '阿根廷', 'CL': '智利', 'CO': '哥伦比亚',
                    'PE': '秘鲁'}
        if s in code_map:
            return code_map[s]
    # ② 国际电话号码
    hit = country_from_phone(phones)
    if hit:
        return hit
    # ③ 地址文字
    hit = country_from_text(text)
    if hit:
        return hit
    # ④ 中国境内号码形态
    if _has_cn_mobile(phones):
        return '中国'
    return ''


# ==================== 浏览器操作 ====================
# 不做静态资源拦截：视频 / 字体 / 图片等一律正常加载。
#
# 之前用 context.route 拦过 media / font，看起来能省一点流量，但风险更大：
#   · Google 的人机验证（reCAPTCHA）选项图就是普通图片请求，拦了就一片空白，
#     验证永远过不去；
#   · 缺字体会让页面布局和真实用户不同，本身就是一条自动化特征；
#   · Facebook 的搜索/主页大量内容靠 JS + 图片异步渲染，拦截容易导致
#     元素还没出现就被判定为「取不到」。
# 所以这里既然两个采集源都不需要，就整体去掉，行为最接近真实浏览器。


# 页面级反检测补丁
#
# 为什么需要：newPlayWright 的启动参数里有
#   --disable-plugins  -> navigator.plugins.length === 0
#   --disable-gpu / --disable-webgl -> canvas.getContext('webgl') === null
# 这两项是 Google 风控最先查的特征（真实浏览器绝不可能为 0 / 为 null），
# 所以一打开搜索页就直接弹人机验证。
#
# 这里不改启动参数（不影响其他项目），只在页面里把这两项补成「正常浏览器」
# 的样子：plugins 返回 5 个内置 PDF 插件，getContext('webgl') 在真被禁用时
# 返回一个参数合理的 stub。
STEALTH_JS = r"""
(() => {
    // 注意：这里必须是 IIFE 而不是裸的 `() => {...}`。
    // add_init_script 传字符串时是「当脚本执行」，裸箭头函数只会被创建然后丢弃；
    // page.evaluate 才会自动调用函数。用 IIFE 两种方式都能生效。
    // 真实的 navigator.plugins / webdriver / languages 都是原型上的访问器，
    // 只改实例会留下「自有属性」，反而成了新的指纹。
    const defProto = (proto, key, value) => {
        try {
            const old = Object.getOwnPropertyDescriptor(proto, key);
            Object.defineProperty(proto, key, {
                get: () => value,
                configurable: true,
                enumerable: old ? !!old.enumerable : true,
            });
        } catch (e) {}
    };

    // ---------- 1. webdriver ----------
    // 注意：真实 Chrome 里 navigator.webdriver 是 false，不是 undefined。
    // 返回 undefined 本身就是一条特征。
    if (navigator.webdriver !== false) {
        try {
            defProto(Navigator.prototype, 'webdriver', false);
        } catch (e) {}
    }

    // ---------- 2. window.chrome ----------
    if (!window.chrome) { window.chrome = {}; }
    if (!window.chrome.runtime) { window.chrome.runtime = {}; }

    // ---------- 3. plugins / mimeTypes：造出像真的 PluginArray ----------
    // 关键：必须是 PluginArray 的实例（原型链正确），
    //       Object.prototype.toString.call(navigator.plugins) === '[object PluginArray]'
    // 另外 plugins 与 mimeTypes 必须互相自洽：5 个插件都指向同一个
    // application/pdf 的 MimeType，mimeTypes 里同时有 application/pdf 和 text/pdf。
    if (!navigator.plugins || navigator.plugins.length === 0) {
        try {
            const P = (typeof Plugin !== 'undefined') ? Plugin.prototype : null;
            const PA = (typeof PluginArray !== 'undefined')
                ? PluginArray.prototype : null;
            const MP = (typeof MimeType !== 'undefined') ? MimeType.prototype : null;
            const MA = (typeof MimeTypeArray !== 'undefined')
                ? MimeTypeArray.prototype : null;

            const makeMime = (type, suffixes) => {
                const mime = MP ? Object.create(MP) : {};
                Object.defineProperties(mime, {
                    type: { value: type, enumerable: true },
                    suffixes: { value: suffixes, enumerable: true },
                    description: {
                        value: 'Portable Document Format', enumerable: true,
                    },
                    enabledPlugin: { value: null, writable: true },
                });
                return mime;
            };

            const pdf = makeMime('application/pdf', 'pdf');
            const textPdf = makeMime('text/pdf', 'pdf');

            const makePlugin = (name) => {
                const plugin = P ? Object.create(P) : {};
                Object.defineProperties(plugin, {
                    name: { value: name, enumerable: true },
                    filename: { value: 'internal-pdf-viewer', enumerable: true },
                    description: {
                        value: 'Portable Document Format', enumerable: true,
                    },
                    length: { value: 1, enumerable: false },
                    item: {
                        value: (i) => (i === 0 ? pdf : null),
                        enumerable: false,
                    },
                    namedItem: {
                        value: (n) => (n === 'application/pdf' ? pdf : null),
                        enumerable: false,
                    },
                });
                Object.defineProperty(plugin, 0, {
                    value: pdf, enumerable: true,
                });
                pdf.enabledPlugin = plugin;
                return plugin;
            };

            const names = ['PDF Viewer', 'Chrome PDF Viewer',
                           'Chromium PDF Viewer', 'Microsoft Edge PDF Viewer',
                           'WebKit built-in PDF'];
            const list = names.map(makePlugin);

            const arr = PA ? Object.create(PA) : {};
            list.forEach((p, i) => {
                Object.defineProperty(arr, i, { value: p, enumerable: true });
            });
            Object.defineProperties(arr, {
                length: { value: list.length, enumerable: false },
                item: { value: (i) => list[i] || null, enumerable: false },
                namedItem: {
                    value: (n) => list.find(p => p.name === n) || null,
                    enumerable: false,
                },
                refresh: { value: () => {}, enumerable: false },
            });

            const mimes = [pdf, textPdf];
            const mimeArr = MA ? Object.create(MA) : {};
            mimes.forEach((m, i) => {
                Object.defineProperty(mimeArr, i, { value: m, enumerable: true });
            });
            Object.defineProperties(mimeArr, {
                length: { value: mimes.length, enumerable: false },
                item: { value: (i) => mimes[i] || null, enumerable: false },
                namedItem: {
                    value: (n) => mimes.find(m => m.type === n) || null,
                    enumerable: false,
                },
            });

            defProto(Navigator.prototype, 'plugins', arr);
            defProto(Navigator.prototype, 'mimeTypes', mimeArr);
            defProto(Navigator.prototype, 'pdfViewerEnabled', true);
        } catch (e) {}
    }

    // ---------- 4. WebGL：真被禁用时给出参数合理的 stub ----------
    try {
        const makeStub = (type, canvas) => {
            const VENDOR = 'Google Inc. (Intel)';
            const RENDERER = 'ANGLE (Intel, Intel(R) UHD Graphics 630 '
                           + 'Direct3D11 vs_5_0 ps_5_0, D3D11)';
            const EXTS = [
                'ANGLE_instanced_arrays', 'EXT_blend_minmax',
                'EXT_color_buffer_half_float', 'EXT_disjoint_timer_query',
                'EXT_float_blend', 'EXT_frag_depth',
                'EXT_shader_texture_lod', 'EXT_texture_compression_bptc',
                'EXT_texture_compression_rgtc', 'EXT_texture_filter_anisotropic',
                'EXT_sRGB', 'KHR_parallel_shader_compile',
                'OES_element_index_uint', 'OES_fbo_render_sample',
                'OES_standard_derivatives', 'OES_texture_float',
                'OES_texture_float_linear', 'OES_texture_half_float',
                'OES_texture_half_float_linear', 'OES_vertex_array_object',
                'WEBGL_color_buffer_float', 'WEBGL_compressed_texture_s3tc',
                'WEBGL_debug_renderer_info', 'WEBGL_depth_texture',
                'WEBGL_draw_buffers', 'WEBGL_lose_context',
                'WEBGL_multi_draw',
            ];
            const PARAMS = {
                7936: VENDOR,            // VENDOR
                7937: RENDERER,          // RENDERER
                7938: 'WebGL 1.0 (OpenGL ES 2.0 Chromium)',   // VERSION
                35724: 'WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)',
                37445: VENDOR,           // UNMASKED_VENDOR_WEBGL
                37446: RENDERER,         // UNMASKED_RENDERER_WEBGL
                3379: 16384,             // MAX_TEXTURE_SIZE
                34076: 16384,            // MAX_CUBE_MAP_TEXTURE_SIZE
                34921: 16,               // MAX_VERTEX_ATTRIBS
                35660: 16,               // MAX_VERTEX_UNIFORM_VECTORS
                35661: 32,               // MAX_VARYING_VECTORS
                36347: 1024,             // MAX_VERTEX_TEXTURE_IMAGE_UNITS
                36348: 16,               // MAX_COMBINED_TEXTURE_IMAGE_UNITS
                36349: 1024,             // MAX_FRAGMENT_UNIFORM_VECTORS
                3413: 8,                 // ALPHA_BITS
                3414: 8,                 // BLUE_BITS
                3415: 8,                 // DEPTH_BITS
                3412: 8,                 // GREEN_BITS
                3411: 8,                 // RED_BITS
                3410: 8,                 // STENCIL_BITS
            };
            const GLC = (type === 'webgl2')
                ? (typeof WebGL2RenderingContext !== 'undefined'
                    ? WebGL2RenderingContext.prototype : null)
                : (typeof WebGLRenderingContext !== 'undefined'
                    ? WebGLRenderingContext.prototype : null);
            const gl = GLC ? Object.create(GLC) : {};

            // 脚本会读这些常量（gl.VERSION / gl.MAX_TEXTURE_SIZE ...），
            // 原型上本来就有；但原型上的方法直接用错的 this 调用会抛
            // Illegal invocation，所以下面用 Proxy 把「方法」统一换成
            // no-op，「常量」保持真实数值。
            const target = gl;
            const impl = {
                canvas: canvas,
                drawingBufferWidth: canvas ? canvas.width : 300,
                drawingBufferHeight: canvas ? canvas.height : 150,
                getParameter: (p) => (p in PARAMS ? PARAMS[p] : null),
                getExtension: (name) => {
                    if (EXTS.indexOf(name) < 0) { return null; }
                    if (name === 'WEBGL_debug_renderer_info') {
                        return {
                            UNMASKED_VENDOR_WEBGL: 37445,
                            UNMASKED_RENDERER_WEBGL: 37446,
                        };
                    }
                    return {};
                },
                getSupportedExtensions: () => EXTS.slice(),
                getContextAttributes: () => ({
                    alpha: true, antialias: true, depth: true,
                    failIfMajorPerformanceCaveat: false,
                    powerPreference: 'default',
                    premultipliedAlpha: true,
                    preserveDrawingBuffer: false,
                    stencil: false,
                    desynchronized: false,
                }),
                isContextLost: () => false,
                getError: () => 0,
                getShaderPrecisionFormat: () => ({
                    rangeMin: 127, rangeMax: 127, precision: 23,
                }),
            };
            Object.keys(impl).forEach((k) => {
                Object.defineProperty(target, k, {
                    value: impl[k], configurable: true, enumerable: false,
                    writable: true,
                });
            });

            return new Proxy(target, {
                get(t, p, r) {
                    if (typeof p === 'symbol') { return Reflect.get(t, p, r); }
                    if (Object.prototype.hasOwnProperty.call(t, p)) {
                        return Reflect.get(t, p, r);
                    }
                    let v;
                    try { v = Reflect.get(t, p, r); } catch (e) { v = undefined; }
                    // 原型方法 -> no-op（返回 null），原生常量 -> 原值
                    if (typeof v === 'function') {
                        return function () { return null; };
                    }
                    return v;
                },
            });
        };

        const orig = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (type) {
            const real = orig.apply(this, arguments);
            if (real) { return real; }        // 真能用就用真的
            if (type === 'webgl' || type === 'experimental-webgl'
                || type === 'webgl2') {
                return makeStub(type, this);  // 被 --disable-webgl 禁用时兜底
            }
            return real;
        };
    } catch (e) {}

    // ---------- 5. languages：跟启动参数 --lang=zh-CN,zh 保持一致 ----------
    try {
        if (!navigator.languages || navigator.languages.length === 0) {
            defProto(Navigator.prototype, 'languages', ['zh-CN', 'zh', 'en']);
        }
    } catch (e) {}
})();
"""

_STEALTH_STATE = {'applied': False, 'context': None}


def apply_stealth():
    """给 context 与当前页面注入反检测补丁（只对之后创建的页面自动生效）。

    context.add_init_script 只影响新页面，所以要额外对当前页 evaluate 一次。
    这里保存 context 对象本身做标记：浏览器关掉再重开时会重新注入。
    （不能用 id(context) —— 旧对象被回收后 id 会被复用，会导致误判成「已注入」。）
    """
    context = getattr(PlayWright, 'context', None)
    page = getattr(PlayWright, 'page', None)
    if _STEALTH_STATE['applied'] and _STEALTH_STATE['context'] is context:
        return
    ok = False
    if context is not None:
        try:
            context.add_init_script(STEALTH_JS)
            ok = True
        except BROWSER_ERRORS as e:
            logger.info('注入反检测脚本（context）失败：%s' % e)
    if page is not None:
        try:
            page.add_init_script(STEALTH_JS)
            page.evaluate(STEALTH_JS)     # 当前页已经加载，补一次
            ok = True
        except BROWSER_ERRORS as e:
            logger.info('注入反检测脚本（page）失败：%s' % e)
    if ok:
        _STEALTH_STATE['applied'] = True
        _STEALTH_STATE['context'] = context
        logger.info('已注入页面级反检测补丁（plugins / WebGL / webdriver）')


def reset_browser():
    """关掉浏览器并把全局引用清空，让下一次采集能重新启动。

    newPlayWright.close() 只关进程、不清属性，之后 ensure_browser() 会误以为
    浏览器还在（playwright 仍非 None），拿到的是已关闭的页面。
    GUI 连续跑多批任务时必须清引用，这里统一处理，不改对方的 close()。
    """
    try:
        PlayWright.close()
    except BROWSER_ERRORS as e:
        logger.info('关闭浏览器时出错（可忽略）：%s' % e)
    except Exception as e:          # noqa: BLE001  关闭阶段不阻塞重新开始
        logger.info('关闭浏览器时出错（可忽略）：%s' % e)
    for name in ('playwright', 'browser', 'context', 'page'):
        try:
            setattr(PlayWright, name, None)
        except Exception:           # noqa: BLE001
            pass
    _STEALTH_STATE['applied'] = False
    _STEALTH_STATE['context'] = None


EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files (x86)\Microsoft\Edge Beta\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge Beta\Application\msedge.exe',
)


def find_edge():
    """找 Edge 可执行文件。

    newPlayWright 里是硬编码 32 位路径，打包分发到别的机器时如果 Edge
    装在 Program Files（64 位）就会启动失败。这里按顺序探测，
    并补上注册表里的真实安装位置。
    """
    for p in EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    # 注册表：App Paths 里记录的是实际安装路径
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root,
                    r'SOFTWARE\Microsoft\Windows\CurrentVersion'
                    r'\App Paths\msedge.exe')
                path = winreg.QueryValue(key, None)
                winreg.CloseKey(key)
                if path and os.path.isfile(path):
                    return path
            except OSError:
                continue
    except ImportError:
        pass
    return ''


def ensure_browser(proxy=None):
    """确保浏览器已启动，并把反检测补丁挂上（兼容两种浏览器类）。"""
    if getattr(PlayWright, 'playwright', None):
        apply_stealth()               # 已启动过也要确保补丁存在
        return True

    # 启动前校正 Edge 路径：硬编码路径在当前机器上不存在时自动探测
    edge = getattr(PlayWright, 'edge_path', '')
    if not (edge and os.path.isfile(edge)):
        found = find_edge()
        if found:
            logger.info('Edge 路径自动校正：%s' % found)
            try:
                PlayWright.edge_path = found
            except (AttributeError, TypeError):
                pass
        else:
            logger.warning('没找到 msedge.exe，浏览器可能启动失败')

    starter = (getattr(PlayWright, 'start_borwser', None)
               or getattr(PlayWright, 'start_browser', None))
    if starter is None:
        return False
    try:
        if proxy is not None:
            starter(proxy)
        else:
            starter()
        apply_stealth()
        return True
    except BROWSER_ERRORS as e:
        logger.error('启动浏览器失败：%s' % e)
        return False


def safe_text(xpath, default=''):
    """取元素文本；元素不存在或取失败时返回默认值（get_text 会抛异常）"""
    try:
        if PlayWright.get_count(xpath):
            return PlayWright.get_text(xpath) or default
    except BROWSER_ERRORS:
        pass
    return default


def wait_page_ready(seconds=2.0):
    """等页面基本加载完（PlayWright.goto 内部已 sleep(5)，这里补一点）"""
    page = getattr(PlayWright, 'page', None)
    if page is not None:
        try:
            page.wait_for_load_state('domcontentloaded', timeout=PAGE_TIMEOUT)
        except BROWSER_ERRORS:
            pass
    time.sleep(seconds)


def _page_alive():
    """判断当前页面还能不能用（浏览器被关掉 / 页面崩了都返回 False）。"""
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return False
    try:
        if page.is_closed():
            return False
    except Exception:            # noqa: BLE001  老版本没有 is_closed
        pass
    return True


def goto_fast(url, retry=2):
    """打开网页（不带 PlayWright.goto 里固定的 5 秒等待）。

    批量访问几十上百个网站时，每页固定多等 5 秒会白耗好几分钟，
    这里直接用 page.goto，自己控制等待时长。
    """
    if not ensure_browser():
        return False
    for _ in range(retry):
        if not _page_alive():
            # 浏览器/页面没了：重启一次再试，别让整批任务挂在这里
            logger.warning('浏览器页面已失效，正在重启……')
            reset_browser()
            if not ensure_browser():
                return False
        try:
            PlayWright.page.goto(url, timeout=PAGE_TIMEOUT,
                                 wait_until='domcontentloaded')
            time.sleep(random.uniform(4.8, 7.8))     # 给动态内容一点渲染时间
            return True
        except BROWSER_ERRORS as e:
            logger.info('%s 打开失败：%s' % (url, e))
            time.sleep(1.5)
        except Exception as e:            # noqa: BLE001
            # AttributeError 之类（page 被置空等）也要兜住，否则会一路抛到顶层
            logger.info('%s 打开异常：%s' % (url, e))
            time.sleep(1.0)
    return False


# ==================== 弹窗处理 ====================
_POPUP_STATE = {'dialog_handler': False}


def _on_native_dialog(dialog):
    """原生 JS 弹窗（alert/confirm/prompt/beforeunload）自动关掉。

    统一用 dismiss（等于点「取消」），比 accept 安全：
    不会因为点「确定」而触发提交表单、跳转或确认离开。
    """
    try:
        kind = getattr(dialog, 'type', 'dialog')
        msg = (getattr(dialog, 'message', '') or '').strip()[:40]
        logger.info('    自动关闭原生弹窗（%s）%s' % (kind, msg))
        dialog.dismiss()
    except BROWSER_ERRORS as e:
        # 弹窗可能已被页面自己关掉，dismiss 会报错，属正常情况
        logger.info('    关闭原生弹窗失败：%s' % e)


def ensure_dialog_handler():
    """给当前页面挂上原生弹窗处理器（只挂一次）"""
    if _POPUP_STATE['dialog_handler']:
        return True
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return False
    try:
        page.on('dialog', _on_native_dialog)
        _POPUP_STATE['dialog_handler'] = True
        return True
    except BROWSER_ERRORS as e:
        logger.info('注册原生弹窗处理器失败：%s' % e)
        return False


# 关闭 DOM 浮层弹窗。
#
# 为什么不用固定 XPath：各家站的弹窗 class 名千差万别，写死必然漏；
# 这里按「语义」找：aria-label/title/class/id 含 close、文字是「关闭/我知道了/×」，
# 并且必须位于浮层容器（fixed/absolute + 有 z-index + 面积够大）内，
# 避免误点正文里的「确定」「取消」。
#
# 两步走：
#   1) 点关闭按钮（优先，保留页面原有状态）
#   2) 还挡着就移除整块遮罩，并解除滚动锁定
JS_CLOSE_POPUPS = r"""
(maxClicks) => {
    const done = { clicked: [], removed: [], scroll: false };

    const isVisible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity || '1') === 0) return false;
        const r = el.getBoundingClientRect();
        return r.width >= 6 && r.height >= 6;
    };

    const textOf = (el) => ((el.innerText || el.textContent || '') + '').trim();

    // ① 明确的关闭语义（属性/类名层面）
    const CLOSE_WORDS = ['close', 'btn-close', 'closebutton', 'close-button',
                         'modal-close', 'popup-close', 'dialog-close',
                         'icon-close', 'js-close', 'dismiss', '关闭'];
    const hasCloseHint = (el) => {
        const hay = [
            el.getAttribute('aria-label') || '',
            el.getAttribute('title') || '',
            el.getAttribute('data-dismiss') || '',
            el.getAttribute('data-close') || '',
            el.id || '',
            (el.className && el.className.toString()) || '',
        ].join(' ').toLowerCase();
        if (!hay) return false;
        return CLOSE_WORDS.some(w => hay.indexOf(w) >= 0);
    };

    // ② 关闭类按钮的常见文字（保守：不收录「取消」等容易误伤的词）
    const CLOSE_TEXTS = ['关闭', '关 闭', '关闭窗口', '我知道了', '知道了',
                         '我已知晓', '稍后再说', '暂不', '暂不订阅', '不再提示',
                         '跳过', '继续访问', '进入网站', '同意', '同意并继续',
                         '接受', '接受全部', '接受所有', '确定', '好的',
                         'close', 'close dialog', 'dismiss', 'got it',
                         'i agree', 'accept', 'accept all', 'agree',
                         'no thanks', 'not now', 'skip', 'ok', 'okay'];
    const CLOSE_SYMBOLS = ['×', '✕', '✖', '⨯', '╳', 'ⅹ', '✗'];

    // 只有落在浮层里的按钮才算（防止点到正文的「确定」）
    const inOverlay = (el) => {
        let p = el;
        for (let i = 0; i < 12 && p && p !== document.body; i++) {
            const s = window.getComputedStyle(p);
            if ((s.position === 'fixed' || s.position === 'absolute')
                && Number(s.zIndex || 0) >= 10) {
                const r = p.getBoundingClientRect();
                if (r.width >= window.innerWidth * 0.3
                    || r.height >= window.innerHeight * 0.2) return true;
            }
            p = p.parentElement;
        }
        return false;
    };

    const isCloseCandidate = (el) => {
        if (!isVisible(el)) return false;
        const r = el.getBoundingClientRect();
        if (r.width > 420 || r.height > 220) return false;   // 按钮不会很大
        if (hasCloseHint(el)) return true;                   // 语义明确，直接认可
        const raw = textOf(el);
        if (CLOSE_SYMBOLS.indexOf(raw) >= 0) return inOverlay(el);
        const t = raw.toLowerCase();
        if (t && t.length <= 16 && CLOSE_TEXTS.indexOf(t) >= 0) return inOverlay(el);
        return false;
    };

    // ---- 1. 点关闭按钮 ----
    const nodes = Array.from(document.querySelectorAll(
        'button,[role="button"],a,span,div,i,svg,[aria-label],[data-dismiss],[data-close]'
    ));
    let clicks = 0;
    for (const el of nodes) {
        if (clicks >= maxClicks) break;
        if (el.disabled) continue;
        if (!isCloseCandidate(el)) continue;
        let ok = false;
        try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
        try { el.click(); ok = true; } catch (e) { ok = false; }
        if (ok) {
            clicks++;
            const label = textOf(el).slice(0, 12)
                          || el.getAttribute('aria-label') || el.tagName;
            done.clicked.push(label);
            isVisible(el);   // 触发一次 reflow，让消失动画跟上
        }
    }

    // ---- 2. 兜底：移除挡住整屏的遮罩 ----
    const bodyLocked = () => {
        const b = document.body, h = document.documentElement;
        const hidden = (el) => el
            && (el.style.overflow === 'hidden'
                || window.getComputedStyle(el).overflow === 'hidden');
        return hidden(b) || hidden(h);
    };

    if (clicks === 0 || bodyLocked()) {
        const vpArea = window.innerWidth * window.innerHeight;
        const suspects = Array.from(document.querySelectorAll('body > *, body > * > *'))
            .filter(el => {
                if (!isVisible(el)) return false;
                const s = window.getComputedStyle(el);
                if (s.position !== 'fixed') return false;
                if (Number(s.zIndex || 0) < 10) return false;
                const r = el.getBoundingClientRect();
                return (r.width * r.height) >= vpArea * 0.25;
            });
        for (const el of suspects) {
            try { el.remove(); done.removed.push('overlay'); } catch (e) {}
        }
    }

    // ---- 3. 解除滚动锁定（很多弹窗把 body 设成 overflow:hidden）----
    try {
        if (document.body && document.body.style.overflow === 'hidden') {
            document.body.style.overflow = '';
            done.scroll = true;
        }
        if (document.documentElement
            && document.documentElement.style.overflow === 'hidden') {
            document.documentElement.style.overflow = '';
            done.scroll = true;
        }
    } catch (e) {}

    return done;
}
"""


def close_popups(rounds=None):
    """关闭当前页面的弹窗，返回实际处理的数量。

    原生弹窗由 ensure_dialog_handler() 里注册的处理器负责；
    这里处理 DOM 浮层（Cookie 同意框、订阅弹窗、广告遮罩等）。
    """
    if not CLOSE_POPUPS:
        return 0

    ensure_dialog_handler()
    rounds = rounds or POPUP_ROUNDS
    total = 0

    for _ in range(rounds):
        try:
            res = PlayWright.page.evaluate(JS_CLOSE_POPUPS, POPUP_MAX_CLICKS) or {}
        except BROWSER_ERRORS as e:
            logger.info('    关闭弹窗失败：%s' % e)
            break

        clicked = res.get('clicked') or []
        removed = res.get('removed') or []
        n = len(clicked) + len(removed)
        if n:
            total += n
            detail = []
            if clicked:
                detail.append('按钮 %d 个（%s）'
                              % (len(clicked), '、'.join(clicked[:3])))
            if removed:
                detail.append('遮罩 %d 块' % len(removed))
            logger.info('    关闭弹窗：%s' % '，'.join(detail))
        if not n:
            break                     # 没有可关的就结束
        time.sleep(POPUP_WAIT)        # 等待关闭动画/二次弹窗

    return total


def handle_google_consent():
    """处理 Google 的 Cookie / 隐私同意弹窗（不同地区文案不同）"""
    labels = ('Accept all', 'I agree', 'Agree to all', '接受全部',
              '同意', 'Accept')
    for _ in range(2):
        for label in labels:
            xpath = '//button[contains(., "%s")]' % label
            try:
                if PlayWright.get_count(xpath):
                    PlayWright.click(xpath, force=True)
                    logger.info('已点击 Google 同意按钮：%s' % label)
                    time.sleep(2)
                    return True
            except BROWSER_ERRORS:
                continue
    return False


def check_blocked():
    """检测是否被 Google 拦下（人机验证 / 流量异常）"""
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return False
    try:
        text = page.inner_text('body')[:3000]
    except BROWSER_ERRORS:
        return False
    markers = ('unusual traffic', 'not a robot', 'recaptcha',
               'detected unusual', '流量异常', '不是机器人', '安全验证')
    low = text.lower()
    if any(m in low for m in markers):
        return True
    # 有些拦截页正文不含上述词，但 URL 会跳到 /sorry/
    try:
        if '/sorry/' in (page.url or ''):
            return True
    except BROWSER_ERRORS:
        pass
    return False


# 人机验证面板的诊断脚本：看验证框在不在、选项图有没有真正加载出来
JS_RECAPTCHA_STATE = r"""
() => {
    const out = {
        anchor: 0, bframe: 0,
        images: 0, loaded: 0,
        broken: 0, text: '', hasAudio: false, hasReload: false,
    };
    try {
        out.anchor = document.querySelectorAll('iframe[src*="recaptcha"]').length;
        // 选项图在 bframe（第二个 iframe）里，跨域取不到内部 DOM，
        // 只能靠 iframe 数量 + 外层提示判断；再用 performance 里的资源统计兜底
        const ifr = document.querySelectorAll('iframe[src*="/recaptcha/"]');
        out.bframe = Math.max(0, ifr.length - 1);
        const body = document.body ? document.body.innerText : '';
        out.text = body.slice(0, 800);

        // 统计 recaptcha 相关的图片请求（同源可见的部分）
        if (window.performance && performance.getEntriesByType) {
            const rs = performance.getEntriesByType('resource') || [];
            rs.forEach(r => {
                const u = r.name || '';
                if (u.indexOf('recaptcha') < 0) return;
                if (r.initiatorType === 'img' || /\.(png|jpg|jpeg|webp)(\?|$)/i.test(u)) {
                    out.images += 1;
                    if (r.transferSize > 0 || r.decodedBodySize > 0) out.loaded += 1;
                }
            });
        }

        // 页面里能取到的 img（部分版本验证图在外层）
        document.querySelectorAll('img').forEach(img => {
            const src = img.currentSrc || img.src || '';
            if (src.indexOf('recaptcha') < 0 && src.indexOf('google') < 0) return;
            out.images += 1;
            if (img.complete && img.naturalWidth > 0) out.loaded += 1;
            else out.broken += 1;
        });

        out.hasAudio = !!document.querySelector('#recaptcha-audio-button');
        out.hasReload = !!document.querySelector('.rc-button-reload, #recaptcha-reload-button');
    } catch (e) {}
    return out;
}
"""


def recaptcha_state():
    """读取人机验证面板状态；不是验证页时返回 None"""
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return None
    try:
        return page.evaluate(JS_RECAPTCHA_STATE) or {}
    except BROWSER_ERRORS:
        return None


def images_stuck(state):
    """判断验证图是不是「一张都没加载出来」

    只在「确实存在验证 iframe」且「统计到图片但全没加载」时判为卡住。
    没有统计到任何图片请求时不误判（可能只是还没开始加载）。
    """
    if not state:
        return False
    if not (state.get('anchor') or state.get('bframe')):
        return False                       # 不是验证面板
    images = state.get('images') or 0
    loaded = state.get('loaded') or 0
    return images > 0 and loaded == 0


def refresh_recaptcha_ui():
    """点验证框上的「换一组图」按钮；点不到就整页重载。"""
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return False
    # ① 刷新按钮（同源外层）
    for sel in ('.rc-button-reload', '#recaptcha-reload-button'):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=3000)
                logger.info('已点击验证码刷新按钮')
                return True
        except BROWSER_ERRORS:
            continue
    # ② 进入 bframe 内部点 refresh
    try:
        for frame in page.frames:
            u = (frame.url or '')
            if '/recaptcha/' not in u or 'anchor' in u:
                continue
            btn = frame.locator('#recaptcha-reload-button').first
            if btn.count():
                btn.click(timeout=3000)
                logger.info('已在验证框内点击刷新按钮')
                return True
    except BROWSER_ERRORS:
        pass
    # ③ 整页重载（大多能重新拉到图片）
    try:
        page.reload(wait_until='domcontentloaded', timeout=PAGE_TIMEOUT)
        logger.info('已重新加载页面以重试验证图')
        return True
    except BROWSER_ERRORS as e:
        logger.info('重新加载失败：%s' % e)
        return False


def page_kind():
    """判断当前页面类型，用于验证通过后确认「是否真的回到结果页」。

    返回 'serp'（搜索结果）/ 'sorry'（拦截页）/ 'captcha'（验证面板）/
    'google_other'（Google 其它页）/ 'external'（外部站点）
    """
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return 'none'
    try:
        url = (page.url or '').lower()
    except BROWSER_ERRORS:
        return 'none'
    if 'google.' not in url:
        return 'external'
    if '/sorry/' in url:
        return 'sorry'
    if '/search' in url:
        return 'serp'
    return 'google_other'


def wait_serp_ready(timeout=15):
    """等搜索结果真正渲染出来。

    验证通过的那一刻 Google 还在异步跳转（遮罩消失 ≠ 结果页就绪），
    所以要轮询：URL 变成 /search 且页面里出现带 h3 的链接才算好。
    返回 True 表示已就绪。
    """
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            page.wait_for_load_state('domcontentloaded', timeout=3000)
        except BROWSER_ERRORS:
            pass
        if page_kind() == 'serp':
            try:
                n = page.locator('a:has(h3)').count()
            except BROWSER_ERRORS:
                n = 0
            if n > 0:
                return True
        time.sleep(0.6)
    return False


def block_ip_hint():
    """从 /sorry/ 页面里把 Google 认为的出口 IP 和判定原因抠出来。"""
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return ''
    try:
        text = page.inner_text('body')[:2000]
    except BROWSER_ERRORS:
        return ''
    m = re.search(r'IP\s*address\s*[:：]\s*([0-9a-fA-F:.]{7,45})', text)
    return m.group(1) if m else ''


def wait_if_blocked(max_wait=180, max_reload=3):
    """被拦时等你手动完成验证。

    验证通过后不会立刻返回：Google 需要 1~3 秒跳回结果页，
    这里会等到 URL 真正变成 /search 且结果已渲染，避免「验证过了但解析 0 条」。
    """
    if not check_blocked():
        return True

    kind = page_kind()
    state = recaptcha_state()
    logger.warning('=' * 56)

    if kind == 'sorry':
        # /sorry/ 是按 IP 判定的「异常流量」页，跟浏览器指纹无关。
        # 这一步必须人来做（点「我不是机器人」/选图），脚本只负责等。
        logger.warning('Google 返回「异常流量」拦截页（/sorry/）。')
        ip = block_ip_hint()
        if ip:
            logger.warning('Google 判定的出口 IP：%s' % ip)
        logger.warning('该页面按 IP 判定，不是浏览器指纹问题 ——')
        logger.warning('浏览器反检测已生效（plugins/WebGL/webdriver 都正常），')
        logger.warning('所以继续弹验证就说明这个 IP 被标记了，需要换代理节点。')
        logger.warning('请在窗口里点「我不是机器人」并完成选图验证。')
    else:
        logger.warning('检测到 Google 人机验证，请在弹出的浏览器窗口内完成验证。')

    if state and state.get('bframe'):
        logger.warning('验证面板已出现（%d 个图片请求，已加载 %d 个）'
                       % (state.get('images', 0), state.get('loaded', 0)))
    elif state and state.get('anchor') and not state.get('bframe'):
        logger.warning('验证框还没展开 —— 先勾选「我不是机器人」，图才会出来。')
    logger.warning('最多等待 %d 秒。' % max_wait)
    logger.warning('=' * 56)

    reloads = 0
    last_stuck_log = 0
    for i in range(max_wait):
        time.sleep(1)

        if stop_requested():
            logger.warning('已停止等待验证')
            return False

        if not check_blocked():
            logger.info('验证已通过，等待 Google 跳回结果页……')
            if wait_serp_ready(15):
                logger.info('结果页已就绪（%s），继续采集' % page_kind())
            else:
                logger.warning('15 秒内未出现结果页（当前：%s），继续尝试解析'
                               % page_kind())
            return True

        state = recaptcha_state()
        if images_stuck(state) and i - last_stuck_log >= 5:
            last_stuck_log = i
            logger.warning('验证图未加载出来（请求 %d 个，成功 0 个）'
                           % (state.get('images') or 0))
            if reloads < max_reload:
                reloads += 1
                logger.warning('自动刷新验证（第 %d/%d 次）……'
                               % (reloads, max_reload))
                refresh_recaptcha_ui()
                wait_page_ready(2.0)
                continue
            logger.error('多次刷新后验证图仍加载失败。可能原因与建议：')
            logger.error('  1) 代理不稳定或被限速 —— 换一个节点再试')
            logger.error('  2) 该 IP 已被 Google 标记 —— 换 IP / 等待一段时间')
            logger.error('  3) 请在浏览器窗口里手动按 Ctrl+F5 强制刷新一次')
            logger.error('继续等待中……')

        if i and i % 30 == 0:
            logger.info('仍在等待验证……（已等 %d 秒）' % i)

    logger.error('等待验证超时（%d 秒），跳过当前步骤' % max_wait)
    return False


# ==================== 搜索 ====================
# 直接从页面里批量取自然搜索结果（标题 / href / cite / 网站名称）。
#
# 关于「能不能不用 cite」：
#   实测 Google 现在把 9/9 条结果的 href 全改成了 /goto?url=<protobuf 加密串>，
#   /url?q=<目标> 是 0 条、直链也是 0 条 —— 加密串解不出明文目标地址，
#   所以 <cite> 是目前唯一能拿到真实域名的来源，绕不开。
#
# 网站名称取自 Google 的「站点信息块」，也就是这段结构：
#   <div class="notranslate ...">
#     <div class="q0vns">
#       ...
#       <div><div><span>Horizon Hobby</span></div><div><cite>https://...</cite></div></div>
# 用 cite 反推它所在的 notranslate 容器，再取容器里第一个非空 span，
# 比固定层级 //div[1]/span 更抗 Google 改版。
JS_SERP_LINKS = r"""
() => {
    const out = [];
    const pickSiteName = (cite) => {
        if (!cite) return '';
        // cite 一般就在 div.notranslate 里；向上找最近的这个容器
        let box = cite.closest('div.notranslate')
            || cite.closest('div[class*="notranslate"]');
        if (!box) {
            let p = cite.parentElement;
            for (let i = 0; i < 5 && p; i++) {
                if ((p.className || '').toString().indexOf('notranslate') >= 0) {
                    box = p;
                    break;
                }
                p = p.parentElement;
            }
        }
        if (!box) return '';
        // 容器内第一个有文字的 span 就是站点名
        for (const sp of box.querySelectorAll('span')) {
            const t = (sp.innerText || '').trim();
            // 排除站点名之外的情况：纯图标、含域名、太长
            if (t && t.length <= 60
                && !/^https?:\/\//i.test(t)
                && !/^www\./i.test(t)
                && t.indexOf('\n') < 0) {
                return t;
            }
        }
        return '';
    };

    document.querySelectorAll('a').forEach(a => {
        const h3 = a.querySelector('h3');
        if (!h3) return;
        let cite = a.querySelector('cite');
        if (!cite) {
            // 向上找 cite 时必须限制在「本条结果」之内。
            // 一旦祖先里出现第二个 <h3>，说明已经跨出这条结果的范围，
            // 再往上 querySelector('cite') 会把页面上第一条结果的域名
            // 错配给这一条（真实踩到过：没有 cite 的结果全指向同一个网站）。
            let p = a.parentElement;
            for (let i = 0; i < 6 && p; i++) {
                if (p.querySelectorAll('h3').length > 1) break;
                cite = p.querySelector('cite');
                if (cite) break;
                p = p.parentElement;
            }
        }
        out.push({
            href: a.getAttribute('href') || '',
            cite: cite ? (cite.innerText || '').trim() : '',
            title: (h3.innerText || '').trim(),
            site_name: pickSiteName(cite),
        });
    });
    return out;
}
"""


def _serp_first_text(xpath):
    """取 XPath 命中的第一个元素的文本；取不到返回空串。"""
    try:
        return (PlayWright.get_text('(%s)[1]' % xpath) or '').strip()
    except BROWSER_ERRORS:
        return ''


def _extract_serp_by_xpath():
    """XPath 兜底：以结果链接 <a> 为锚点，只取「网站名称 + 链接」。

    Google 每条自然结果的结构大致是：

        <a href="/url?q=... 或 /goto?url=...">   ← 锚点
          ...
          <div class="notranslate">
            <div><div>
              <div><span>站点名</span></div>      ← 网站名称
              <div><cite>真实域名</cite></div>    ← 真实地址
            </div></div>
          </div>
        </a>

    用 `//div[contains(@class,"notranslate")]/../../a` 从站点信息块反推到它
    所属的 <a>。以 <a> 为锚点，名称就是它的后代，天然 1:1 对应。

    原来的写法是分别取「名称列表」和「cite 列表」再按下标配对 ——
    只要某条结果少了站点信息块，后面所有条目的名称和链接就整体串位
    （真实踩到过：整页结果的站点名全是同一个）。

    关于 cite：默认不读。只有当链接是 Google 的加密跳转（/goto?url=）
    时才补读一次 —— 那种链接解不出目标域名，不读 cite 的话这条会被
    当成 google.com 过滤掉，等于白采。这个补读是按需触发的，
    常走的路径依然只有「名称 + 链接」两个字段。
    """
    anchor_xp = '//div[contains(@class, "notranslate")]/../../a'
    try:
        total = PlayWright.get_count(anchor_xp)
    except BROWSER_ERRORS as e:
        logger.warning('【搜索】XPath 取结果链接失败：%s' % e)
        return []

    out = []
    seen = set()
    cite_used = 0
    for i in range(1, total + 1):
        base = '(%s)[%d]' % (anchor_xp, i)
        try:
            href = (PlayWright.get_attribute(base, 'href') or '').strip()
        except BROWSER_ERRORS:
            continue
        if not href or href in seen:
            # 一条结果里可能有多个 notranslate 块，会指到同一个 <a>，去重
            continue
        seen.add(href)

        # ① 网站名称
        name = _serp_first_text(
            base + '//div[contains(@class, "notranslate")]'
                   '/div/div/div[1]/span')

        # ② 链接：先看它自身能不能直接还原成目标地址
        cite = ''
        if not unwrap_google_url(href, decode_only=True):
            # 加密跳转 / 解不出来，才去读 cite 里的真实域名
            cite = _serp_first_text(
                base + '//div[contains(@class, "notranslate")]'
                       '/div/div/div[2]/cite')
            cite_used += 1

        out.append(('', href, cite, name))

    if cite_used:
        logger.info('【搜索】XPath 兜底：%d 条中有 %d 条需要读 cite 才能还原地址'
                    % (len(out), cite_used))
    return out


def extract_serp_links():
    """从当前 Google 结果页取出自然搜索结果 [(title, href, cite, site_name), ...]

    先走页面内 JS 一次取全（最快，且能同时拿到 cite 和站点名）；
    JS 拿不到（页面结构变了 / evaluate 失败）时退回 XPath。
    """
    try:
        raw = PlayWright.page.evaluate(JS_SERP_LINKS) or []
    except BROWSER_ERRORS as e:
        logger.warning('【搜索】页面解析失败，改用 XPath：%s' % e)
        raw = []

    out = []
    for item in raw:
        title = (item.get('title') or '').strip()
        href = (item.get('href') or '').strip()
        cite = (item.get('cite') or '').strip()
        site_name = (item.get('site_name') or '').strip()
        if href:
            out.append((title, href, cite, site_name))
    if out:
        return out

    return _extract_serp_by_xpath()


# cite 里可能是 "https://www.example.com" 或 "www.example.com › 路径"
RE_CITE_URL = re.compile(r'^(?:https?://)?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?:[/?#]\S*)?')


def url_from_cite(cite):
    """从 <cite> 文本里取出真实域名地址，取不到返回空串"""
    c = (cite or '').strip()
    if not c:
        return ''
    # 去掉 Google 用来分隔面包屑的 › / > 以及后面内容
    c = re.split(r'\s*[›»]\s*', c, maxsplit=1)[0].strip()
    if not c:
        return ''
    m = RE_CITE_URL.match(c)
    if not m:
        return ''
    url = m.group(0).strip()
    if not url.lower().startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def resolve_result_url(href, cite=''):
    """把一条搜索结果的链接还原成目标网站地址（纯计算，不发网络请求）。

    只处理能在本地解码的形态：
      1. <cite> 显示的真实域名
      2. /url?q=<目标> 这类老式跳转链接
      3. 本身就是目标站直链
    /goto?url=<加密串> 解不出来 —— 这时原样返回，
    后续由浏览器直接访问该 href，靠它自己跟随跳转拿到真实地址
    （见 crawl 里落地后按 page.url 校正）。
    """
    from_cite = url_from_cite(cite)
    if from_cite:
        return from_cite
    return unwrap_google_url(href)


def is_google_link(url):
    """判断一个地址是不是还停在 Google 域名下（即没能还原到目标站）。"""
    try:
        return is_google_host((urlparse(url).netloc or '').lower())
    except (ValueError, TypeError):
        return False


# Google 的结果跳转入口（访问它才会 302 到真实网站）
GOOGLE_REDIRECT_PATHS = ('/url', '/goto', '/interstitial', '/imgres',
                         '/search/url', '/amp/s')


def _is_google_redirect(url):
    """判断是不是 Google 的「跳转入口」链接 —— 这种要保留，是可以访问的入口。

    与「Google 站内链接」的区别：
        /goto?url=<加密串>   → 跳转入口，保留，浏览器访问后会到真实网站
        /search?q=...        → 站内页面，跳过
    """
    try:
        p = urlparse(str(url or ''))
    except (ValueError, TypeError):
        return False
    if not is_google_host((p.netloc or '').lower()):
        return False
    path = (p.path or '').lower()
    return any(path == s or path.startswith(s + '/')
               for s in GOOGLE_REDIRECT_PATHS)


def log_serp_diagnosis():
    """解析到 0 条时输出现场信息，便于判断原因。

    常见三种：
      1. 页面还没跳到结果页（URL 不是 /search）
      2. 结果页结构变了（有 a/h3 但取不到）
      3. 被静默拦到别的页（/sorry/、首页、consent）
    """
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return
    try:
        cur = page.url
    except BROWSER_ERRORS:
        cur = '?'
    try:
        title = page.title()
    except BROWSER_ERRORS:
        title = '?'
    try:
        info = page.evaluate(r"""() => ({
            aCount: document.querySelectorAll('a').length,
            aH3: document.querySelectorAll('a h3').length,
            h3: document.querySelectorAll('h3').length,
            cite: document.querySelectorAll('cite').length,
            rso: document.querySelectorAll('#rso').length,
            text: (document.body ? document.body.innerText : '').slice(0, 300),
        })""") or {}
    except BROWSER_ERRORS:
        info = {}

    logger.info('【诊断】当前页面类型：%s' % page_kind())
    if page_kind() == 'sorry':
        ip = block_ip_hint()
        logger.info('【诊断】这是 /sorry/ 拦截页（按 IP 判定），不是页面结构变了。'
                    + ('出口 IP：%s' % ip if ip else ''))
        logger.info('【诊断】验证通过后会自动跳到结果页；停在拦截页说明验证没过。')
    logger.info('【诊断】URL  ：%s' % (cur[:140]))
    logger.info('【诊断】标题 ：%s' % (str(title)[:100]))
    logger.info('【诊断】元素数：a=%s  a内h3=%s  h3=%s  cite=%s  #rso=%s'
                % (info.get('aCount'), info.get('aH3'), info.get('h3'),
                   info.get('cite'), info.get('rso')))
    snippet = re.sub(r'\s+', ' ', info.get('text') or '').strip()
    if snippet:
        logger.info('【诊断】正文前 300 字：%s' % snippet[:300])


def google_search(keyword, max_pages=MAX_SERP_PAGES, proxy=None,
                  per_page=NUM_PER_PAGE):
    """搜索关键词，返回 [(url, title, site_name), ...]（已去重、已过滤）

    per_page 是每页要 Google 返回多少条（num 参数），翻页步长也随之变化。
    """
    results = []
    seen = set()
    try:
        per_page = max(1, int(per_page))
    except (TypeError, ValueError):
        per_page = NUM_PER_PAGE

    # 先启动浏览器，后续翻页直接复用这个会话
    if not ensure_browser(proxy):
        logger.error('【搜索】浏览器启动失败')
        return results

    for page in range(max_pages):
        if stop_requested():
            logger.warning('【搜索】已停止，保留已找到的 %d 个链接' % len(results))
            break

        start = page * per_page
        url = ('https://www.google.com/search?q=%s&start=%d&hl=en&num=%d'
               % (quote_plus(keyword), start, per_page))
        logger.info('【搜索】第 %d/%d 页：%s' % (page + 1, max_pages, keyword))
        report_progress('search', page + 1, max_pages,
                        '搜索第 %d/%d 页' % (page + 1, max_pages))

        # 代理只在启动浏览器时生效，这里传入保持兼容（已启动则忽略）
        ok = PlayWright.goto(url, proxy=proxy)
        if not ok:
            logger.error('【搜索】第 %d 页打开失败，停止翻页' % (page + 1))
            break

        wait_page_ready(1.5)
        if page == 0:
            handle_google_consent()
            wait_page_ready(1.0)

        if not wait_if_blocked():
            break

        # 验证通过后页面可能还没跳到结果页（甚至停在 /sorry/ 或首页）。
        # 顺序：先等结果渲染 → 还不行且不在结果页 → 重新导航一次
        links = extract_serp_links()

        if not links:
            wait_serp_ready(10)          # 遮罩消失 ≠ 结果已渲染，给它 10 秒
            links = extract_serp_links()

        if not links and page_kind() != 'serp':
            kind = page_kind()
            logger.info('【搜索】当前不在结果页（%s），重新打开搜索地址……'
                        % kind)
            if PlayWright.goto(url, proxy=proxy):
                wait_page_ready(1.5)
                if not wait_if_blocked():
                    break
                wait_serp_ready(10)
                links = extract_serp_links()

        logger.info('【搜索】第 %d 页解析到 %d 个链接' % (page + 1, len(links)))

        # 解析不到时把现场信息打出来，方便判断是页面没就绪还是结构变了
        if not links:
            log_serp_diagnosis()

        parsed = 0          # 本页解析出的有效结果条数（不含重复）
        added = 0           # 其中真正新增的条数
        rejects = []
        for title, href, cite, site_name in links:
            # 单条结果解析失败不能让整页（乃至整个搜索）中断
            try:
                raw = (href or '').strip()
                if not raw:
                    continue

                # ① 先按「网站名称」过滤平台站。
                #    YouTube 这类结果在搜索结果里名字就是 "YouTube · xxx"，
                #    链接却是 /goto?url=<加密串>，本地解不出域名 ——
                #    等浏览器落地后再过滤就太晚了（已经白访问一次）。
                if is_platform_name(site_name) or is_platform_name(title):
                    rejects.append(('平台站名称', '%s | %s'
                                    % (site_name or title, raw[:60])))
                    continue

                # ② 再按「链接」过滤：能本地解析的直接查域名。
                #    /url?q=https://a.com 和直链能解出目标地址；
                #    /goto?url=<加密串> 解不出，就原样保留 ——
                #    后面由浏览器直接访问这个 href，靠它自己跟随跳转。
                href = resolve_result_url(raw, cite) or raw

                if not href.startswith('http'):
                    rejects.append(('非 http 链接', raw))
                    continue
                # Google 自家的搜索/首页链接直接跳过；
                # 但 /goto?url= 这类「跳转链接」要保留，它是访问入口。
                if is_google_link(href) and not _is_google_redirect(href):
                    rejects.append(('Google 站内链接', href[:90]))
                    continue
                # 能解析出目标域名的，顺便查一下 SKIP_DOMAINS
                if not is_google_link(href) and not is_acceptable(href):
                    rejects.append(('域名被过滤', href[:90]))
                    continue

                parsed += 1

                # 去重：网站名称 + href。
                # 加密跳转链接解不出域名，没法按域名去重，所以用「名称+链接」
                # —— 同一个站点在不同页出现时，名称和链接都一样，能挡住。
                key = _serp_dedup_key(site_name, title, href)
                if key in seen:
                    continue
                seen.add(key)

                results.append((href, title, site_name))
                added += 1
                # 实时上报：链接一解析出来就进界面列表，用户立刻能看到
                report_link(href, title, site_name, keyword, len(results))
            except Exception as e:          # noqa: BLE001
                logger.warning('【搜索】跳过一条异常结果（%s）：%s'
                               % (e, str(href)[:80]))
                continue

        # 一个都没加上时把原因打出来，方便排查（否则只有一句「可能是最后一页」）
        if added == 0 and rejects:
            logger.info('【搜索】第 %d 页 %d 个链接均不可用，示例原因：'
                        % (page + 1, len(rejects)))
            for reason, sample in rejects[:3]:
                short = sample if len(sample) <= 90 else sample[:87] + '...'
                logger.info('    %s：%s' % (reason, short))

        # 停止翻页的条件只看「本页有没有解析出结果」，不看「有没有新增」。
        # 后面几页常常全是前几页出现过的站（重复），如果按新增数判断就会
        # 误以为到底了而提前收工 —— 这是之前少翻页的直接原因。
        if parsed == 0:
            logger.info('【搜索】第 %d 页没解析出任何结果，停止翻页' % (page + 1))
            break
        if added == 0:
            logger.info('【搜索】第 %d 页 %d 条结果都重复，继续翻下一页'
                        % (page + 1, parsed))

        if page < max_pages - 1:
            time.sleep(random.uniform(*SERP_DELAY))

    logger.info('【搜索】关键词「%s」共收集 %d 个待访问链接'
                % (keyword, len(results)))
    report_progress('links', len(results), len(results),
                    '找到 %d 个链接' % len(results))
    return results


def _serp_dedup_key(site_name, title, href):
    """搜索结果的去重键：网站名称 + 链接。

    为什么不用域名：Google 现在把结果 href 换成 /goto?url=<加密串>，
    域名是加密的、解不出来，按域名去重会失效（全被当成不同站点）。

    用「名称 + 链接」的好处：
      · 同一个站出现在多页时，名称和链接都一样 → 能挡住重复
      · 加密链接互不相同 → 不会误判两个不同站为同一个

    名称缺失时退回用标题，都没有就只用链接。
    """
    name = (site_name or '').strip().lower()
    if not name:
        name = (title or '').strip().lower()
    link = (href or '').strip()
    # 链接只做轻量归一：去掉末尾斜杠和 # 锚点，保留查询串
    # （查询串里可能带结果标识，去掉会让不同结果看起来一样）
    if '#' in link:
        link = link.split('#', 1)[0]
    if link.endswith('/'):
        link = link[:-1]
    return (name, link)


# 去重时忽略的纯追踪参数。这类参数只记录「从哪里点进来的」，
# 同一页面带不带它们都是同一个页面；其余参数一律保留（见 _canonical_query）。
TRACKING_PARAMS = frozenset((
    'gclid', 'fbclid', 'msclkid', 'yclid', 'dclid', 'twclid', 'igshid',
    'mc_cid', 'mc_eid', '_ga', '_gl', '_hsenc', '_hsmi', 'vero_id',
))


def _canonical_query(query, host=''):
    """把查询串规范化成可以参与去重比较的形式。

    做两件事：
      · 丢掉「不改变页面身份」的参数 —— 纯追踪参数（utm_*、gclid、fbclid），
        以及 Facebook 专属的标签页/前端参数（sk、mibextid 等）。
        否则同一个页面会因为投放参数或落在不同标签页而变成两个链接；
      · 参数按名字排序 —— ?a=1&b=2 和 ?b=2&a=1 视为同一个。

    其他参数必须保留：很多站点的「是哪一页」完全写在查询串里，
    最典型的就是 Facebook 的 profile.php?id=123456。
    早期版本把整个查询串丢掉，导致所有 profile.php 主页挤成同一个键，
    表里只要有一条 profile.php，后面所有主页都会被误判成「已存在」而跳过。
    """
    if not query:
        return ''
    drop = TRACKING_PARAMS
    if host == FACEBOOK_CANONICAL_HOST:
        drop = drop | FACEBOOK_NOISE_PARAMS
    pairs = []
    for part in str(query).split('&'):
        if not part:
            continue
        name = part.split('=', 1)[0].strip().lower()
        if not name:
            continue
        if name.startswith('utm_') or name in drop:
            continue
        pairs.append((name, part))
    if not pairs:
        return ''
    pairs.sort(key=lambda kv: kv[0])
    return '&'.join(part for _name, part in pairs)


# Facebook 同一页面的不同前端。它们内容完全一样，不归一的话
# 同一条主页会在结果表里存成多行（搜索页有时会返回 m. / web. 的链接）。
FACEBOOK_HOST_ALIASES = frozenset((
    'facebook.com', 'www.facebook.com', 'm.facebook.com',
    'web.facebook.com', 'mbasic.facebook.com', 'touch.facebook.com',
))
FACEBOOK_CANONICAL_HOST = 'facebook.com'


# Facebook 的「前端选择 / 标签页 / 追踪」参数。它们不改变是哪个主页，
# 只是同一主页的不同视图，去重时必须忽略 —— 否则同一条主页会因为
# 落在时间线、About 标签页、或带分享参数而在表里存成多行。
FACEBOOK_NOISE_PARAMS = frozenset((
    'sk',          # 标签页：about / about_contact_and_basic_info / photos …
    'ref', 'refid', 'refsrc', 'referrer',
    '__tn__', '__cft__', '__xts__',
    'eid', 'mibextid', 'rdid', 'share_url', 'paipv', 'sfnsn', 'locale',
    '_rdr', '_rdc', 'hc_ref', 'fref', 'comment_id', 'reply_comment_id',
))


def _canonical_host(host):
    """归一化域名：小写、去端口、去末尾的点、统一 Facebook 各前端。"""
    h = (host or '').lower()
    if ':' in h:                 # 去掉端口
        h = h.split(':', 1)[0]
    h = h.rstrip('.')            # www.a.com. 这种 FQDN 写法
    if h in FACEBOOK_HOST_ALIASES:
        return FACEBOOK_CANONICAL_HOST
    return h


def _canonical_parts(url):
    """把 URL 拆成 (host, path, query)，并做去重用的归一化。

    · host ：小写、去端口；Facebook 的 www/m/web/mbasic 统一成 facebook.com
    · path ：去末尾斜杠；Facebook 的用户名不区分大小写，所以转小写
    · query：见 _canonical_query

    归一化规则只在这里定义一份 —— normalize_url 和 link_key 都调用它，
    两套规则只要有一处不同，就会出现「历史键和新链接对不上」的误判。
    其他站点的路径不动小写：绝大多数服务器路径是区分大小写的。
    """
    p = urlparse(url)
    host = _canonical_host(p.netloc)
    path = (p.path or '/').rstrip('/') or '/'
    if host == FACEBOOK_CANONICAL_HOST:
        path = path.lower()
    return host, path, _canonical_query(p.query, host)


def normalize_url(url):
    """归一化 URL 用于去重：域名 + 路径 + 规范化后的查询串。

    去掉锚点、末尾斜杠、追踪参数；保留有意义的查询参数（如 ?id=123）。
    """
    try:
        host, path, query = _canonical_parts(url)
        return host + path + ('?' + query if query else '')
    except (ValueError, TypeError, AttributeError):
        return url


def site_domain(url):
    """取站点主域名（小写、去掉 www.），用于「同站只访问一次」去重"""
    try:
        return urlparse(url).netloc.lower().replace('www.', '')
    except (ValueError, TypeError, AttributeError):
        return ''


def link_key(url):
    """链接去重键：忽略协议、www.、末尾斜杠和锚点差异。

    查询串与 normalize_url 一样做规范化后保留 —— 两者必须一致，
    否则「读出来的历史键」和「新链接算出的键」对不上。
    也兼容 normalize_url() 产出的「域名+路径」形式（没有协议）。
    """
    s = str(url or '').strip()
    if not s:
        return ''
    if '://' not in s:
        s = 'http://' + s
    try:
        p = urlparse(s)
        host = (p.netloc or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        path = (p.path or '/').rstrip('/') or '/'
        query = _canonical_query(p.query)
        return host + path + ('?' + query if query else '')
    except (ValueError, TypeError, AttributeError):
        return s.lower()


def _host_matches(host, domain):
    """host 是否是 domain 本身或它的子域（大小写不敏感）。"""
    return host == domain or host.endswith('.' + domain)


def is_acceptable(url):
    """过滤掉不需要访问的链接（大型平台、社交、电商、文件等）。

    站点名单见 SKIP_DOMAINS。命中规则：
      · host 等于域名，或是它的子域（www.youtube.com、m.youtube.com 都挡）
      · PLATFORM_HOSTS_ONLY 里的托管平台只挡主站本身，
        因为它的子域很可能是真实企业站（xxx.azurewebsites.net）

    大小写：host 统一转小写再比；常量表里的域名也在这里统一小写，
    避免名单里手写大写（如 Amazon.COM）时漏掉。
    """
    try:
        p = urlparse(url)
    except (ValueError, TypeError):
        return False
    if (p.scheme or '').lower() not in ('http', 'https'):
        return False
    host = (p.netloc or '').lower()
    if not host:
        return False
    # 去掉端口和末尾的点（FQDN 写法 www.a.com.）
    if ':' in host:
        host = host.split(':', 1)[0]
    host = host.rstrip('.')

    platform_only = set(d.lower() for d in PLATFORM_HOSTS_ONLY)
    for d in SKIP_DOMAINS:
        d = d.lower()
        if d in platform_only:
            if host == d:                 # 只挡主站
                return False
        elif _host_matches(host, d):
            return False

    # 邮箱服务器 / 文件服务器这类子域不是网站首页，
    # 访问它们只会拿到 webmail 登录页或空目录，采不到联系方式。
    # 要求至少三段（mail.a.com），避免把 mail.com 这种主站本身误杀。
    parts = host.split('.')
    if len(parts) >= 3 and parts[0] in SKIP_HOST_PREFIXES:
        return False

    if any(host.endswith(s) for s in SKIP_SUFFIXES):
        return False
    path = (p.path or '').lower()
    if any(path.endswith(s) for s in SKIP_SUFFIXES):
        return False
    return True


def is_google_host(host):
    """判断是不是 Google 的搜索/跳转域名"""
    h = (host or '').lower()
    return any(h == d or h.endswith('.' + d) for d in GOOGLE_SEARCH_HOSTS)


def unwrap_google_url(href, base='https://www.google.com', decode_only=False):
    """把 Google 结果页的链接还原成目标网站的真实地址。

    Google 的 <a href> 有三种形态，前两种必须还原，否则会被当成 google.com 过滤掉：
      1. https://www.google.com/url?q=https://example.com/&sa=U&ved=...
      2. /url?q=https://example.com/&sa=U           （相对路径）
      3. https://example.com/                        （少数情况下是直链）
    另外顺带处理 AMP 链接 /amp/s/example.com/... 和 /interstitial 中转页。

    decode_only=True 时只回答「这个链接能不能还原出目标地址」：
      能还原 → 返回还原后的地址；还原不了 → 返回空串。
    用来判断是否需要去读 <cite>（/goto?url=<加密串> 解不出来）。
    """
    if not href:
        return ''
    h = html_unescape(str(href).strip())
    if not h:
        return ''

    # 补全相对路径 / 协议相对路径
    if h.startswith('//'):
        h = 'https:' + h
    elif h.startswith('/'):
        h = base + h

    try:
        p = urlparse(h)
    except (ValueError, TypeError):
        return h
    if not is_google_host(p.netloc):
        return h                       # 已经是目标站直链

    path = (p.path or '').lower()
    query = parse_qs(p.query or '')

    # ① 跳转中转页：/url?q=<目标>&sa=U，或 /url?url=<目标>
    if path in ('/url', '/interstitial', '/imgres', '/search/url'):
        for key in ('q', 'url', 'imgurl', 'image_url', 'u'):
            values = query.get(key) or []
            for value in values:
                v = html_unescape(str(value)).strip()
                if v.startswith(('http://', 'https://')):
                    return v
                if v.startswith('//'):
                    return 'https:' + v
                if v.startswith('/'):          # 站内相对路径，非结果链接
                    continue
        # 拿不到目标（如 /goto?url=<加密串>）：交给 is_acceptable 过滤
        return '' if decode_only else h

    # ② AMP 中转页：/amp/s/example.com/path -> https://example.com/path
    if '/amp/s/' in h:
        rest = h.split('/amp/s/', 1)[1]
        if rest.startswith('http'):
            return rest
        return 'https://' + rest.lstrip('/')

    # ③ 其它 Google 域名下的链接（/goto?url=<加密串> 之类）：解不出来
    #    非 decode_only 时原样返回，交给 is_acceptable 过滤掉
    return '' if decode_only else h


# ==================== 网页提取 ====================
JS_EXTRACT = r"""
() => {
    const metas = {};
    document.querySelectorAll('meta[property],meta[name]').forEach(m => {
        const k = (m.getAttribute('property') || m.getAttribute('name') || '').toLowerCase();
        const v = (m.getAttribute('content') || '').trim();
        if (k && v && !(k in metas)) metas[k] = v;
    });
    const tels = Array.from(document.querySelectorAll('a[href^="tel:"]'))
        .map(a => a.getAttribute('href') || '');
    const mails = Array.from(document.querySelectorAll('a[href^="mailto:"]'))
        .map(a => a.getAttribute('href') || '');
    const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
        .map(s => (s.textContent || '').slice(0, 300000));
    // 站内链接：首页缺联系方式时，用来找「联系我们 / 关于我们」补抓
    const links = Array.from(document.querySelectorAll('a[href]'))
        .slice(0, 400)
        .map(a => ({ href: a.href || '', text: (a.innerText || '').trim().slice(0, 40) }))
        .filter(x => x.href.indexOf('http') === 0);
    let text = '';
    try { text = document.body ? document.body.innerText : ''; } catch (e) {}
    return {
        url: location.href,
        title: document.title || '',
        metas: metas,
        tels: tels,
        mails: mails,
        ld: ld,
        links: links,
        text: text.slice(0, 400000),
    };
}
"""


def parse_page(data, url):
    """从 JS_EXTRACT 的结果里解析出联系人信息（不含 keyword 字段）"""
    # data['url'] 是浏览器落地后的真实地址（跟随 Google 跳转后）；
    # 万一它不可用（about:blank / 空 / 非 http），退回调用方给的原地址，
    # 否则后面按域名叫「联系我们」页会全部对不上。
    final_url = (data.get('url') or '').strip()
    if not final_url.startswith('http'):
        final_url = url
    title = (data.get('title') or '').strip()
    metas = data.get('metas') or {}
    text = data.get('text') or ''

    # tel: / mailto: 链接是最可靠的来源
    # 链接里的值可能被 URL 编码（如 info%40abc.com），也可能一条 mailto
    # 里带多个地址（a@x.com,b@y.com），这里一并拆开还原。
    tel_links = [unquote(t.split(':', 1)[-1].split('?', 1)[0])
                 for t in (data.get('tels') or [])]
    mail_links = []
    for m in data.get('mails') or []:
        raw = unquote(m.split(':', 1)[-1].split('?', 1)[0])
        for part in re.split(r'[,;]', raw):
            part = part.strip()
            if part:
                mail_links.append(part)

    # JSON-LD 结构化数据
    ld_names, ld_phones, ld_emails, ld_countries = jsonld_contacts(
        data.get('ld'))

    emails, phones = find_contacts(text, mail_links + ld_emails,
                                   tel_links + ld_phones)

    return {
        'url': final_url,
        'title': title,
        'site_name': pick_site_name(metas, ld_names[0] if ld_names else title,
                                    final_url),
        'emails': emails,
        'phones': phones,
        # 国家：靠页面地址 / 电话号码判断，判断不出就留空
        'country': detect_country(text, phones, ld_countries),
        'checked_pages': [],      # 补看过的联系页（用于内部重试/日志）
    }


def contact_page_links(data, base_url):
    """从站内链接里挑出「联系我们 / 关于我们」类页面（仅同域名）"""
    try:
        base_host = urlparse(base_url).netloc.lower()
    except (ValueError, TypeError):
        return []
    out = []
    for item in data.get('links') or []:
        href = (item.get('href') or '').strip()
        anchor = (item.get('text') or '').lower()
        if not href.startswith('http'):
            continue
        try:
            p = urlparse(href)
        except (ValueError, TypeError):
            continue
        if (p.netloc or '').lower() != base_host:
            continue
        if p.path.lower().endswith(SKIP_SUFFIXES):
            continue
        probe = ((p.path or '') + ' ' + (p.query or '') + ' ' + anchor).lower()
        if any(k in probe for k in CONTACT_KEYWORDS):
            if href not in out:
                out.append(href)
    return out


# ==================== 接口抓取（requests） ====================
class _HtmlPageParser(HTMLParser):
    """把 HTML 解析成与浏览器 JS_EXTRACT 相同结构的数据（无需浏览器）。

    只取采集需要的几类信息：标题、meta、tel:/mailto:、JSON-LD、
    站内链接、可见文本。script/style 等节点会被跳过。
    """

    SKIP_TAGS = {'script', 'style', 'noscript', 'template', 'svg'}
    BLOCK_TAGS = {'p', 'div', 'br', 'li', 'tr', 'td', 'th', 'h1', 'h2',
                  'h3', 'h4', 'h5', 'h6', 'section', 'article', 'header',
                  'footer', 'address', 'table', 'ul', 'ol', 'form',
                  'label', 'button', 'figure', 'nav', 'main'}

    def __init__(self, base_url=''):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.base_url = base_url or ''
        self.title_parts = []
        self.metas = {}
        self.ld = []
        self.tels = []
        self.mails = []
        self.links = []
        self.text_parts = []
        self.in_title = False
        self.skip_depth = 0
        self.in_ld = False
        self._ld_buf = []
        self._link_href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = (tag or '').lower()
        if tag == 'title':
            self.in_title = True
        elif tag == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').strip().lower()
            content = (attrs.get('content') or '').strip()
            if key and content and key not in self.metas:
                self.metas[key] = content
        elif tag == 'script':
            if 'ld+json' in (attrs.get('type') or '').lower():
                self.in_ld = True
                self._ld_buf = []
            self.skip_depth += 1
        elif tag == 'a':
            href = (attrs.get('href') or '').strip()
            low = href.lower()
            if low.startswith('tel:'):
                self.tels.append(href)
            elif low.startswith('mailto:'):
                self.mails.append(href)
            if href and not low.startswith(('javascript:', '#', 'data:')):
                absolute = urljoin(self.base_url, html_unescape(href))
                if absolute.lower().startswith('http'):
                    self._link_href = absolute
                    self._link_text = []
        if tag in self.SKIP_TAGS and tag != 'script':
            self.skip_depth += 1
        if tag in self.BLOCK_TAGS and self.skip_depth == 0 and not self.in_ld:
            self.text_parts.append('\n')

    def handle_startendtag(self, tag, attrs):
        # 自闭合标签（<br/>、<meta/> 等）按开始 + 结束处理
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = (tag or '').lower()
        if tag == 'title':
            self.in_title = False
        elif tag == 'script':
            if self.in_ld:
                self.ld.append(''.join(self._ld_buf)[:300000])
                self.in_ld = False
                self._ld_buf = []
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag == 'a':
            if self._link_href:
                text = re.sub(r'\s+', ' ', ''.join(self._link_text)).strip()[:40]
                self.links.append({'href': self._link_href, 'text': text})
            self._link_href = None
            self._link_text = []
        if tag in self.BLOCK_TAGS and self.skip_depth == 0 and not self.in_ld:
            self.text_parts.append('\n')

    def handle_data(self, data):
        if self.in_ld:
            self._ld_buf.append(data)
            return
        if self.skip_depth > 0:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self._link_href:
            self._link_text.append(data)
        self.text_parts.append(data)

    def to_data(self):
        text = ''.join(self.text_parts)
        text = re.sub(r'[ \t\r\f\v]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n', text).strip()
        return {
            'url': self.base_url,
            'title': re.sub(r'\s+', ' ', ''.join(self.title_parts)).strip(),
            'metas': self.metas,
            'tels': self.tels,
            'mails': self.mails,
            'ld': self.ld,
            'links': self.links[:400],
            'text': text[:400000],
        }


_HTTP_SESSION = None        # 串行抓取，全局复用一个会话即可
_HTTP_PROXY = None          # {'http': ..., 'https': ...} 或 None


def configure_http_proxy(proxy):
    """把浏览器用的代理同步给 requests。

    proxy 为 None 时必须关掉 trust_env，否则 requests 会读取系统里
    可能失效的 HTTP_PROXY/HTTPS_PROXY 环境变量，导致全部站点抓取失败。
    """
    global _HTTP_PROXY
    if proxy and proxy.get('server'):
        server = proxy['server']
        _HTTP_PROXY = {'http': server, 'https': server}
    else:
        _HTTP_PROXY = None


def _http_session():
    """复用同一个 requests.Session（串行抓取，不需要按线程隔离）。"""
    global _HTTP_SESSION
    session = _HTTP_SESSION
    if session is None:
        session = requests.Session()
        ua = getattr(PlayWright, 'user_agent', '') or (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        session.headers.update({
            'User-Agent': ua,
            'Accept': ('text/html,application/xhtml+xml,application/xml;'
                       'q=0.9,*/*;q=0.8'),
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })
        _HTTP_SESSION = session
    session.trust_env = False
    session.proxies.clear()
    if _HTTP_PROXY:
        session.proxies.update(_HTTP_PROXY)
    return session


def http_page_data(url):
    """用 requests 抓取页面，返回与 JS_EXTRACT 同构的数据；失败返回 None。"""
    if requests is None:
        return None
    try:
        resp = _http_session().get(url, timeout=HTTP_TIMEOUT,
                                   allow_redirects=True,
                                   verify=HTTP_VERIFY_SSL)
    except requests.RequestException as e:
        logger.info('    接口抓取失败 %s：%s' % (url, e))
        return None

    if resp.status_code >= 400:
        logger.info('    接口抓取失败 %s：HTTP %d' % (url, resp.status_code))
        return None

    ctype = (resp.headers.get('Content-Type') or '').lower()
    if ctype and not any(t in ctype for t in
                         ('text/html', 'application/xhtml', 'text/plain',
                          'application/xml', 'text/xml')):
        logger.info('    接口跳过 %s：非网页内容（%s）' % (url, ctype))
        return None

    # 中文站常用 GBK/GB2312，requests 猜错时 text 会乱码
    if not resp.encoding or resp.encoding.lower() in ('iso-8859-1', 'ascii'):
        resp.encoding = resp.apparent_encoding or 'utf-8'
    html = resp.text or ''
    if len(html) < 50:               # 基本是空响应，交给浏览器
        return None

    low = html[:5000].lower()
    if any(m in low for m in HTTP_BLOCK_MARKERS):
        logger.info('    接口疑似被拦截，改用浏览器：%s' % url)
        return None

    final_url = resp.url or url
    parser = _HtmlPageParser(final_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception as e:            # 外部 HTML 千奇百怪，解析失败直接放弃
        logger.info('    接口解析失败 %s：%s' % (url, e))
        return None

    data = parser.to_data()
    if len(data['text']) < 20 and not (data['tels'] or data['mails']
                                      or data['ld']):
        logger.info('    接口内容过少，改用浏览器：%s' % url)
        return None
    return data


def _follow_contact_pages(info, data, loader, delay=0.0):
    """首页没提取到时，补看「联系我们 / 关于我们」这类页面。

    触发条件：
      · 首页完全没提取到联系方式（没邮箱也没电话）→ 必须补看
      · 联系方式有了、但国家没判出来 → 也补看
        （联系页往往才是真正写着地址的页面）
    没有这类链接就什么都不做 —— 不是每个站都有联系我们页。
    """
    if not VISIT_CONTACT_PAGE:
        return

    has_email = bool(info.get('emails'))
    has_phone = bool(info.get('phones'))
    has_country = bool(info.get('country'))

    if has_email and has_phone and has_country:
        return                      # 都齐了，不用补看

    if not (has_email or has_phone):
        reason = '首页没提取到联系方式'
    else:
        reason = '还缺国家'

    sub_urls = contact_page_links(data, info['url'])[:CONTACT_PAGE_LIMIT]
    if not sub_urls:
        logger.info('    %s，且页面里没有「联系我们」类链接，不做补看' % reason)
        return

    logger.info('    %s，补看联系页（%d 个）' % (reason, len(sub_urls)))
    for sub_url in sub_urls:
        if delay:
            time.sleep(random.uniform(delay, delay + 0.7))
        logger.info('    补看联系页：%s' % sub_url)
        info['checked_pages'].append(sub_url)
        sub_data = loader(sub_url)
        if not sub_data:
            logger.info('    补看页没打开：%s' % sub_url)
            continue
        sub = parse_page(sub_data, sub_url)
        for e in sub['emails']:
            if e not in info['emails']:
                info['emails'].append(e)
        for p in sub['phones']:
            if p not in info['phones']:
                info['phones'].append(p)
        # 联系页常常是唯一写着地址的地方
        if not info.get('country') and sub.get('country'):
            info['country'] = sub['country']
        if info['emails'] and info['phones'] and info.get('country'):
            break                   # 都齐了，不用再看下一个


def _browser_page_data(url):
    """用浏览器打开页面并取数据；失败返回 None。"""
    if not goto_fast(url):
        return None
    if not _page_alive():
        logger.info('【解析跳过】页面已失效：%s' % url)
        return None
    try:
        return PlayWright.page.evaluate(JS_EXTRACT) or None
    except BROWSER_ERRORS as e:
        logger.info('【解析失败】%s：%s' % (url, e))
        return None
    except Exception as e:                # noqa: BLE001
        logger.info('【解析异常】%s：%s' % (url, e))
        return None


def _smart_page_data(url):
    """补看页优先走接口，接口取不到再用浏览器（仅主线程调用）。"""
    data = http_page_data(url) if USE_HTTP_FIRST else None
    if data:
        return data
    return _browser_page_data(url)


def _retry_checked_pages_with_browser(info):
    """接口补看后仍没邮箱时，用浏览器重新分析补看页。"""
    if not info.get('checked_pages'):
        return False
    gained = False
    for sub_url in info['checked_pages'][:CONTACT_PAGE_LIMIT]:
        logger.info('    浏览器重查补看页：%s' % sub_url)
        sub_data = _browser_page_data(sub_url)
        if not sub_data:
            continue
        sub = parse_page(sub_data, sub_url)
        before = (len(info['emails']), len(info['phones']))
        for e in sub['emails']:
            if e not in info['emails']:
                info['emails'].append(e)
        for p in sub['phones']:
            if p not in info['phones']:
                info['phones'].append(p)
        # 首页没判出国家时，用补看页的地址信息补上
        if not info.get('country') and sub.get('country'):
            info['country'] = sub['country']
        if (len(info['emails']), len(info['phones'])) != before:
            gained = True
        if info['emails'] and info['phones']:
            break
    return gained


def visit_site_http(url):
    """只用 requests 抓取并解析；失败返回 None（不含 keyword 字段）。"""
    data = http_page_data(url)
    if not data:
        return None
    info = parse_page(data, url)
    _follow_contact_pages(info, data, http_page_data)
    return info


def visit_site_browser(url):
    """用浏览器访问页面，提取邮箱 / 电话 / 国家。

    流程：
      1. 浏览器 goto(url) —— 如果 url 是 Google 的加密跳转，
         Google 会 302，落地后 data['url'] 就是真实网站地址
      2. 解析首页：邮箱、电话、国家
      3. 首页没提取到（或国家没判出）且页面里有「联系我们」类链接时，
         再用浏览器多访问一步那个页面
    """
    data = _browser_page_data(url)
    if not data:
        logger.warning('【访问失败】%s' % url)
        return None
    info = parse_page(data, url)
    logger.info('    落地：%s' % (info.get('url') or url)[:100])
    logger.info('    首页：邮箱 %d 个 / 电话 %d 个 / 国家 %s'
                % (len(info['emails']), len(info['phones']),
                   info.get('country') or '未判出'))
    # 补看页同样用浏览器（保持全程不走接口）
    _follow_contact_pages(info, data, _browser_page_data, delay=0.5)
    return info


def visit_site(url):
    """访问单个网页：优先接口，失败再退回浏览器。"""
    if USE_HTTP_FIRST:
        info = visit_site_http(url)
        if info:
            return info
        if not HTTP_FALLBACK_TO_BROWSER:
            return None
        logger.info('    接口未取到，改用浏览器：%s' % url)
    return visit_site_browser(url)


def prefetch_http(links):
    """用接口逐个抓取第一层页面，返回 {url: info}（一次性收集完）。

    采集主流程已改用 prefetch_http_stream（边抓边回调、边落盘），
    这个函数保留给需要「先全部拿到再统一处理」的脚本用。
    """
    out = {}

    def collect(url, info):
        if info:
            out[url] = info

    prefetch_http_stream(links, on_result=collect)
    return out


def prefetch_http_stream(links, on_result=None):
    """用接口逐个抓取，**每完成一个就立刻回调**。

    串行执行（一次只抓一个网站），不用线程池：
      · 行为可预测，出问题能直接定位到是哪个 URL、哪一行
      · 不会因为多线程共享 requests / 日志 / 回调而出现难查的竞争问题
      · 复用同一个会话，更容易被目标站当成正常访客
    代价是比并行慢，但整体耗时主要花在 Google 搜索和浏览器阶段，影响有限。

    on_result(url, info)：
        info 为 None 表示这个站点接口没抓到，留给后面的浏览器阶段。

    只做 HTTP，不碰 Playwright。
    代理已在 configure_http_proxy() 里配置好，_http_session() 会自动带上。
    """
    if not (USE_HTTP_FIRST and requests is not None):
        return

    urls = [u for u, _t, _s in links]
    if not urls:
        return

    total = len(urls)
    logger.info('【接口】开始逐个抓取 %d 个网站（串行，代理：%s）'
                % (total, _HTTP_PROXY['http'] if _HTTP_PROXY else '不使用'))
    ok = 0
    for done, url in enumerate(urls, 1):
        if stop_requested():
            logger.warning('【接口】已停止，剩余 %d 个网站未抓取'
                           % (total - done + 1))
            break

        try:
            info = visit_site_http(url)
        except Exception as e:               # noqa: BLE001
            # 单个站点异常不能中断整批
            logger.info('    接口抓取异常 %s：%s' % (url, e))
            info = None
        if info:
            ok += 1

        # 一条一回调，立刻显示 / 落盘
        if on_result:
            on_result(url, info)

        if done % 10 == 0 or done == total:
            logger.info('【接口】进度 %d/%d，成功 %d' % (done, total, ok))

    logger.info('【接口】完成：%d/%d 个网站可用，其余交给浏览器阶段'
                % (ok, total))


def merge_by_domain(records):
    """同一域名的多条记录合并（一个网站可能被搜到多个页面）"""
    # 类型标注让静态检查知道值是 dict，避免 IDE 把 merged.get() 判成 Any | None
    merged: dict = {}
    for rec in records:
        try:
            domain = urlparse(rec['url']).netloc.lower().replace('www.', '')
        except (ValueError, TypeError, AttributeError):
            domain = rec['url']
        if not domain:
            continue
        # Google 结果页给出的站点名比页面标题更简洁，优先用它
        site_name = rec.get('serp_name') or rec['site_name']
        checked = list(rec.get('checked_pages') or [])

        if domain not in merged:
            merged[domain] = {
                'keyword': rec['keyword'],
                'site_name': site_name,
                'url': rec['url'],
                'country': rec.get('country') or '',
                'phones': list(rec['phones']),
                'emails': list(rec['emails']),
                'title': rec['title'],
                'checked_pages': checked,
                'serp_name': rec.get('serp_name') or '',
            }
            continue

        cur = merged[domain]          # 已确定存在，不再需要 None 判断
        for p in rec['phones']:
            if p not in cur['phones']:
                cur['phones'].append(p)
        for e in rec['emails']:
            if e not in cur['emails']:
                cur['emails'].append(e)
        # 国家：先判出来的为准，后面的不覆盖
        if not cur.get('country') and rec.get('country'):
            cur['country'] = rec['country']
        for c in checked:
            if c not in cur['checked_pages']:
                cur['checked_pages'].append(c)
        # 有 serp_name 就用它覆盖（Google 的站点名更准）
        if rec.get('serp_name'):
            cur['serp_name'] = rec['serp_name']
            cur['site_name'] = rec['serp_name']
        if len(rec['title']) > len(cur['title']):
            cur['title'] = rec['title']
            if not cur['serp_name']:
                cur['site_name'] = rec['site_name']
    return list(merged.values())


# ==================== xlsx ====================
# 列顺序即写入顺序，「来源」固定在最后一列。
# 中间几列的顺序是用户明确要求过的（国家紧跟关键词），插列容易打乱，
# 所以新增字段一律追加到末尾。
HEADERS = ['关键词', '国家', '网站名称', '网站链接', '邮箱', '电话', '来源']

# 上一版的 6 列格式（还没有「来源」列），读取时自动补列
PREV7_HEADERS = ['关键词', '国家', '网站名称', '网站链接', '邮箱', '电话']

# 更早的 6 列格式（「国家」在第 4 列），读取时把它挪到关键词后面
PREV6_HEADERS = ['关键词', '网站名称', '网站链接', '国家', '邮箱', '电话']

# 上一版的 5 列格式（没有国家列），读取时自动插列迁移
PREV_HEADERS = ['关键词', '网站名称', '网站链接', '邮箱', '电话']

# 旧版本的 5 列格式（电话在前、邮箱在后），读取时自动迁移到新列顺序
LEGACY_HEADERS = ['关键词', '网站名称', '网站地址', '电话', '邮箱']

HEADER_FONT = Font(name='微软雅黑', size=11, bold=True, color='FFFFFF')
HEADER_FILL = PatternFill(start_color='4472C4', end_color='4472C4',
                          fill_type='solid')

# 写入前对「电话 / 邮箱」两列做最终校验：
# 只保留真正的电话号码 / 邮箱地址，挡住日志文本、URL、页面杂项混进来。
RE_EMAIL_STRICT = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}$')
RE_PHONE_STRICT = re.compile(r'^[+(]?\d[\d\s\-+()]{5,24}$')

# openpyxl 不接受 XML 非法控制字符（0x00-0x08、0x0B、0x0C、0x0E-0x1F），
# 页面标题里偶尔会混进这类字符，直接写入会抛 IllegalCharacterError
# 把整条记录（乃至整批采集）搞崩。
RE_XLSX_ILLEGAL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def clean_cell(value):
    """清洗一个单元格的值：去掉 XML 非法控制字符，None 转空串。"""
    if value is None:
        return ''
    s = str(value)
    return RE_XLSX_ILLEGAL.sub('', s)


# ==================== 来源（google / facebook） ====================
# 结果表的「来源」列只有这两个取值。老数据（还没有这一列时写的）没有记录过，
# 迁移时按链接域名推断：facebook.com → facebook，其余视为 google。
SOURCE_GOOGLE = 'google'
SOURCE_FACEBOOK = 'facebook'
SOURCE_UNKNOWN = '未知'

# 判定「这是 Facebook 链接」的域名
FACEBOOK_HOSTS = ('facebook.com', 'fb.com', 'm.facebook.com',
                  'web.facebook.com')


def infer_source(url):
    """按链接域名推断来源；没有链接时返回「未知」。"""
    domain = site_domain(url or '')
    if not domain:
        return SOURCE_UNKNOWN
    if domain in FACEBOOK_HOSTS:
        return SOURCE_FACEBOOK
    return SOURCE_GOOGLE


def source_cell(rec):
    """「来源」列：google / facebook。

    rec 里优先读 'origin'（采集模块自己写进去的，最准）；
    没有就按链接推断 —— 兼容老数据和外部脚本手工拼的记录。
    """
    raw = str(rec.get('origin') or '').strip().lower()
    if raw in (SOURCE_GOOGLE, SOURCE_FACEBOOK):
        return raw
    if 'facebook' in raw:
        return SOURCE_FACEBOOK
    if 'google' in raw:
        return SOURCE_GOOGLE
    return infer_source(rec.get('url'))


def country_cell(rec):
    """「国家」列：判断不出来写「未知」。

    不用「暂无匹配数据」是为了区分两种情况：
    未知 = 页面上看不出来；暂无匹配数据 = 这一列本来就没抓到东西。
    """
    return clean_cell((rec.get('country') or '').strip() or UNKNOWN_COUNTRY)


def safe_phone_cell(values):
    """把电话列表拼成单元格文本，过滤掉不是电话的内容"""
    out = []
    for v in values or []:
        s = str(v or '').strip()
        if not s:
            continue
        # 必须只由数字/空格/-/+/括号组成，且数字个数合理
        if not RE_PHONE_STRICT.match(s):
            continue
        digits = re.sub(r'\D', '', s)
        if not (7 <= len(digits) <= 16):
            continue
        if s not in out:
            out.append(s)
    return '; '.join(out)


def safe_email_cell(values):
    """把邮箱列表拼成单元格文本，过滤掉不是邮箱的内容"""
    out = []
    for v in values or []:
        s = str(v or '').strip().strip('.,;:<>()[]{}"\'')
        if not s:
            continue
        if not s.isascii():
            continue
        if not RE_EMAIL_STRICT.match(s):
            continue
        if s not in out:
            out.append(s)
    return '; '.join(out)


def email_cell(rec):
    """「邮箱」列：有邮箱写邮箱（多个用 ; 分隔），没有则写暂无匹配数据。"""
    return safe_email_cell(rec.get('emails')) or NO_DATA_TEXT


def phone_cell(rec):
    """「电话」列：有电话写电话（多个用 ; 分隔），没有则写暂无匹配数据。"""
    return safe_phone_cell(rec.get('phones')) or NO_DATA_TEXT


def _save_workbook(wb, path):
    """保存工作簿；目标被 Excel / WPS 占用时改用「临时文件 + 原子替换」。

    Windows 上文件被 Excel 打开后仍允许 os.replace 覆盖它，
    所以这样能避免「迁移只发生在内存里、磁盘上还是旧列序」的坑。
    返回 True 表示内容已经写到 path。
    """
    try:
        wb.save(path)
        return True
    except PermissionError:
        pass

    tmp = '%s.tmp%s.xlsx' % (os.path.splitext(path)[0],
                             time.strftime('%H%M%S'))
    try:
        wb.save(tmp)
        os.replace(tmp, path)
        return True
    except OSError as e:
        logger.warning('%s 暂时无法写入（%s），稍后保存'
                       % (os.path.basename(path), e))
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def _write_header_row(ws):
    """把 HEADERS 写到第 1 行（带样式）。迁移和新建表都用它。"""
    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')


def _fill_missing(ws, col, value):
    """把某一列里空着的单元格填上默认值（迁移老数据用）。"""
    for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
        for cell in row:
            if not cell.value:
                cell.value = value


def open_workbook(path):
    """打开或新建结果表，返回 (wb, ws, 已存在的数据键集合)。

    迁移策略：所有旧格式都先「归一到上一版 6 列」，再统一补「来源」列，
    这样新增字段时只需要在末尾加一段，不用动前面几段。

    · 表头与当前 HEADERS 一致：直接复用。
    · 上一版 6 列（还没有「来源」）：末尾补「来源」，按链接推断 google/facebook。
    · 更早的 6 列（国家在第 4 列）：把国家挪到关键词后面，再补「来源」。
    · 上一版 5 列（没有国家列）：插入「国家」列，再补「来源」。
    · 更早的 5 列（电话/邮箱顺序不同）：原地换序 + 插国家，再补「来源」。
    · 其他结构：备份旧文件后重建，避免列错位。
    """
    if os.path.exists(path):
        try:
            wb = load_workbook(path)
            ws = wb.active
            # 取完整表头（去掉尾部空单元格）再和 HEADERS 比较
            raw_headers = [str(c.value or '').strip() for c in ws[1]]
            while raw_headers and raw_headers[-1] == '':
                raw_headers.pop()

            changed = False

            # ---------- ① 更早的 6 列：国家在第 4 列 ----------
            if raw_headers == PREV6_HEADERS:
                # 先整行取值再写回，避免覆盖过程中互相踩数据
                for r in range(2, ws.max_row + 1):
                    vals = [ws.cell(row=r, column=c).value for c in range(1, 7)]
                    order = [vals[0], vals[3], vals[1], vals[2],
                             vals[4], vals[5]]
                    for c, v in enumerate(order, 1):
                        ws.cell(row=r, column=c, value=v)
                raw_headers = PREV7_HEADERS
                changed = True
                logger.info('结果表列顺序已调整：国家前移到关键词后面')

            # ---------- ② 上一版 5 列：没有国家列 ----------
            if raw_headers == PREV_HEADERS:
                ws.insert_cols(2)
                # 老数据没有国家信息，填「未知」而不是留空
                _fill_missing(ws, 2, UNKNOWN_COUNTRY)
                raw_headers = PREV7_HEADERS
                changed = True
                logger.info('结果表已补上「国家」列')

            # ---------- ③ 更早的 5 列：电话/邮箱顺序不同 ----------
            if raw_headers == LEGACY_HEADERS:
                # 旧: 关键词 | 网站名称 | 网站地址 | 电话 | 邮箱
                for row in ws.iter_rows(min_row=2):
                    row[3].value, row[4].value = row[4].value, row[3].value
                ws.insert_cols(2)
                _fill_missing(ws, 2, UNKNOWN_COUNTRY)
                raw_headers = PREV7_HEADERS
                changed = True
                logger.info('旧结果表已迁移列顺序')

            # ---------- ④ 上一版 6 列：末尾补「来源」 ----------
            if raw_headers == PREV7_HEADERS:
                url_col = PREV7_HEADERS.index('网站链接') + 1
                src_col = len(PREV7_HEADERS) + 1     # 追加在最后一列
                for r in range(2, ws.max_row + 1):
                    url = ws.cell(row=r, column=url_col).value
                    if not ws.cell(row=r, column=src_col).value:
                        ws.cell(row=r, column=src_col,
                                value=infer_source(str(url or '')))
                raw_headers = HEADERS
                changed = True
                logger.info('结果表已补上「来源」列（老数据按链接推断）')

            # ---------- 统一落盘一次 ----------
            if changed:
                _write_header_row(ws)
                _save_workbook(wb, path)
                logger.info('结果表结构：%s' % '/'.join(HEADERS))

            if raw_headers == HEADERS:
                # 列位置从 HEADERS 推导，改列顺序时这里不用跟着改
                kw_idx = HEADERS.index('关键词')
                url_idx = HEADERS.index('网站链接')
                existing = set()
                width = max(kw_idx, url_idx) + 1
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if row and len(row) >= width and row[url_idx]:
                        existing.add((str(row[kw_idx] or ''),
                                      normalize_url(str(row[url_idx]))))
                return wb, ws, existing

            # 表头不匹配：备份旧文件，重新建表
            backup = '%s.bak.%s.xlsx' % (os.path.splitext(path)[0],
                                         time.strftime('%Y%m%d%H%M%S'))
            try:
                wb.close()
            except OSError:
                pass
            os.replace(path, backup)
            logger.warning('已有结果表列结构不匹配（%s），已备份为 %s，将新建空表'
                           % ('/'.join(raw_headers) or '空',
                              os.path.basename(backup)))
        except (OSError, ValueError, KeyError, TypeError) as e:
            # 文件损坏 / 不是 xlsx / 表头异常等：退回新建
            logger.warning('读取已有结果表失败（%s），将新建：%s' % (path, e))

    wb = Workbook()
    ws = wb.active
    ws.title = '联系方式'
    ws.freeze_panes = 'A2'
    _write_header_row(ws)
    wb.save(path)
    return wb, ws, set()


def save_records(wb, ws, path, records):
    """追加记录并立即保存（逐条落盘，中断不丢）"""
    for rec in records:
        ws.append([
            clean_cell(rec.get('keyword')),
            country_cell(rec),    # 判断不出国家时写「未知」
            clean_cell(rec.get('site_name')),
            clean_cell(rec.get('url')),
            email_cell(rec),      # 无邮箱时写「暂无匹配数据」
            phone_cell(rec),      # 无电话时写「暂无匹配数据」
            source_cell(rec),     # google / facebook
        ])
    try:
        wb.save(path)
        logger.info('已保存 %d 条记录到 %s' % (len(records),
                                              os.path.basename(path)))
    except PermissionError:
        fallback = os.path.splitext(path)[0] + '_%s.xlsx' % time.strftime('%H%M%S')
        wb.save(fallback)
        logger.warning('%s 被占用（请关闭 Excel），本次改写入 %s'
                       % (os.path.basename(path), os.path.basename(fallback)))


# ==================== 主流程 ====================
# 现在每采到一条就立刻落盘（见 crawl 里的 emit），不再攒批，
# FLUSH_EVERY 只保留给外部脚本参考，采集流程已不使用。
FLUSH_EVERY = 10


def crawl(keyword, proxy=None, max_pages=MAX_SERP_PAGES,
          max_sites=MAX_SITES, out_file=None, per_page=NUM_PER_PAGE,
          browser_fallback=True):
    """采集单个关键词：搜索 -> 用浏览器逐个访问 href -> 写 xlsx（边采边存）

    搜索阶段拿到的 href 可能是 Google 的加密跳转（/goto?url=<加密串>），
    解不出真实地址 —— 直接把 href 交给浏览器访问，Google 会 302 到目标站，
    落地后的 page.url 就是真实地址（比 cite 更完整，连路径都有）。

    所以「真实域名去重 / 是否该跳过」都放在访问落地之后做。
    """
    out_file = out_file or os.path.join(BASE_DIR, OUT_NAME)

    # 输出目录可能不存在（--out 指定了子目录），先建好再写表
    out_dir = os.path.dirname(os.path.abspath(out_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # requests 与浏览器使用同一个代理设置（无代理时忽略系统代理环境变量）
    configure_http_proxy(proxy)

    # 先把结果表准备好：即使一条都没采到，也留下带表头的文件，
    # 方便确认输出位置（否则 0 条时直接 return，连文件都不会生成）
    wb, ws, existing = open_workbook(out_file)
    logger.info('结果表：%s' % out_file)

    links = google_search(keyword, max_pages=max_pages, proxy=proxy,
                          per_page=per_page)
    if not links:
        logger.warning('关键词「%s」没有拿到任何搜索结果' % keyword)
        logger.warning('结果表已就绪（暂无数据）：%s' % out_file)
        return 0

    # ==================================================================
    # 阶段一结束：搜索已全部翻完（页面提取「网站名称 + href」）
    # 阶段二开始：逐个访问这些链接，爬取邮箱 / 电话 / 国家
    # ==================================================================
    total_extracted = len(links)
    logger.info('【阶段一完成】关键词「%s」共提取 %d 个链接'
                '（已翻 %d 页）' % (keyword, total_extracted, max_pages))
    logger.info('【阶段二开始】开始逐个访问网站，提取邮箱 / 电话 / 国家')

    # 表格里已有的链接不再访问。
    # 注意：搜索给的 href 可能是 Google 跳转链接（/goto?url=<加密串>），
    # 和 xlsx 里存的真实地址对不上，所以这里只能按「能解出来的」链接先比一次；
    # 解不出来的留到落地后再按真实域名去重（见下面的 visited_domains）。
    skipped_existing = []
    if SKIP_EXISTING_LINKS:
        existing_keys = set(link_key(url) for _kw, url in existing)
        before = len(links)
        kept = []
        for item in links:
            resolved = resolve_result_url(item[0], item[2] if len(item) > 2
                                          else '')
            if not is_google_link(resolved) and \
                    link_key(resolved) in existing_keys:
                skipped_existing.append(item)
            else:
                kept.append(item)
        links = kept
        skipped = before - len(links)
        if skipped:
            logger.info('已跳过 %d 个结果表中已存在的链接' % skipped)
        if not links:
            logger.info('关键词「%s」的链接都已在结果表中，无需重复爬取'
                        % keyword)
            return 0

    # 被跳过的链接也要在表格里标成「已完成」，
    # 否则它们会永远停在「待采集」，看起来像卡住了。
    for url, title, site_name in skipped_existing:
        report_record({
            'keyword': keyword, 'url': url, 'title': title or '',
            'site_name': site_name or '', 'emails': [], 'phones': [],
            'source': 'skip', 'written': False,
        })

    links = links[:max_sites]
    logger.info('实际访问 %d 个网页' % len(links))

    # ---------------- 结果落盘：一条一写，实时进表格 ----------------
    # 不再攒批（原来是每 FLUSH_EVERY 条才写一次），采到一条就立刻写进 xlsx
    # 并推给界面，用户能实时看到成果；中断最多只丢正在处理的那一条。
    written_keys = set()
    written_domains = set()
    saved = 0
    skipped_no_contact = []

    def emit(info, url, title, site_name, source):
        """写一条结果：立即落盘 + 立即刷界面。

        source: 'http'=接口拿到 / 'browser'=浏览器拿到
        返回 True 表示已写入表格。
        """
        nonlocal saved
        info['keyword'] = keyword
        info['origin'] = SOURCE_GOOGLE        # 结果表「来源」列
        if site_name:
            info['serp_name'] = site_name

        emails = list(info.get('emails') or [])
        phones = list(info.get('phones') or [])
        has_contact = bool(emails or phones)

        # 写进表格的链接是「重定向后的最终 URL」（如 https://a.com/ 而不是
        # 搜索页给的 https://a.com），去重键必须用同一个值 ——
        # 否则下次运行从 xlsx 读出来的键永远匹配不上，同一站点会被重复采集。
        final_url = (info.get('url') or url or '').strip() or url
        domain = site_domain(final_url)
        written = False

        # 只要访问过就写入（WRITE_NO_CONTACT=True）：
        # 没采到的列写「暂无匹配数据」/「未知」，表就是完整的访问清单。
        # 关掉这个开关时才按「有无联系方式」过滤。
        skip = (not WRITE_NO_CONTACT and not has_contact)
        if skip:
            if url not in skipped_no_contact:
                skipped_no_contact.append(url)
            logger.info('    跳过（未采到电话/邮箱）')
        else:
            key = (keyword, normalize_url(final_url))
            dup = (key in existing or key in written_keys
                   or (domain and domain in written_domains))
            if not dup:
                save_records(wb, ws, out_file, [info])
                written_keys.add(key)
                if domain:
                    written_domains.add(domain)
                saved += 1
                written = True
            else:
                logger.info('    跳过（结果表里已有这个链接）')

        # 界面始终显示这条（即使没写进 xlsx，用户也该看到采过了）。
        # 这里用搜索链接 url：它和报告链接时的键一致，界面才能原地更新那一行。
        report_record({
            'keyword': keyword,
            'url': url,
            'title': title or '',
            'site_name': site_name or '',
            'country': (info.get('country') or ''),
            'emails': emails,
            'phones': phones,
            'source': source,          # 界面用它显示「接口 / 浏览器」
            'origin': SOURCE_GOOGLE,   # 界面用它区分采集源
            'written': written,
        })
        return written

    # ==================================================================
    # 用浏览器逐个访问 href
    #   href 可能就是 Google 的加密跳转（/goto?url=<加密串>），
    #   浏览器 goto 后 Google 会 302 到目标站，落地地址就是真实网站。
    #   所以「是否跳过 / 按域名去重」都在落地之后按最终 URL 判断。
    # ==================================================================
    if not browser_fallback:
        logger.warning('浏览器已关闭（仅接口模式）：加密跳转链接无法访问，'
                       '本次只能处理直链')

    total = len(links)
    visited_domains = set()
    for idx, (href, title, site_name) in enumerate(links, 1):
        if stop_requested():
            logger.warning('已停止，剩余 %d 个网站未访问' % (total - idx + 1))
            break

        logger.info('[%d/%d] %s' % (idx, total, href))
        logger.info('    ── 开始处理这一条（首页 → 必要时联系页 → 写表）──')
        report_progress('sites', idx, total,
                        '访问第 %d/%d 个' % (idx, total))

        if not browser_fallback:
            continue

        # 单个站点出任何问题都只跳过它自己，不能打断整批。
        # 这里用 Exception：页面失效时抛的是 AttributeError 之类的杂项异常，
        # 不在 BROWSER_ERRORS 里，漏掉就会一路抛到顶层。
        #
        # 注意：visit_site_browser 内部是「首页 → 补看联系页」的完整流程，
        # 它会一直做完才返回，所以下面写表时这一条已经彻底处理完了，
        # 真正做到了「一条走完流程再走下一条」。
        info = None
        try:
            if browser_fallback:
                # 浏览器访问：能跟随 Google 的加密跳转，JS 站点也能取到
                info = visit_site_browser(href)
            elif not is_google_link(href):
                # 仅接口模式：只能处理能直接解析出目标地址的直链
                info = visit_site_http(href)
            else:
                logger.info('    跳过（仅接口模式无法解析加密跳转链接）')
        except Exception as e:                # noqa: BLE001
            import traceback
            logger.error('访问异常 %s：%s' % (href, e))
            logger.info(traceback.format_exc()[:1200])
            if not _page_alive():
                logger.warning('检测到浏览器已失效，重置后继续')
                try:
                    reset_browser()
                except Exception:             # noqa: BLE001
                    pass

        if info is None:
            logger.info('    跳过（页面没打开）')
            continue

        # 落地后才知道真实地址（浏览器已跟随 Google 的跳转）
        final_url = (info.get('url') or '').strip()
        if not final_url.startswith('http'):
            logger.info('    跳过（没有拿到有效地址）')
            continue
        if is_google_link(final_url):
            logger.info('    跳过（仍停在 Google，跳转没成功）')
            continue
        if not is_acceptable(final_url):
            logger.info('    跳过（域名被过滤）：%s' % final_url[:80])
            continue

        domain = site_domain(final_url)
        if ONE_RESULT_PER_DOMAIN and domain and domain in visited_domains:
            logger.info('    跳过（同一站点已访问过）：%s' % domain)
            continue
        if domain:
            visited_domains.add(domain)

        try:
            emit(info, href, title, site_name, 'browser')
            found = []
            if info.get('phones'):
                found.append('电话 %d 个' % len(info['phones']))
            if info.get('emails'):
                found.append('邮箱 %d 个' % len(info['emails']))
            if info.get('country'):
                found.append('国家 %s' % info['country'])
            logger.info('    汇总：%s'
                        % ('、'.join(found) if found else '无联系方式'))
        except Exception as e:                # noqa: BLE001
            logger.error('写入结果失败 %s：%s' % (final_url, e))

        if idx < total:
            time.sleep(random.uniform(*PAGE_DELAY))

    # 收尾：把「没采到联系方式所以没写入」的网站列出来，避免误以为漏写
    if skipped_no_contact:
        logger.info('以下 %d 个网站因未采到电话/邮箱，未写入结果表：'
                    % len(skipped_no_contact))
        for u in skipped_no_contact[:20]:
            logger.info('    %s' % u)
        if len(skipped_no_contact) > 20:
            logger.info('    ...（共 %d 个）' % len(skipped_no_contact))

    logger.info('关键词「%s」本次新增 %d 条记录（提取链接 %d 个 / 访问站点 %d 个）'
                % (keyword, saved, total_extracted, len(visited_domains)))
    report_progress('keyword_done', saved, saved,
                    '关键词完成，新增 %d 条' % saved)
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Google 关键词采集：搜索关键词并爬取网站的电话 / 邮箱')
    parser.add_argument('-k', '--keywords',
                        help='关键词，多个用逗号分隔（不传则交互式输入）')
    parser.add_argument('-p', '--proxy',
                        help='代理地址，如 127.0.0.1:7892'
                             '（不传则交互式输入；配合 -k 时不使用代理）')
    parser.add_argument('--no-proxy', action='store_true',
                        help='不使用代理（非交互运行时配合 -k 使用）')
    parser.add_argument('--pages', type=int, default=None,
                        help='Google 最多翻几页（默认 %d）' % MAX_SERP_PAGES)
    parser.add_argument('--max-sites', type=int, default=None,
                        help='最多访问多少个网页（默认 %d）' % MAX_SITES)
    parser.add_argument('-o', '--out', default=None,
                        help='结果文件路径（默认 %s）' % OUT_NAME)
    parser.add_argument('--cli', action='store_true',
                        help='兼容参数（本文件本来就是命令行模式，加不加效果一样）')
    args = parser.parse_args(argv)

    print('=' * 60)
    print(' Google 关键词采集 —— 提取电话 / 邮箱 / 网站名称')
    print('=' * 60)
    print('提示：Google 需要代理，直接回车表示不使用代理。')

    keyword = (args.keywords or
               input('请输入关键词（多个用英文逗号分隔）：')).strip()
    if not keyword:
        print('关键词不能为空')
        return 1

    # 传了 --keywords 视为非交互（批量）模式，缺失的参数直接用默认值，
    # 避免定时任务因为没有标准输入卡在 input() 上。
    batch = bool(args.keywords)

    if args.no_proxy:
        proxy = None
    elif args.proxy:
        proxy = {'server': 'http://%s' % args.proxy.strip()}
    elif batch:
        proxy = None
    else:
        proxy_input = input('请输入代理（如 127.0.0.1:7892，回车跳过）：').strip()
        proxy = {'server': 'http://%s' % proxy_input} if proxy_input else None

    if args.pages and args.pages > 0:
        max_pages = args.pages
    elif batch:
        max_pages = MAX_SERP_PAGES
    else:
        pages_input = input('Google 搜索翻几页（默认 %d，回车使用默认）：'
                            % MAX_SERP_PAGES).strip()
        max_pages = (int(pages_input) if pages_input.isdigit()
                     else MAX_SERP_PAGES)

    if args.max_sites and args.max_sites > 0:
        max_sites = args.max_sites
    elif batch:
        max_sites = MAX_SITES
    else:
        sites_input = input('最多访问多少个网页（默认 %d，回车使用默认）：'
                            % MAX_SITES).strip()
        max_sites = int(sites_input) if sites_input.isdigit() else MAX_SITES

    out_file = (os.path.abspath(args.out) if args.out
                else os.path.join(BASE_DIR, OUT_NAME))

    keywords = [k.strip() for k in re.split(r'[,，]', keyword) if k.strip()]

    total = 0
    for kw in keywords:
        logger.info('=' * 50)
        logger.info('开始采集关键词：%s' % kw)
        try:
            total += crawl(kw, proxy=proxy, max_pages=max_pages,
                           max_sites=max_sites, out_file=out_file)
        except BROWSER_ERRORS as e:
            # 一个关键词失败不影响后续关键词
            logger.error('关键词「%s」采集失败：%s' % (kw, e))
        time.sleep(random.uniform(*SERP_DELAY))

    logger.info('=' * 50)
    logger.info('全部完成，本次新增 %d 条记录，文件：%s' % (total, out_file))
    print('\n完成，结果文件：%s' % out_file)
    return 0


if __name__ == '__main__':
    # 本文件是采集库：命令行直接跑就是 Google 采集。
    # 图形界面（可切 Google / Facebook）请运行 run.py。
    try:
        sys.exit(main())
    finally:
        try:
            PlayWright.close()
        except BROWSER_ERRORS:
            pass
