# coding='utf-8'
"""Google 关键词采集：搜索关键词 -> 抓取前 N 页搜索结果 -> 逐个访问网页 -> 提取联系方式

输出字段：关键词、网站名称、网站地址、电话、邮箱
    · 首页没有电话/邮箱时，会自动补看「联系我们 / 关于我们」页面；
      若补看后仍然没有邮箱，「邮箱」列写入备注：
      首页无联系方式，补看：https://xxx.com/contact
      这样能看出这个站查过哪个页、以及确实没留邮箱。

用法：
    python keyword_get_email.py

流程：
    1. 用 Google 搜索关键词，翻 MAX_SERP_PAGES 页（默认 10 页）
    2. 收集结果链接（跳过 Google 自家、社交平台、文件类链接）
       注意 Google 结果页的 href 现在是 /goto?url=<protobuf 加密串>，解不出目标地址，
       必须用每条结果下方 <cite> 里显示的真实域名来还原（见 resolve_result_url），
       老格式 /url?q=<目标> 也能自动还原
    3. 逐个打开网页，依次从 tel:/mailto: 链接、JSON-LD、页面正文里提取
       电话 / 邮箱 / 公司名 / 地址
    4. 首页三项全空时，自动再打开「联系我们 / 关于我们」页补抓
       （很多企业站只在联系页写地址，见 VISIT_CONTACT_PAGE）
    5. 同一域名合并成一条记录，写成 xlsx（每条落盘，中断不丢）

地址提取顺序（extract_addresses）：
    <address> 标签 → JSON-LD 结构化数据 → 正文「地址：」标签行
    → 「地址」独占一行的下一行 → 无标签时按地址特征兜底
    支持 公司地址/办公地址/详细地址/注册地址/工厂地址/厂址 等写法，
    也支持标签在行中间、带括号注释、冒号后换行、全角空格。

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
from html import unescape as html_unescape
from urllib.parse import urlparse, quote_plus, parse_qs

from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(str(Path(__file__).parent.parent))

from PatchRightClass import PatchRightClass
from Logger import logger          # 与 PatchRightClass 共用同一个日志实例
PlayWright = PatchRightClass()

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

# 浏览器操作可能抛出的异常：Playwright/patchright 自己的 Error、超时、
# 以及页面被关闭 / 导航中断等引起的 OSError / RuntimeError。
# 单独收敛成元组，避免到处写 except Exception 把真正的代码错误也吞掉。
try:
    from patchright.sync_api import Error as _BrowserError
except ImportError:                       # 兼容只装了 playwright 的环境
    try:
        from playwright.sync_api import Error as _BrowserError
    except ImportError:
        _BrowserError = OSError

BROWSER_ERRORS = (_BrowserError, OSError, RuntimeError, ValueError)


# ==================== 采集参数（按需改这里） ====================
MAX_SERP_PAGES = 10          # Google 搜索结果最多翻几页（每页约 10 条）
MAX_SITES = 100              # 最多访问多少个网页（防止跑飞）
PAGE_DELAY = (1.5, 3.5)      # 每访问一个网页后的随机等待（秒）
SERP_DELAY = (2.5, 5.0)      # 每翻一页搜索结果的随机等待（秒）
PAGE_TIMEOUT = 25000         # 单个网页加载超时（毫秒）
OUT_NAME = 'google_contacts.xlsx'

# 首页抓不到电话/邮箱时，是否再打开「联系我们 / 关于我们」页面补抓
# 很多企业官网只在联系页留联系方式，这一步能明显提高命中率
VISIT_CONTACT_PAGE = True
CONTACT_PAGE_LIMIT = 2       # 每个网站最多补看几个联系页（别设太大，会变慢）

# 既没有电话、也没有邮箱、还没补看过联系页的网站，是否也写入结果表
#   False（默认）：不写入，日志会列出跳过了哪些站点
#   True         ：写进表格（邮箱列留空），适合要「全量站点清单」时用
# 注意：补看过联系页的站点无论有没有邮箱都会写入，
#       邮箱列会写「首页无联系方式，补看：<url>」作为备注。
WRITE_NO_CONTACT = False

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

# 地址线索（用于从正文里补抓）
# 常见地址标签。顺序很重要：长标签放前面，否则「公司地址」会被「地址」抢先匹配，
# 导致标签识别不全。地\s*址 / 厂\s*址 兼容「地　址」这种中间加空格、加全角空格的写法。
_ADDR_LABELS = (
    '公司地址', '办公地址', '联系地址', '详细地址', '企业地址', '注册地址',
    '生产地址', '工厂地址', '厂区地址', '总部地址', '门店地址', '通讯地址',
    '收货地址', '项目地址', '地\\s*址', '厂\\s*址',
    'Address', 'Addr', 'Add',
)
_ADDR_LABEL = '(?:%s)' % '|'.join(_ADDR_LABELS)

# 英文标签要求前后不是字母，避免 "Email Address" 里的 "Address"、
# "Add to cart" 里的 "Add" 被当成地址标签
_ADDR_LABEL_EN_SAFE = (r'(?<![A-Za-z])(?:Address|Addr|Add)(?![A-Za-z])')

# 行首的地址标签（用于兜底时把「联系地址 浙江省…」前面的标签去掉）
RE_ADDR_LEAD_LABEL = re.compile(r'^\s*' + _ADDR_LABEL + r'\s*[:：]?\s*', re.I)

# ① 标签 + 可选括号说明（如「地址（Address）」）+ 冒号 + 值
#    值用 [^\n\r] 取当前行剩余内容；冒号后即使换行，也由 \s* 吃掉换行继续匹配下一行
RE_ADDR_LABELED = re.compile(
    '(?:' + _ADDR_LABEL + '|' + _ADDR_LABEL_EN_SAFE + ')' +
    r'\s*(?:[（(][^）)\n]{0,24}[）)])?'
    r'\s*[:：]\s*'
    r'([^\n\r]{4,160})',
    re.I)

# ② 「地址」独占一行、没有冒号，值在下一行
#    必须用 ^ 锚定行首：否则 "Email Address\nSign Up" 会从 "Address" 处开始匹配，
#    把下一行的 "Sign Up" 当成地址（真实踩过的坑）
RE_ADDR_NO_COLON = re.compile(
    r'^[ \t]*'
    '(?:' + _ADDR_LABEL + '|' + _ADDR_LABEL_EN_SAFE + ')' +
    r'\s*(?:[（(][^）)\n]{0,24}[）)])?[ \t]*$[ \t]*\r?\n[ \t]*'
    r'([^\n\r]{4,160})',
    re.I | re.M)

# ③ 地址值里出现这些词就截断（地址后面常紧跟电话 / 邮编 / 邮箱）
RE_ADDR_STOP = re.compile(
    r'\s*(?:电\s*话|联系电话|联系方式|Tel|TEL|Phone|传真|Fax|'
    r'邮\s*编|邮政编码|Zip|E-?mail|邮\s*箱|手\s*机|Mobile|微\s*信)\s*[:：]?',
    re.I)


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


# ---------- 地址提取 ----------
# 中文地址特征：省市区县等行政区划 + 路街号栋楼等门牌特征
_ADDR_CN_HINT = ('省', '市', '区', '县', '镇', '乡', '街道', '路', '街',
                 '巷', '弄', '号', '栋', '幢', '楼', '层', '室', '大厦',
                 '广场', '园区', '工业园', '科技园', '大道', '村')
# 英文地址特征：街道类关键词（前后补空格避免误匹配子串）
_ADDR_EN_HINT = (' street', ' st.', ' st ', ' avenue', ' ave', ' road',
                 ' rd ', ' boulevard', ' blvd', ' drive', ' dr.', ' lane',
                 ' ln ', ' suite', ' floor', ' building', ' bldg', ' way ',
                 ' highway', ' hwy', ' parkway', ' pkwy', ' court', ' ct ',
                 ' place', ' pl.', ' plaza', ' square', ' unit ')
RE_ADDR_ZIP = re.compile(r'\b\d{5}(?:-\d{4})?\b')


# 地址值里出现这些词，说明抓到的不是真实地址（表单占位符、提示语等）
_ADDR_JUNK = ('请输入', '请填写', '请选择', '暂无', '未填写', '待完善',
              '点击查看', '了解更多', '详情请', '加载中', '地图导航',
              '查看地图', '点击地图')


def looks_like_address(value, max_len=160):
    """判断一段文本像不像真实地址。

    用来过滤「Sign Up」「Email Address」这类误命中：
      · 中文：至少命中 2 个行政区划/道路门牌特征
      · 英文：必须有门牌数字，且带街道词或邮编
    """
    s = str(value or '').strip()
    if not (6 <= len(s) <= max_len):
        return False
    if re.search(r'[。！？!?]', s):            # 有句末标点，多半是正文句子
        return False
    if RE_EMAIL.search(s) or RE_MOBILE_CN.search(s):
        return False

    if re.search(r'[\u4e00-\u9fa5]', s):
        return sum(1 for k in _ADDR_CN_HINT if k in s) >= 2

    low = ' ' + s.lower() + ' '
    has_digit = bool(re.search(r'\d', s))
    has_street = any(k in low for k in _ADDR_EN_HINT)
    has_zip = bool(RE_ADDR_ZIP.search(s))
    return has_digit and (has_street or has_zip)


def clean_address(value):
    """清理地址值：压空白、截掉后面的电话/邮编/邮箱、去掉首尾多余符号"""
    s = re.sub(r'\s+', ' ', str(value or '')).strip()
    if not s:
        return ''
    # 表单占位符 / 提示语，不是真实地址
    if any(j in s for j in _ADDR_JUNK):
        return ''
    # 地址后面常紧跟「电话：」「邮编：」等，从这些词开始全部丢弃
    s = RE_ADDR_STOP.split(s)[0].strip()
    # 「南京路100号（电话：xxx）」截断后会残留一个左括号，括号不配对就丢到括号前
    for open_ch, close_ch in (('（', '）'), ('(', ')')):
        if s.count(open_ch) > s.count(close_ch):
            s = s[:s.rfind(open_ch)].strip()
    s = s.strip(' ，,；;、|/\\-—:：.')
    if not s:
        return ''
    # 最终校验：不像地址的一律丢弃（挡住「Sign Up」之类的误命中）
    if not looks_like_address(s):
        return ''
    return s


def extract_addresses(ld_addrs, tag_addrs, text):
    """按可靠性依次提取地址。

    顺序：<address> 语义标签 → JSON-LD 结构化数据 → 正文「地址：」标签行
          → 「地址」独占一行的下一行 → 无标签时按地址特征兜底
    <address> 排在 JSON-LD 前面，因为它是站点自己展示给人看的完整地址文本；
    JSON-LD 里的地址常被拆成省/市/街道几段，拼接后反而不如原文本完整。
    返回去重后的地址列表（第一个最可能是完整地址）。
    """
    out = []

    def push(value):
        v = clean_address(value)
        if v and v not in out:
            out.append(v)

    for v in tag_addrs or []:
        push(v)
    for v in ld_addrs or []:
        push(v)

    body = text or ''
    if body:
        for m in RE_ADDR_LABELED.findall(body):
            push(m)
        for m in RE_ADDR_NO_COLON.findall(body):
            push(m)

    # 完全没有标签时，再从正文里找「长得像地址」的整行，避免漏采
    if not out and body:
        for line in body.splitlines():
            if looks_like_address(line, max_len=80):
                # 表格布局里 innerText 会把「联系地址」和值挤在同一行，去掉行首标签
                push(RE_ADDR_LEAD_LABEL.sub('', line))
                if len(out) >= 3:
                    break

    return out


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
    """从 JSON-LD 结构化数据里取公司名 / 电话 / 邮箱 / 地址（最准）"""
    names, phones, emails, addresses = [], [], [], []

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
                elif low in ('address', 'postaladdress'):
                    if isinstance(value, str):
                        addresses.append(value.strip())
                    elif isinstance(value, dict):
                        # 中文地址习惯「省市 + 街道门牌」，英文地址习惯「街道 + 城市 + 州」
                        street = str(value.get('streetAddress') or '').strip()
                        locality = str(value.get('addressLocality') or '').strip()
                        region = str(value.get('addressRegion') or '').strip()
                        postal = str(value.get('postalCode') or '').strip()
                        has_cjk = any(re.search(r'[\u4e00-\u9fa5]', x)
                                      for x in (street, locality, region))
                        if has_cjk:
                            pieces = [region, locality, street, postal]
                        else:
                            pieces = [street, locality, region, postal]
                        pieces = [p for p in pieces if p]
                        if pieces:
                            addresses.append(' '.join(pieces))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in ld_blocks or []:
        try:
            walk(json.loads(block))
        except (ValueError, TypeError):
            continue
    return names, phones, emails, addresses


# ==================== 浏览器操作 ====================
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
    try:
        PlayWright.page.wait_for_load_state('domcontentloaded',
                                           timeout=PAGE_TIMEOUT)
    except BROWSER_ERRORS:
        pass
    time.sleep(seconds)


def goto_fast(url, retry=2):
    """打开网页（不带 PlayWright.goto 里固定的 5 秒等待）。

    批量访问几十上百个网站时，每页固定多等 5 秒会白耗好几分钟，
    这里直接用 page.goto，自己控制等待时长。
    """
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
    """搜索关键词，返回 [(url, title), ...]（已去重、已过滤）"""
    results = []
    seen = set()

    for page in range(max_pages):
        start = page * 10
        url = ('https://www.google.com/search?q=%s&start=%d&hl=en&num=10'
               % (quote_plus(keyword), start))
        logger.info('【搜索】第 %d/%d 页：%s' % (page + 1, max_pages, keyword))

        # 第一次访问要带代理（代理只在启动浏览器时生效）
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
            seen.add(key)
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
    const addrs = Array.from(document.querySelectorAll('address'))
        .map(a => (a.innerText || '').trim());
    // 站内链接：首页没有联系方式时，用来找「联系我们 / 关于我们」补抓
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
        addrs: addrs,
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
    tel_links = [t.split(':', 1)[-1] for t in (data.get('tels') or [])]
    mail_links = [m.split(':', 1)[-1].split('?', 1)[0]
                  for m in (data.get('mails') or [])]

    # JSON-LD 结构化数据
    ld_names, ld_phones, ld_emails, ld_addrs = jsonld_contacts(data.get('ld'))

    emails, phones = find_contacts(text, mail_links + ld_emails,
                                   tel_links + ld_phones)

    # 地址：JSON-LD > <address> 标签 > 正文「地址：」行 > 整行兜底
    addresses = extract_addresses(ld_addrs, data.get('addrs'), text)

    return {
        'url': final_url,
        'title': title,
        'site_name': pick_site_name(metas, ld_names[0] if ld_names else title,
                                    final_url),
        'emails': emails,
        'phones': phones,
        'address': addresses[0] if addresses else '',
        'checked_pages': [],      # 补看过的联系页，最终会写进「邮箱」列做备注
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


def visit_site(url):
    """访问单个网页，返回提取到的联系人信息字典；失败返回 None

    首页三项（电话/邮箱/地址）全空时，会再打开最多 CONTACT_PAGE_LIMIT 个
    「联系我们 / 关于我们」页面补抓——很多企业站只在联系页写地址。
    """
    if not goto_fast(url):
        logger.warning('【访问失败】%s' % url)
        return None

    try:
        data = PlayWright.page.evaluate(JS_EXTRACT) or {}
    except BROWSER_ERRORS as e:
        logger.warning('【解析失败】%s：%s' % (url, e))
        return None

    info = parse_page(data, url)

    # 需要补看联系页的条件：没有电话，且没有邮箱
    need_more = not (info['emails'] or info['phones'])
    if VISIT_CONTACT_PAGE and need_more:
        for sub_url in contact_page_links(data, info['url'])[:CONTACT_PAGE_LIMIT]:
            time.sleep(random.uniform(0.5, 1.2))
            logger.info('    首页无联系方式，补看：%s' % sub_url)
            # 无论补看成功与否都记下来，最终写进「邮箱」列当备注
            info['checked_pages'].append(sub_url)
            if not goto_fast(sub_url):
                continue
            try:
                sub_data = PlayWright.page.evaluate(JS_EXTRACT) or {}
            except BROWSER_ERRORS:
                continue
            sub = parse_page(sub_data, sub_url)
            for e in sub['emails']:
                if e not in info['emails']:
                    info['emails'].append(e)
            for p in sub['phones']:
                if p not in info['phones']:
                    info['phones'].append(p)
            if not info['address'] and sub['address']:
                info['address'] = sub['address']
            if info['emails'] and info['phones']:
                break            # 电话邮箱都拿到了，不用再看下一个

    return info


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
                'address': rec['address'],
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
        if not cur['address'] and rec['address']:
            cur['address'] = rec['address']
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
HEADERS = ['关键词', '网站名称', '网站地址', '电话', '邮箱']

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
        # 必须是纯 ASCII 的标准邮箱，且整串完全匹配
        if not s.isascii():
            continue
        if not RE_EMAIL_STRICT.match(s):
            continue
        if s not in out:
            out.append(s)
    return '; '.join(out)


def email_cell_with_note(rec):
    """「邮箱」列最终内容。

    有邮箱：只写邮箱（多个用 ; 分隔）。
    没邮箱但有补看过联系页：写「首页无联系方式，补看：<url>」作为备注，
    方便事后知道查过哪个页、以及该站确实没留邮箱。
    """
    emails = safe_email_cell(rec.get('emails'))
    if emails:
        return emails
    checked = rec.get('checked_pages') or []
    if checked:
        return '首页无联系方式，补看：%s' % '；'.join(checked)
    return ''


def open_workbook(path):
    """打开或新建结果表，返回 (wb, ws, 已存在的数据键集合)。

    如果已有的 xlsx 表头与当前 HEADERS 不一致（例如旧版本的 8 列），
    会把旧文件改名备份后重建，避免新旧列错位把数据写到错误的列里。
    """
    if os.path.exists(path):
        try:
            wb = load_workbook(path)
            ws = wb.active
            # 取完整表头（去掉尾部空单元格）再和 HEADERS 比较，
            # 只比前 5 列会把旧的 8 列表误判成「结构一致」，导致列错位
            raw_headers = [str(c.value or '').strip() for c in ws[1]]
            while raw_headers and raw_headers[-1] == '':
                raw_headers.pop()
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
            safe_phone_cell(rec.get('phones')),   # 二次校验，非电话不写入
            email_cell_with_note(rec),            # 无邮箱时写入「补看」备注
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

    # 先把结果表准备好：即使一条都没采到，也留下带表头的文件，
    # 方便确认输出位置（否则 0 条时直接 return，连文件都不会生成）
    wb, ws, existing = open_workbook(out_file)
    logger.info('结果表：%s' % out_file)

    links = google_search(keyword, max_pages=max_pages, proxy=proxy)
    if not links:
        logger.warning('关键词「%s」没有拿到任何搜索结果' % keyword)
        logger.warning('结果表已就绪（暂无数据）：%s' % out_file)
        return 0

    links = links[:max_sites]
    logger.info('实际访问 %d 个网页' % len(links))

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
            # 邮箱列会带「首页无联系方式，补看：xxx」备注，方便事后核对查过哪些页。
            # 既不写邮箱列也没有备注、且完全没电话的，才按开关决定是否跳过。
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
        try:
            info = visit_site(url)
        except BROWSER_ERRORS as e:
            # 单个站点出错不能中断整批采集
            logger.error('访问异常 %s：%s' % (url, e))
            info = None

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
            if info['address']:
                found.append('地址')
            logger.info('    命中：%s' % ('、'.join(found) if found else '无联系方式'))
        else:
            logger.info('    跳过')

        # 定期落盘：中断最多只丢最近 FLUSH_EVERY 个网站的数据
        if idx % FLUSH_EVERY == 0:
            flush()

        if idx < len(links):
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


def main():
    print('=' * 60)
    print(' Google 关键词采集 —— 提取电话 / 邮箱 / 网站名称 / 地址')
    print('=' * 60)
    print('提示：Google 需要代理，直接回车表示不使用代理。')

    keyword = input('请输入关键词（多个用英文逗号分隔）：').strip()
    if not keyword:
        print('关键词不能为空')
        return 1

    proxy_input = input('请输入代理（如 127.0.0.1:7892，回车跳过）：').strip()
    proxy = {'server': 'http://%s' % proxy_input} if proxy_input else None

    pages_input = input('Google 搜索翻几页（默认 %d，回车使用默认）：'
                        % MAX_SERP_PAGES).strip()
    max_pages = int(pages_input) if pages_input.isdigit() else MAX_SERP_PAGES

    sites_input = input('最多访问多少个网页（默认 %d，回车使用默认）：'
                        % MAX_SITES).strip()
    max_sites = int(sites_input) if sites_input.isdigit() else MAX_SITES

    keywords = [k.strip() for k in re.split(r'[,，]', keyword) if k.strip()]

    total = 0
    for kw in keywords:
        logger.info('=' * 50)
        logger.info('开始采集关键词：%s' % kw)
        try:
            total += crawl(kw, proxy=proxy, max_pages=max_pages,
                           max_sites=max_sites)
        except BROWSER_ERRORS as e:
            # 一个关键词失败不影响后续关键词
            logger.error('关键词「%s」采集失败：%s' % (kw, e))
        time.sleep(random.uniform(*SERP_DELAY))

    logger.info('=' * 50)
    logger.info('全部完成，本次新增 %d 条记录，文件：%s'
                % (total, os.path.join(BASE_DIR, OUT_NAME)))
    print('\n完成，结果文件：%s' % os.path.join(BASE_DIR, OUT_NAME))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        try:
            PlayWright.close()
        except BROWSER_ERRORS:
            pass
