# coding='utf-8'
"""Google 关键词采集：搜索关键词 -> 抓取前 N 页搜索结果 -> 逐个访问网页 -> 提取联系方式

输出字段：关键词、网站名称、网站链接、邮箱、电话
    · 首页缺电话或邮箱时，会自动补看「联系我们 / 关于我们」页面；
      补看页同样用接口抓取（必要时用浏览器再分析），
      若仍然没有数据，对应单元格写「暂无匹配数据」，不再输出补看链接。

用法：
    python keyword_get_email.py
    python keyword_get_email.py -k "灯具厂家,LED供应商" -p 127.0.0.1:7892
    python keyword_get_email.py -k "灯饰" --no-proxy --pages 5 --max-sites 30 -o out.xlsx

流程：
    1. 用 Google 搜索关键词，翻 MAX_SERP_PAGES 页（默认 10 页）
    2. 收集结果链接（跳过 Google 自家、社交平台、文件类链接）
       注意 Google 结果页的 href 现在是 /goto?url=<protobuf 加密串>，解不出目标地址，
       必须用每条结果下方 <cite> 里显示的真实域名来还原（见 resolve_result_url），
       老格式 /url?q=<目标> 也能自动还原
    3. 优先用 requests 接口并发抓取网页（快）；JS 渲染 / 反爬站点
       再用浏览器兜底（见 USE_HTTP_FIRST / HTTP_MAX_WORKERS），
       从 tel:/mailto: 链接、JSON-LD、页面正文里提取电话 / 邮箱 / 公司名
    4. 首页缺电话或邮箱时，自动再打开「联系我们 / 关于我们」页补抓（见 VISIT_CONTACT_PAGE）
    5. 同一域名合并成一条记录，写成 xlsx（每条落盘，中断不丢）

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
import threading
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape as html_unescape
from urllib.parse import urlparse, urljoin, quote_plus, parse_qs, unquote

try:
    import requests
except ImportError:                       # 没装 requests 时退回纯浏览器模式
    requests = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 用 BASE_DIR 推出项目根目录：直接运行脚本时 __file__ 可能是相对路径，
# Path(__file__).parent.parent 会指到当前目录，导致找不到 newPlayWright。
sys.path.append(os.path.dirname(BASE_DIR))

from newPlayWright import PlayWright, logger

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

# 浏览器操作可能抛出的异常：Playwright 自己的 Error、超时，以及页面被关闭 /
# 导航中断等引起的 OSError / RuntimeError。收敛成元组，避免到处写
# except Exception 把真正的代码错误也吞掉。
try:
    from playwright.sync_api import Error as _BrowserError
except ImportError:                       # 兼容只装了 patchright 的环境
    try:
        from patchright.sync_api import Error as _BrowserError
    except ImportError:
        _BrowserError = OSError

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
OUT_NAME = 'google_contacts.xlsx'

# 首页电话/邮箱任一项缺失时，是否再打开「联系我们 / 关于我们」页面补抓
# 很多企业官网只在联系页留联系方式，这一步能明显提高命中率
VISIT_CONTACT_PAGE = True
CONTACT_PAGE_LIMIT = 2       # 每个网站最多补看几个联系页（别设太大，会变慢）

# 既没有电话、也没有邮箱、还没补看过联系页的网站，是否也写入结果表
#   False（默认）：不写入，日志会列出跳过了哪些站点
#   True         ：写进表格（邮箱/电话列显示「暂无匹配数据」），适合要全量清单时用
# 注意：补看过联系页的站点无论有没有联系方式都会写入。
WRITE_NO_CONTACT = False

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
HTTP_MAX_WORKERS = 8              # 并发抓取的网站数（1 = 串行）
HTTP_VERIFY_SSL = False           # 部分企业站证书异常，默认不校验

# 最终没有采集到数据时，单元格显示的文字
NO_DATA_TEXT = '暂无匹配数据'

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

# 不做联系信息采集的域名（社交平台、聚合站、Google 自家）
SKIP_DOMAINS = (
    'google.com', 'googleusercontent.com', 'gstatic.com', 'youtube.com',
    'facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'linkedin.com',
    'pinterest.com', 'tiktok.com', 'wikipedia.org', 'wikimedia.org',
    'amazon.com', 'ebay.com', 'alibaba.com', 'aliexpress.com',
    'zhihu.com', 'weibo.com', 'baidu.com', 'bilibili.com', 'douyin.com',
    'quora.com', 'reddit.com', 'medium.com', 'blogspot.com', 'wordpress.com',
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

    return clean_emails(emails), clean_phones(phones)


# ---------- 网站名称 ----------
def pick_site_name(meta, title, url):
    """网站名称：优先 og:site_name，其次 <title> 去掉常见后缀，最后用域名"""
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
    if not name:
        name = urlparse(url).netloc.replace('www.', '')
    return name.strip()


def jsonld_contacts(ld_blocks):
    """从 JSON-LD 结构化数据里取公司名 / 电话 / 邮箱（最准）"""
    names, phones, emails = [], [], []

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
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in ld_blocks or []:
        try:
            walk(json.loads(block))
        except (ValueError, TypeError):
            continue
    return names, phones, emails


# ==================== 浏览器操作 ====================
# 访问网页时拦截图片/视频/字体等无关资源，只保留 HTML/CSS/JS，明显加快加载
BLOCK_HEAVY_RESOURCES = True
BLOCKED_RESOURCE_TYPES = ('image', 'media', 'font')
_RESOURCE_STATE = {'installed': False}


def ensure_browser(proxy=None):
    """确保浏览器已启动（兼容 newPlayWright / PatchRight 两种类）。"""
    if getattr(PlayWright, 'playwright', None):
        return True
    starter = (getattr(PlayWright, 'start_borwser', None)
               or getattr(PlayWright, 'start_browser', None))
    if starter is None:
        return False
    try:
        if proxy is not None:
            starter(proxy)
        else:
            starter()
        return True
    except BROWSER_ERRORS as e:
        logger.error('启动浏览器失败：%s' % e)
        return False


def _block_route(route):
    """Playwright 路由回调：拦截非必要资源，其余放行。"""
    try:
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()
    except BROWSER_ERRORS:
        try:
            route.continue_()
        except BROWSER_ERRORS:
            pass


def setup_resource_blocking():
    """给当前 context 挂上资源拦截（只挂一次）。"""
    if not BLOCK_HEAVY_RESOURCES or _RESOURCE_STATE['installed']:
        return
    context = getattr(PlayWright, 'context', None)
    if context is None:
        return
    try:
        context.route('**/*', _block_route)
        _RESOURCE_STATE['installed'] = True
        logger.info('已启用资源拦截：%s' % '/'.join(BLOCKED_RESOURCE_TYPES))
    except BROWSER_ERRORS as e:
        logger.info('启用资源拦截失败：%s' % e)


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


def goto_fast(url, retry=2):
    """打开网页（不带 PlayWright.goto 里固定的 5 秒等待）。

    批量访问几十上百个网站时，每页固定多等 5 秒会白耗好几分钟，
    这里直接用 page.goto，自己控制等待时长。
    """
    if not ensure_browser():
        return False
    setup_resource_blocking()
    for _ in range(retry):
        try:
            PlayWright.page.goto(url, timeout=PAGE_TIMEOUT,
                                 wait_until='domcontentloaded')
            time.sleep(random.uniform(0.8, 1.8))     # 给动态内容一点渲染时间
            return True
        except BROWSER_ERRORS as e:
            logger.info('%s 打开失败：%s' % (url, e))
            time.sleep(1.5)
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
    try:
        text = PlayWright.page.inner_text('body')[:3000]
    except BROWSER_ERRORS:
        return False
    markers = ('unusual traffic', 'not a robot', 'recaptcha',
               'detected unusual', '流量异常', '不是机器人', '安全验证')
    low = text.lower()
    if any(m in low for m in markers):
        return True
    return False


def wait_if_blocked():
    """被拦时提示用户手动处理，最多等 3 分钟"""
    if not check_blocked():
        return True
    logger.warning('检测到 Google 人机验证，请在浏览器窗口内手动完成……')
    for i in range(180):
        time.sleep(1)
        if not check_blocked():
            logger.info('验证已通过，继续采集')
            return True
    logger.error('等待验证超时，跳过当前步骤')
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
            let p = a.parentElement;
            for (let i = 0; i < 4 && p && !cite; i++) {
                cite = p.querySelector('cite');
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


def extract_serp_links():
    """从当前 Google 结果页取出自然搜索结果 [(title, href, cite, site_name), ...]

    优先用页面内 JS 一次取全（能拿到 cite 和站点名）；失败时退回 XPath 方式。
    XPath 兜底会按 Google 站点信息块的结构取名称与地址。
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

    # 兜底：按 XPath 取「站点信息块」里的名称与地址，再与标题按顺序配对
    name_xp = ('//div[contains(@class, "notranslate")]'
               '/div/div/div[1]/span')
    cite_xp = ('//div[contains(@class, "notranslate")]'
               '/div/div/div[2]/cite')
    anchor_xp = '//div[@id="rso"]//a[.//h3]'

    def all_text(xpath):
        vals = []
        for i in range(1, PlayWright.get_count(xpath) + 1):
            try:
                vals.append((PlayWright.get_text('(%s)[%d]' % (xpath, i))
                             or '').strip())
            except BROWSER_ERRORS:
                vals.append('')
        return vals

    names = all_text(name_xp)
    cites = all_text(cite_xp)

    for i in range(1, PlayWright.get_count(anchor_xp) + 1):
        try:
            href = PlayWright.get_attribute('(%s)[%d]' % (anchor_xp, i), 'href')
            title = safe_text('(%s)[%d]//h3' % (anchor_xp, i))
        except BROWSER_ERRORS:
            continue
        if not href:
            continue
        idx = i - 1
        cite = cites[idx] if idx < len(cites) else ''
        name = names[idx] if idx < len(names) else ''
        out.append((title, href, cite, name))
    return out


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
    """把一条搜索结果的链接还原成目标网站地址。

    优先级：
      1. <cite> 显示的真实域名（Google 现在最可靠、最直接把地址摆出来的地方）
      2. /url?q=<目标> 这种老式跳转链接（可以解出）
      3. 本身就是目标站直链
    /goto?url=<加密串> 无法解码，只能靠 cite。
    """
    from_cite = url_from_cite(cite)
    if from_cite:
        return from_cite
    return unwrap_google_url(href)


def google_search(keyword, max_pages=MAX_SERP_PAGES, proxy=None):
    """搜索关键词，返回 [(url, title, site_name), ...]（已去重、已过滤）"""
    results = []
    seen = set()
    seen_domains = set()

    # 先启动浏览器并挂上资源拦截，第一页搜索也能享受加速
    if not ensure_browser(proxy):
        logger.error('【搜索】浏览器启动失败')
        return results
    setup_resource_blocking()

    for page in range(max_pages):
        start = page * 10
        url = ('https://www.google.com/search?q=%s&start=%d&hl=en&num=10'
               % (quote_plus(keyword), start))
        logger.info('【搜索】第 %d/%d 页：%s' % (page + 1, max_pages, keyword))

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

        # 提取自然搜索结果：每条 = (标题, href, cite, 网站名称)
        links = extract_serp_links()

        logger.info('【搜索】第 %d 页解析到 %d 个链接' % (page + 1, len(links)))

        added = 0
        rejects = []
        for title, href, cite, site_name in links:
            raw = (href or '').strip()
            # Google 的 href 是 /goto?url=<加密串>，只能靠 <cite> 里的真实域名还原
            href = resolve_result_url(raw, cite)
            if not href.startswith('http'):
                rejects.append(('非 http 链接', '%s | cite=%s' % (raw, cite)))
                continue
            if not is_acceptable(href):
                rejects.append(('域名被过滤', href))
                continue
            key = normalize_url(href)
            if key in seen:
                continue
            domain = site_domain(href)
            if ONE_RESULT_PER_DOMAIN and domain and domain in seen_domains:
                continue
            seen.add(key)
            if domain:
                seen_domains.add(domain)
            results.append((href, title, site_name))
            added += 1

        # 一个都没加上时把原因打出来，方便排查（否则只有一句「可能是最后一页」）
        if added == 0 and rejects:
            logger.info('【搜索】第 %d 页 %d 个链接均不可用，示例原因：'
                        % (page + 1, len(rejects)))
            for reason, sample in rejects[:3]:
                short = sample if len(sample) <= 90 else sample[:87] + '...'
                logger.info('    %s：%s' % (reason, short))

        if added == 0:
            logger.info('【搜索】第 %d 页没有新链接，可能是最后一页，停止翻页'
                        % (page + 1))
            break

        if page < max_pages - 1:
            time.sleep(random.uniform(*SERP_DELAY))

    logger.info('【搜索】关键词「%s」共收集 %d 个待访问链接'
                % (keyword, len(results)))
    return results


def normalize_url(url):
    """归一化 URL 用于去重：小写域名 + 去掉末尾斜杠与锚点"""
    try:
        p = urlparse(url)
        host = (p.netloc or '').lower()
        path = (p.path or '/').rstrip('/') or '/'
        return host + path
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
        return host + path
    except (ValueError, TypeError, AttributeError):
        return s.lower()


def is_acceptable(url):
    """过滤掉不需要访问的链接（社交平台、文件、Google 自家）"""
    try:
        p = urlparse(url)
    except (ValueError, TypeError):
        return False
    if p.scheme not in ('http', 'https'):
        return False
    host = (p.netloc or '').lower()
    if not host:
        return False
    if any(host == d or host.endswith('.' + d) for d in SKIP_DOMAINS):
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


def unwrap_google_url(href, base='https://www.google.com'):
    """把 Google 结果页的链接还原成目标网站的真实地址。

    Google 的 <a href> 有三种形态，前两种必须还原，否则会被当成 google.com 过滤掉：
      1. https://www.google.com/url?q=https://example.com/&sa=U&ved=...
      2. /url?q=https://example.com/&sa=U           （相对路径）
      3. https://example.com/                        （少数情况下是直链）
    另外顺带处理 AMP 链接 /amp/s/example.com/... 和 /interstitial 中转页。
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
        return h                       # 拿不到目标，留给 is_acceptable 过滤

    # ② AMP 中转页：/amp/s/example.com/path -> https://example.com/path
    if '/amp/s/' in h:
        rest = h.split('/amp/s/', 1)[1]
        if rest.startswith('http'):
            return rest
        return 'https://' + rest.lstrip('/')

    return h


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
    final_url = data.get('url') or url
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
    ld_names, ld_phones, ld_emails = jsonld_contacts(data.get('ld'))

    emails, phones = find_contacts(text, mail_links + ld_emails,
                                   tel_links + ld_phones)

    return {
        'url': final_url,
        'title': title,
        'site_name': pick_site_name(metas, ld_names[0] if ld_names else title,
                                    final_url),
        'emails': emails,
        'phones': phones,
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


_thread_local = threading.local()
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
    """每个线程一个 requests.Session，复用连接。"""
    session = getattr(_thread_local, 'session', None)
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
        _thread_local.session = session
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
    """电话或邮箱任一缺失时，用 loader 补看联系页并合并结果。"""
    if not (VISIT_CONTACT_PAGE and not (info['emails'] and info['phones'])):
        return
    for sub_url in contact_page_links(data, info['url'])[:CONTACT_PAGE_LIMIT]:
        if delay:
            time.sleep(random.uniform(delay, delay + 0.7))
        logger.info('    补看联系页：%s' % sub_url)
        info['checked_pages'].append(sub_url)
        sub_data = loader(sub_url)
        if not sub_data:
            logger.info('    补看页暂未取到内容：%s' % sub_url)
            continue
        sub = parse_page(sub_data, sub_url)
        for e in sub['emails']:
            if e not in info['emails']:
                info['emails'].append(e)
        for p in sub['phones']:
            if p not in info['phones']:
                info['phones'].append(p)
        if info['emails'] and info['phones']:
            break                # 电话邮箱都拿到了，不用再看下一个


def _browser_page_data(url):
    """用浏览器打开页面并取数据；失败返回 None。"""
    if not goto_fast(url):
        return None
    try:
        return PlayWright.page.evaluate(JS_EXTRACT) or None
    except BROWSER_ERRORS as e:
        logger.info('【解析失败】%s：%s' % (url, e))
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
    """用浏览器抓取（JS 渲染 / 反爬站点兜底）。"""
    data = _browser_page_data(url)
    if not data:
        logger.warning('【访问失败】%s' % url)
        return None
    info = parse_page(data, url)
    _follow_contact_pages(info, data, _smart_page_data, delay=0.5)
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
    """并发用接口抓取第一层页面，返回 {url: info}。

    只做 HTTP，不碰 Playwright（非线程安全）；失败的站点留给主流程用
    浏览器逐个兜底。links = [(url, title, site_name), ...]
    """
    if not (USE_HTTP_FIRST and requests is not None
            and HTTP_MAX_WORKERS > 0):
        return {}
    urls = [u for u, _t, _s in links]
    if not urls:
        return {}
    if len(urls) == 1:
        info = visit_site_http(urls[0])
        return {urls[0]: info} if info else {}

    results = {}
    total = len(urls)
    logger.info('【接口】开始并发抓取 %d 个网站（%d 线程）'
                % (total, HTTP_MAX_WORKERS))
    with ThreadPoolExecutor(max_workers=min(HTTP_MAX_WORKERS, total)) as pool:
        future_map = {pool.submit(visit_site_http, u): u for u in urls}
        for done, fut in enumerate(as_completed(future_map), 1):
            url = future_map[fut]
            try:
                info = fut.result()
            except Exception as e:       # 线程内异常不能中断整批
                logger.info('    接口抓取异常 %s：%s' % (url, e))
                info = None
            if info:
                results[url] = info
            if done % 10 == 0 or done == total:
                logger.info('【接口】进度 %d/%d，成功 %d'
                            % (done, total, len(results)))
    logger.info('【接口】完成：%d/%d 个网站可用，其余走浏览器'
                % (len(results), total))
    return results


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
HEADERS = ['关键词', '网站名称', '网站链接', '邮箱', '电话']

# 旧版本的 5 列格式（电话在前、邮箱在后），读取时自动迁移到新列顺序
LEGACY_HEADERS = ['关键词', '网站名称', '网站地址', '电话', '邮箱']

HEADER_FONT = Font(name='微软雅黑', size=11, bold=True, color='FFFFFF')
HEADER_FILL = PatternFill(start_color='4472C4', end_color='4472C4',
                          fill_type='solid')

# 写入前对「电话 / 邮箱」两列做最终校验：
# 只保留真正的电话号码 / 邮箱地址，挡住日志文本、URL、页面杂项混进来。
RE_EMAIL_STRICT = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}$')
RE_PHONE_STRICT = re.compile(r'^[+(]?\d[\d\s\-+()]{5,24}$')


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


def open_workbook(path):
    """打开或新建结果表，返回 (wb, ws, 已存在的数据键集合)。

    · 表头与当前 HEADERS 一致：直接复用。
    · 旧版 5 列（电话/邮箱顺序不同）：原地迁移列顺序后复用。
    · 其他结构（如更早的 8 列）：备份旧文件后重建，避免列错位。
    """
    if os.path.exists(path):
        try:
            wb = load_workbook(path)
            ws = wb.active
            # 取完整表头（去掉尾部空单元格）再和 HEADERS 比较
            raw_headers = [str(c.value or '').strip() for c in ws[1]]
            while raw_headers and raw_headers[-1] == '':
                raw_headers.pop()

            if raw_headers == LEGACY_HEADERS:
                # 旧: 关键词 | 网站名称 | 网站地址 | 电话 | 邮箱
                # 新: 关键词 | 网站名称 | 网站链接 | 邮箱 | 电话
                for row in ws.iter_rows(min_row=2):
                    row[3].value, row[4].value = row[4].value, row[3].value
                for col, header in enumerate(HEADERS, 1):
                    ws.cell(row=1, column=col, value=header)
                try:
                    wb.save(path)
                except PermissionError:
                    logger.warning('%s 被占用，列顺序已在内存中迁移，稍后保存'
                                   % os.path.basename(path))
                logger.info('旧结果表已迁移为：%s' % '/'.join(HEADERS))
                raw_headers = HEADERS

            if raw_headers == HEADERS:
                existing = set()
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if row and len(row) > 2 and row[2]:
                        existing.add((str(row[0] or ''),
                                      normalize_url(str(row[2]))))
                return wb, ws, existing

            # 表头不匹配：备份旧文件，重新建表
            backup = '%s.bak.%s.xlsx' % (os.path.splitext(path)[0],
                                         time.strftime('%Y%m%d%H%M%S'))
            try:
                wb.close()
            except OSError:
                pass
            os.replace(path, backup)
            logger.warning('已有结果表列结构不匹配（%s），已备份为 %s，将新建 5 列结果表'
                           % ('/'.join(raw_headers) or '空', os.path.basename(backup)))
        except (OSError, ValueError, KeyError, TypeError) as e:
            # 文件损坏 / 不是 xlsx / 表头异常等：退回新建
            logger.warning('读取已有结果表失败（%s），将新建：%s' % (path, e))

    wb = Workbook()
    ws = wb.active
    ws.title = '联系方式'
    ws.freeze_panes = 'A2'
    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
    wb.save(path)
    return wb, ws, set()


def save_records(wb, ws, path, records):
    """追加记录并立即保存（逐条落盘，中断不丢）"""
    for rec in records:
        ws.append([
            rec.get('keyword') or '',
            rec.get('site_name') or '',
            rec.get('url') or '',
            email_cell(rec),      # 无邮箱时写「暂无匹配数据」
            phone_cell(rec),      # 无电话时写「暂无匹配数据」
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
FLUSH_EVERY = 10             # 每访问这么多个网站就合并落盘一次，避免中断丢数据


def crawl(keyword, proxy=None, max_pages=MAX_SERP_PAGES,
          max_sites=MAX_SITES, out_file=None):
    """采集单个关键词：搜索 -> 逐站访问 -> 写 xlsx（边采边存）"""
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

    links = google_search(keyword, max_pages=max_pages, proxy=proxy)
    if not links:
        logger.warning('关键词「%s」没有拿到任何搜索结果' % keyword)
        logger.warning('结果表已就绪（暂无数据）：%s' % out_file)
        return 0

    # 表格里已有的链接不再访问/重复采集（忽略 www.、末尾斜杠差异）
    if SKIP_EXISTING_LINKS:
        existing_urls = set(link_key(url) for _kw, url in existing)
        before = len(links)
        links = [item for item in links
                 if link_key(item[0]) not in existing_urls]
        skipped = before - len(links)
        if skipped:
            logger.info('已跳过 %d 个结果表中已存在的链接' % skipped)
        if not links:
            logger.info('关键词「%s」的链接都已在结果表中，无需重复爬取'
                        % keyword)
            return 0

    links = links[:max_sites]
    logger.info('实际访问 %d 个网页' % len(links))

    # 先用接口并发抓取，失败的站点再逐个用浏览器兜底
    http_infos = prefetch_http(links)

    written_keys = set()
    raw_records = []
    saved = 0
    skipped_no_contact = []

    def flush():
        """把已采集的记录按域名合并后写入表格（只写还没写过的域名）"""
        nonlocal saved
        if not raw_records:
            return
        fresh = []
        for rec in merge_by_domain(raw_records):
            # 没电话也没邮箱的站点同样写入：
            # 补看过联系页的站点，单元格会显示「暂无匹配数据」。
            # 连联系页都没得补、又完全没有联系方式的，才按开关决定是否跳过。
            has_contact = bool(rec['phones'] or rec['emails'])
            has_note = bool(rec.get('checked_pages'))
            if not has_contact and not has_note and not WRITE_NO_CONTACT:
                skipped_no_contact.append(rec['url'])
                continue
            key = (keyword, normalize_url(rec['url']))
            if key in existing or key in written_keys:
                continue
            written_keys.add(key)
            fresh.append(rec)
        if fresh:
            save_records(wb, ws, out_file, fresh)
            saved += len(fresh)
        raw_records.clear()

    for idx, (url, title, site_name) in enumerate(links, 1):
        logger.info('[%d/%d] %s' % (idx, len(links), url))
        info = http_infos.get(url)
        browser_used = False

        # 接口没抓到的站点，用浏览器兜底走 JS 渲染/反爬页面
        if info is None and (not USE_HTTP_FIRST or HTTP_FALLBACK_TO_BROWSER):
            browser_used = True
            try:
                info = visit_site_browser(url)
            except BROWSER_ERRORS as e:
                # 单个站点出错不能中断整批采集
                logger.error('访问异常 %s：%s' % (url, e))
                info = None

        # 可选：接口抓到了但没有任何联系方式，再用浏览器确认一次
        if (info and HTTP_FALLBACK_IF_EMPTY
                and not (info['emails'] or info['phones'])):
            browser_used = True
            retry = None
            try:
                retry = visit_site_browser(url)
            except BROWSER_ERRORS as e:
                logger.info('浏览器兜底失败 %s：%s' % (url, e))
            if retry and (retry['emails'] or retry['phones']):
                info = retry

        # 接口补看后仍没邮箱：用浏览器重新分析补看页（有些站联系页是 JS 渲染）
        if (info and BROWSER_RETRY_CHECKED_PAGES and not browser_used
                and not info['emails'] and info.get('checked_pages')):
            browser_used = True
            try:
                _retry_checked_pages_with_browser(info)
            except BROWSER_ERRORS as e:
                logger.info('浏览器重查补看页失败 %s：%s' % (url, e))

        if info:
            info['keyword'] = keyword
            # Google 结果页给出的站点名比页面标题更简洁准确，优先采用
            if site_name:
                info['serp_name'] = site_name
            raw_records.append(info)
            found = []
            if info['phones']:
                found.append('电话 %d 个' % len(info['phones']))
            if info['emails']:
                found.append('邮箱 %d 个' % len(info['emails']))
            logger.info('    命中：%s' % ('、'.join(found) if found else '无联系方式'))
        else:
            logger.info('    跳过')

        # 定期落盘：中断最多只丢最近 FLUSH_EVERY 个网站的数据
        if idx % FLUSH_EVERY == 0:
            flush()

        # 接口抓取不需要模拟人工间隔；只有浏览器访问才等待，避免整体变慢
        if browser_used and idx < len(links):
            time.sleep(random.uniform(*PAGE_DELAY))

    flush()

    # 收尾：把「没采到联系方式所以没写入」的网站列出来，避免误以为漏写
    if skipped_no_contact:
        logger.info('以下 %d 个网站因未采到联系方式，未写入结果表：'
                    % len(skipped_no_contact))
        for u in skipped_no_contact[:20]:
            logger.info('    %s' % u)
        if len(skipped_no_contact) > 20:
            logger.info('    ...（共 %d 个）' % len(skipped_no_contact))

    logger.info('关键词「%s」本次新增 %d 条记录' % (keyword, saved))
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
    try:
        sys.exit(main())
    finally:
        try:
            PlayWright.close()
        except BROWSER_ERRORS:
            pass
