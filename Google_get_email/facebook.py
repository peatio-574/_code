# coding='utf-8'
"""Facebook 群组采集：搜索关键词 -> 逐个打开主页 -> 提取地址(国家) / 电话 / 邮箱 -> 写 xlsx

与 google.py 的关系：
    本模块只负责 Facebook 的采集流程，结果表读写、运行时钩子（进度 / 实时记录 /
    停止信号）、国家识别全部复用 google.py —— 两个采集源写进同一套 xlsx，
    列结构只需要维护一处。

    用法（图形界面请运行 run.py）：
        python facebook.py -k "RC car raceway" -p 127.0.0.1:7892

依赖：
    · config.ini 里的 [login] facebook_cookie —— 首次运行会自动打开浏览器
      让你手动登录，登录成功后 cookie 会写回这个文件，之后就不用再登。
    · 系统 Edge（newPlayWright 默认用它）

原脚本里修掉的两个问题（保留说明，避免以后又写回去）：
    1. 地址/电话/邮箱的 XPath 少了一个右方括号，一直是非法表达式；
       现在补上，并且额外用「整页文本 + mailto:/tel: 链接」兜底。
    2. get_all_detail() 把 search() 返回的 [名称, 链接] 整个当成 URL 传给
       get_detail()，等于抓错页面；现在按二元组拆开传。
"""
import os
import re
import sys
import time
import random
from pathlib import Path
from urllib.parse import quote_plus, unquote

sys.path.append(str(Path(__file__).parent.parent))

import google as G                       # 通用层：结果表 / 钩子 / 国家识别
from google import logger                # 与 Google 共用同一个 logger
from newPlayWright import PlayWright

from Config import CaseSensitiveConfig

# config.ini 跟着「可写目录」走：打包成 exe 后 __file__ 指向临时解包目录
# _MEIPASS（退出即删），cookie 写进去下次就找不到了。必须用 exe 所在目录。
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(G.BASE_DIR, 'config.ini')
COOKIE_KEY = 'login.facebook_cookie'

# 首次运行时生成的空白配置（用户可以自己打开这个文件改，改完立即生效）。
# 故意只用 ASCII：用户可能用记事本按 ANSI(GBK) 另存，若这里写中文，
# 下次按 utf-8 读就会抛异常。
CONFIG_TEMPLATE = (
    "[login]\r\n"
    "; Facebook login cookie. Written back automatically after login.\r\n"
    "; To switch account: click the delete-account button, or log in again.\r\n"
    "facebook_cookie = \r\n"
    "facebook_cookie_api = \r\n"
)


def ensure_config_template():
    """确保 config.ini 存在（只在缺失时创建，绝不覆盖已有内容）。

    打包成 exe 分发时，config.ini 是「exe 同级的外部文件」：
    用户可以直接编辑它，程序读写的就是这一份。
    """
    if os.path.isfile(CONFIG_FILE):
        return CONFIG_FILE
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE) or '.', exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8', newline='') as f:
            f.write(CONFIG_TEMPLATE)
        logger.info('【FB】已生成空白配置：%s' % CONFIG_FILE)
    except OSError as e:
        logger.warning('【FB】创建配置失败（%s）：%s' % (CONFIG_FILE, e))
    return CONFIG_FILE

# 搜索群组/主页。sde 是 Facebook 的搜索上下文标记，失效时不影响结果，
# 所以允许通过下面的常量覆盖或留空。
SEARCH_URL = ('https://www.facebook.com/search/groups/?q=%s'
              '&sde=AbrggujvjMyXR74p7wCRmi0L_zu0jmOyUZzf8HGUjsoFR3AgjBZh7C6nMHBmYpwZR4RMZiAkOHyu6RQidk6huyHE')
# 搜索页里每一条结果的锚点（Facebook 用 role="presentation" 标记）
RESULT_XPATH = '//a[@role="presentation"]'

MAX_RESULTS = 300        # 单个关键词最多收集多少个主页
MAX_SCROLL = 100          # 搜索页最多往下滚几次
SCROLL_PX = 800          # 每次滚动距离
STALE_ROUNDS = 4         # 连续几轮没有新结果就认为到底了
SEARCH_DELAY = (2.0, 4.0)
PAGE_DELAY = (1.5, 3.0)

# 主页信息卡上的图标（data URI SVG）。Facebook 用图标定位「地址 / 电话 / 邮箱」
# 这三行文字，比按 class 名找更稳 —— class 名是构建时生成的，经常变。
ADDR_SVG = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
            "width='24' height='24' viewBox='0 0 24 24'%3E %3Cpath d='M12 "
            "5.499a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm-2 4a2 2 0 1 1 4 0 2 2 0 0 "
            "1-4 0Z'/%3E %3Cpath d='M12 .5a9 9 0 0 0-9 9c0 2.64 1.351 "
            "5.422 2.859 7.736 1.529 2.347 3.325 4.37 4.418 5.522a2.365 "
            "2.365 0 0 0 3.446 0c1.093-1.152 2.89-3.175 4.418-5.522C19.65 "
            "14.922 21 12.14 21 9.5a9 9 0 0 0-9-9Zm-7 9a7 7 0 0 1 14 0c0 "
            "2.036-1.077 4.408-2.535 6.645-1.435 2.204-3.14 4.128-4.192 "
            "5.236a.365.365 0 0 1-.546 0c-1.051-1.108-2.757-3.032-4.192-"
            "5.236C6.077 13.908 5 11.535 5 9.5Z'/%3E %3C/svg%3E")
TEL_SVG = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "width='24' height='24' viewBox='0 0 24 24'%3E %3Cpath d='M3.12 "
           "1.465a2.5 2.5 0 0 1 3.704.184l2.714 3.318a2.5 2.5 0 0 1 .081 "
           "3.061l-1.561 2.13a.23.23 0 0 0-.008.26 18.67 18.67 0 0 0 5.532 "
           "5.532.23.23 0 0 0 .26-.008l2.13-1.561a2.5 2.5 0 0 1 3.06.08l"
           "3.319 2.715a2.5 2.5 0 0 1 .184 3.703l-.66.66a6.893 6.893 0 0 "
           "1-8.267 1.127A32.43 32.43 0 0 1 1.335 10.391 6.893 6.893 0 0 "
           "1 2.46 2.125l.66-.66Zm2.156 1.45a.5.5 0 0 0-.74-.036l-.662.66a"
           "4.893 4.893 0 0 0-.8 5.868 30.43 30.43 0 0 0 11.519 11.518 "
           "4.893 4.893 0 0 0 5.867-.8l.66-.66a.5.5 0 0 0-.036-.74l-3.318-"
           "2.715a.5.5 0 0 0-.612-.017l-2.13 1.562a2.23 2.23 0 0 1-2.529"
           ".074 20.668 20.668 0 0 1-6.124-6.125 2.23 2.23 0 0 1 .074-2.529"
           "l1.561-2.13a.5.5 0 0 0-.016-.612L5.276 2.916Z'/%3E %3C/svg%3E")
EMAIL_SVG = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
             "width='24' height='24' viewBox='0 0 24 24'%3E %3Cpath d='M5.581 "
             "8.186A1 1 0 0 0 4.42 9.814l3.56 2.542c.802.574 1.472 1.052 "
             "2.063 1.38.625.348 1.246.578 1.958.578s1.334-.23 1.958-.576c"
             ".591-.329 1.261-.807 2.064-1.38l3.559-2.54A1 1 0 1 0 18.42 "
             "8.19l-3.513 2.507c-.86.614-1.439 1.025-1.919 1.292-.457.254-"
             ".738.325-.987.325s-.529-.071-.986-.325c-.48-.267-1.058-.678-"
             "1.919-1.293l-3.514-2.51Z'/%3E %3C/svg%3E")

# 注意：下面三个表达式末尾的 `"]` 不能少 —— 原脚本漏掉过，导致一直是非法 XPath，
# Playwright 直接抛异常，地址/电话/邮箱一个都取不到。
ADDR_XPATH = '//img[@src="%s"]/../../div[2]//a' % ADDR_SVG
TEL_XPATH = '//img[@src="%s"]/../../div[2]//span[@dir="auto"]' % TEL_SVG
EMAIL_XPATH = '//img[@src="%s"]/../../div[2]//a' % EMAIL_SVG

# 一次取回整页信息：mailto:/tel: 链接 + 正文
JS_FB_EXTRACT = r"""
() => {
    const pick = (sel) => Array.from(document.querySelectorAll(sel))
        .map(a => a.getAttribute('href') || '');
    let text = '';
    try { text = document.body ? document.body.innerText : ''; } catch (e) {}
    return {
        mails: pick('a[href^="mailto:"]'),
        tels: pick('a[href^="tel:"]'),
        text: text.slice(0, 200000),
    };
}
"""


# ==================== 登录 ====================
def login(url='https://www.facebook.com'):
    """登录 Facebook（有 cookie 就直接用，没有就等你手动登录）。

    返回 True 表示已登录。登录成功后 cookie 会由 newPlayWright 写回 config.ini。
    """
    logger.info('【FB】检查登录状态……')
    ensure_config_template()
    logger.info('【FB】配置文件：%s' % CONFIG_FILE)
    ok = PlayWright.login(url=url, location='//input[@type="search"]',
                          key=COOKIE_KEY, file=CONFIG_FILE)
    if not ok:
        logger.error('【FB】登录失败：config.ini 里的 cookie 可能已失效，'
                     '且 3 分钟内没有完成手动登录')
        return False
    try:
        PlayWright.reload()
    except G.BROWSER_ERRORS:
        pass
    logger.info('【FB】登录成功')
    return True


# ==================== 账号（cookie）管理 ====================
def _cookie_section_option():
    """COOKIE_KEY 拆成 (section, option)，如 ('login', 'facebook_cookie')。"""
    section, option = COOKIE_KEY.split('.', 1)
    return section, option


def login_status():
    """config.ini 里是否存着 Facebook cookie（即「已保存账号」）。

    只读文件、不启动浏览器，界面上可以随便调用。
    """
    section, option = _cookie_section_option()
    if not os.path.isfile(CONFIG_FILE):
        return False
    try:
        cfg = CaseSensitiveConfig(interpolation=None)
        cfg.read(CONFIG_FILE, encoding='utf-8')
        if not cfg.has_section(section):
            return False
        value = (cfg.get(section, option, fallback='') or '').strip()
    except Exception as e:               # noqa: BLE001  配置文件坏了不该让界面崩
        logger.warning('【FB】读取登录状态失败：%s' % e)
        return False
    # 空字符串 / 字面量 '[]' 都算没登录
    return value not in ('', '[]')


def clear_login():
    """删除 config.ini 里的 Facebook cookie（相当于「退出登录 / 删除账号」）。

    同时删掉给接口用的 `<option>_api` 那一行 —— 它是同一份 cookie 的扁平写法，
    留着的话下次启动又会被当成「已登录」。

    浏览器用的是非持久化 context（cookie 只存在内存里），所以删掉配置文件后
    下次采集一定会重新要求登录，不需要额外清浏览器缓存。

    返回 (ok, message)。
    """
    section, option = _cookie_section_option()
    names = (option, option + '_api')

    if not os.path.isfile(CONFIG_FILE):
        return False, '没找到配置文件：%s' % CONFIG_FILE

    try:
        cfg = CaseSensitiveConfig(interpolation=None)
        cfg.read(CONFIG_FILE, encoding='utf-8')
    except Exception as e:               # noqa: BLE001
        return False, '读取配置失败：%s' % e

    if not cfg.has_section(section):
        return True, '配置里本来就没有登录信息，无需删除'

    removed = []
    for name in names:
        if cfg.has_option(section, name):
            cfg.remove_option(section, name)
            removed.append(name)

    if not removed:
        return True, '配置里本来就没有登录信息，无需删除'

    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            cfg.write(f)
    except OSError as e:
        logger.error('【FB】写回配置失败：%s' % e)
        return False, '写入配置失败：%s' % e

    # 浏览器还在跑的话顺手清掉内存里的 cookie，避免这次会话还「登录着」
    if getattr(PlayWright, 'context', None) is not None:
        try:
            PlayWright.clear_cookie()
        except Exception as e:           # noqa: BLE001
            logger.info('【FB】清除浏览器 cookie 失败（可忽略）：%s' % e)

    logger.info('【FB】已删除账号：config.ini 里的 %s 已清除' % '、'.join(removed))
    return True, '已删除已保存的 Facebook 账号，下次采集需要重新登录'


# ==================== 搜索 ====================
def _safe_text(xpath):
    """取元素文本，元素不存在 / 取失败时返回空串。"""
    try:
        if PlayWright.get_count(xpath):
            return (PlayWright.get_text(xpath) or '').strip()
    except G.BROWSER_ERRORS:
        pass
    except Exception:                # noqa: BLE001  定位器内部异常种类很杂
        pass
    return ''


def _safe_attr(xpath, key):
    try:
        if PlayWright.get_count(xpath):
            return (PlayWright.get_attribute(xpath, key) or '').strip()
    except G.BROWSER_ERRORS:
        pass
    except Exception:                # noqa: BLE001
        pass
    return ''


def search(keyword, max_results=None):
    """搜索群组/主页，返回 [(名称, 链接), ...]（已去重，只要 Facebook 站内链接）。

    滚动加载时用「连续几轮没有新增」判断到底，而不是像原脚本那样数重复条数
    —— 原脚本拿错变量做比较，重复计数永远是 0，会一直滚到上限。
    """
    max_results = max_results or MAX_RESULTS
    url = SEARCH_URL % quote_plus(keyword)
    logger.info('【FB搜索】%s' % keyword)
    G.report_progress('search', 1, 1, '搜索 Facebook：%s' % keyword)

    if not G.goto_fast(url):
        logger.error('【FB搜索】打开搜索页失败：%s' % keyword)
        return []

    out = []
    seen = set()
    stale = 0

    for rnd in range(MAX_SCROLL):
        if G.stop_requested():
            logger.warning('【FB搜索】已停止，保留已找到的 %d 个结果' % len(out))
            break

        before = len(out)
        try:
            count = PlayWright.get_count(RESULT_XPATH)
        except G.BROWSER_ERRORS as e:
            logger.info('【FB搜索】取结果条数失败：%s' % e)
            break

        for i in range(1, count + 1):
            if G.stop_requested() or len(out) >= max_results:
                break
            row = '(%s)[%d]' % (RESULT_XPATH, i)
            name = _safe_text(row)
            link = _safe_attr(row, 'href')
            if not link or link in seen:
                continue
            # 只收 Facebook 站内链接（外链、javascript: 之类都丢掉）
            if 'facebook.com' not in link:
                continue
            seen.add(link)
            out.append((name, link))
            G.report_link(link, name, name, keyword, len(out))

        # 每轮都打印进度：页面 DOM 里有多少条、本轮新增多少、累计多少。
        # 页面条数不涨 / 新增为 0 时能立刻看出是「到底了」还是「选择器失效」。
        added = len(out) - before
        logger.info('【FB搜索】第 %d/%d 轮滚动：页面 %d 条，新增 %d 条，累计 %d 条'
                    % (rnd + 1, MAX_SCROLL, count, added, len(out)))
        G.report_progress('search', len(out), max_results,
                          '已滚动 %d 轮，累计 %d 个主页'
                          % (rnd + 1, len(out)))

        if len(out) >= max_results:
            logger.info('【FB搜索】已达上限 %d 个，停止滚动' % max_results)
            break
        if added == 0:
            stale += 1
            logger.info('【FB搜索】本轮没有新结果（连续 %d/%d 轮）'
                        % (stale, STALE_ROUNDS))
            if stale >= STALE_ROUNDS:
                logger.info('【FB搜索】连续 %d 轮没有新结果，停止滚动' % stale)
                break
        else:
            stale = 0

        try:
            PlayWright.mouse_wheel(SCROLL_PX)
        except G.BROWSER_ERRORS:
            break
        time.sleep(random.uniform(0.8, 1.6))

    logger.info('【FB搜索】关键词「%s」共收集 %d 个主页' % (keyword, len(out)))
    G.report_progress('links', len(out), len(out),
                      '找到 %d 个 Facebook 主页' % len(out))
    return out


# ==================== 详情 ====================
def _extract_contacts(data):
    """从一次页面抓取结果里提取 (emails, phones, addr)。

    数据来自 JS_FB_EXTRACT：mailto:/tel: 链接 + 整页正文。
    信息卡上的图标定位是主路径，取不到时用正文兜底。
    """
    text = (data or {}).get('text') or ''

    # tel:/mailto: 链接是最可靠的来源，先去协议、去查询串、拆多地址
    tel_links = [unquote(t.split(':', 1)[-1].split('?', 1)[0])
                 for t in (data.get('tels') or [])]
    mail_links = []
    for m in data.get('mails') or []:
        raw = unquote(m.split(':', 1)[-1].split('?', 1)[0])
        for part in re.split(r'[,;]', raw):
            part = part.strip()
            if part:
                mail_links.append(part)

    emails, phones = G.find_contacts(text, mail_links, tel_links)

    # 信息卡：图标定位（Facebook 当前版本的 DOM）
    addr = _safe_text(ADDR_XPATH)
    if not emails:
        hit = _safe_text(EMAIL_XPATH)
        if hit:
            emails = G.clean_emails([hit]) or emails
    if not phones:
        hit = _safe_text(TEL_XPATH)
        if hit:
            phones = G.clean_phones([hit]) or phones

    # 地址兜底：正文里带「地址 / address」关键词的行
    if not addr:
        segs = G.address_segments(text)
        addr = segs[0] if segs else ''

    return emails, phones, addr


def _grab_page():
    """读取当前页面的提取数据；失败返回 None。"""
    page = getattr(PlayWright, 'page', None)
    if page is None:
        return None
    try:
        return page.evaluate(JS_FB_EXTRACT) or None
    except G.BROWSER_ERRORS as e:
        logger.info('    FB 页面解析失败：%s' % e)
        return None


def get_detail(url):
    """打开这个 Facebook 链接，返回 {addr, emails, phones}；打不开返回 None。

    只访问传入的这一个链接，不打开任何子页或标签页。
    页面里有什么就取什么，取不到就是空，由上层决定如何处理。
    """
    if not G.goto_fast(url):
        return None

    data = _grab_page()
    if data is None:
        return {'addr': '', 'emails': [], 'phones': []}

    emails, phones, addr = _extract_contacts(data)

    # 每个主页解析出多少条，直接打出来 —— 全都是空就说明选择器/页面结构
    # 变了，不用等整批跑完才发现一条都没采到。
    if not emails and not phones:
        logger.info('    解析：暂无数据（地址%s）'
                    % ('有' if addr else '无'))
    else:
        logger.info('    解析：邮箱 %d 个 / 电话 %d 个 / 地址 %s'
                    % (len(emails), len(phones), '有' if addr else '无'))

    return {'addr': addr, 'emails': emails, 'phones': phones}


def country_from_address(addr, phones=None):
    """从 Facebook 上的地址文字判断国家；判断不出来返回空串。

    先用 google.detect_country（它认得省+邮编、州全称、ICP 备案号这些结构特征），
    再用国名匹配兜底 —— 像 "Berlin, Germany" 这种纯「城市, 国家」写法，
    google 的结构规则认不出来，只能靠国名表。
    """
    text = (addr or '').strip()
    if text:
        hit = G.detect_country(text)
        if hit:
            return hit
        tail = re.split(r'[,，]', text)[-1].strip()
        hit = G.match_country_name(tail) or G.match_country_name(text)
        if hit:
            return hit
    # 地址没写清时，国际区号也能说明国家
    return G.country_from_phone(phones or [])


# ==================== 采集主流程 ====================
def crawl(keyword, proxy=None, max_sites=None, out_file=None):
    """采集单个关键词：搜索 -> 逐个打开主页 -> 写 xlsx（一条一落盘）。

    返回本次新增到结果表的条数。
    """
    out_file = out_file or os.path.join(G.BASE_DIR, G.OUT_NAME)
    out_dir = os.path.dirname(os.path.abspath(out_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 两个外部文件都放在 exe（或脚本）同级目录，用户可随时打开查看/编辑
    ensure_config_template()
    logger.info('结果表：%s' % out_file)
    logger.info('配置文件：%s' % CONFIG_FILE)

    # 先把表准备好：即使一条都没采到也留下带表头的文件
    wb, ws, existing = G.open_workbook(out_file)

    if not G.ensure_browser(proxy):
        logger.error('【FB】浏览器启动失败')
        return 0
    if not login():
        return 0

    pairs = search(keyword, max_results=max_sites)
    if not pairs:
        logger.warning('关键词「%s」没有搜到任何 Facebook 主页' % keyword)
        return 0

    total = len(pairs)
    saved = 0
    skipped_no_contact = []
    skipped_existing = []
    written_keys = set()
    visited = set()
    # existing 里的键本来就是 normalize_url 的结果，这里直接拿来比。
    existing_links = set(u for _k, u in existing)

    def key_of(link):
        """去重键：统一走 G.normalize_url，保证和写表/读表用的是同一套规则。

        Facebook 的 www./m./web. 前端、用户名大小写、末尾斜杠、追踪参数
        都会在这里被归一，所以同一主页的不同写法不会重复采集。
        """
        return G.normalize_url(link)

    logger.info('【FB】开始逐个访问 %d 个主页' % total)

    for idx, (name, url) in enumerate(pairs, 1):
        if G.stop_requested():
            logger.warning('已停止，剩余 %d 个主页未访问' % (total - idx + 1))
            break

        logger.info('[%d/%d] %s' % (idx, total, url))
        G.report_progress('sites', idx, total,
                          '访问第 %d/%d 个' % (idx, total))

        # 与结果表去重：表里已有这条链接就跳过（比较用归一化键，
        # 这样 m./www./web. 前端、大小写、末尾斜杠、追踪参数都算同一链接）。
        if G.SKIP_EXISTING_LINKS and key_of(url) in existing_links:
            logger.info('    跳过（结果表里已有这个链接）')
            skipped_existing.append(url)
            continue

        # 本次会话内也去重（搜索页可能返回同一主页的不同前端地址）
        if key_of(url) in visited:
            logger.info('    跳过（本次已访问过）')
            continue
        visited.add(key_of(url))

        detail = None
        try:
            detail = get_detail(url)
        except Exception as e:               # noqa: BLE001
            # 单个主页出问题不能打断整批
            logger.error('访问异常 %s：%s' % (url, e))
            if getattr(PlayWright, 'page', None) is None:
                logger.warning('浏览器已失效，重置后继续')
                try:
                    G.reset_browser()
                    G.ensure_browser(proxy)
                except Exception:            # noqa: BLE001
                    pass

        if detail is None:
            logger.info('    跳过（页面没打开）')
            continue

        emails = list(detail.get('emails') or [])
        phones = list(detail.get('phones') or [])
        addr = detail.get('addr') or ''
        country = country_from_address(addr, phones)

        rec = {
            'keyword': keyword,
            'country': country,
            'site_name': name or url,
            'url': url,
            'emails': emails,
            'phones': phones,
            'origin': G.SOURCE_FACEBOOK,     # 结果表「来源」列
        }

        written = False
        key = (keyword, key_of(url))
        # 只要访问过就写入（WRITE_NO_CONTACT=True）；关掉开关时才按有无联系方式过滤。
        if not (emails or phones) and not G.WRITE_NO_CONTACT:
            if url not in skipped_no_contact:
                skipped_no_contact.append(url)
            logger.info('    跳过（未采到电话/邮箱）')
        elif key in existing or key in written_keys:
            logger.info('    跳过（结果表里已有这个链接）')
        else:
            G.save_records(wb, ws, out_file, [rec])
            written_keys.add(key)
            saved += 1
            written = True
            found = []
            if phones:
                found.append('电话 %d 个' % len(phones))
            if emails:
                found.append('邮箱 %d 个' % len(emails))
            if country:
                found.append('国家 %s' % country)
            logger.info('    汇总：%s'
                        % ('、'.join(found) if found else '暂无数据（已按访问记录写入）'))

        G.report_record({
            'keyword': keyword,
            'url': url,
            'title': name or '',
            'site_name': name or '',
            'country': country,
            'emails': emails,
            'phones': phones,
            'source': 'facebook',
            'origin': G.SOURCE_FACEBOOK,
            'written': written,
        })

        if idx < total:
            time.sleep(random.uniform(*PAGE_DELAY))

    # 被跳过（表里已有）的链接也要在界面上标出来，否则会一直停在「待采集」
    for url in skipped_existing:
        G.report_record({
            'keyword': keyword, 'url': url, 'title': '', 'site_name': '',
            'country': '', 'emails': [], 'phones': [],
            'source': 'skip', 'written': False,
        })

    if skipped_no_contact:
        logger.info('以下 %d 个主页因未采到电话/邮箱，未写入结果表：'
                    % len(skipped_no_contact))
        for u in skipped_no_contact[:20]:
            logger.info('    %s' % u)
        if len(skipped_no_contact) > 20:
            logger.info('    ...（共 %d 个）' % len(skipped_no_contact))

    logger.info('关键词「%s」Facebook 本次新增 %d 条记录（访问主页 %d 个）'
                % (keyword, saved, len(visited)))
    G.report_progress('keyword_done', saved, saved,
                      '关键词完成，新增 %d 条' % saved)
    return saved


# ==================== 命令行 ====================
def main(argv=None):
    """命令行入口（图形界面请用 run.py）。"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Facebook 关键词采集：搜索群组/主页并提取地址(国家) / 电话 / 邮箱')
    parser.add_argument('-k', '--keywords',
                        help='关键词，多个用逗号分隔')
    parser.add_argument('-p', '--proxy',
                        help='代理地址，如 127.0.0.1:7892')
    parser.add_argument('--no-proxy', action='store_true',
                        help='不使用代理')
    parser.add_argument('--max-sites', type=int, default=None,
                        help='每个关键词最多访问多少个主页（默认 %d）' % MAX_RESULTS)
    parser.add_argument('-o', '--out', default=None,
                        help='结果文件路径（默认 %s）' % G.OUT_NAME)
    args = parser.parse_args(argv)

    keyword = (args.keywords or input('请输入关键词（多个用英文逗号分隔）：')).strip()
    if not keyword:
        print('关键词不能为空')
        return 1

    if args.no_proxy:
        proxy = None
    elif args.proxy:
        proxy = {'server': 'http://%s' % args.proxy.strip()}
    else:
        proxy = None

    out_file = (os.path.abspath(args.out) if args.out
                else os.path.join(G.BASE_DIR, G.OUT_NAME))
    keywords = [k.strip() for k in re.split(r'[,，]', keyword) if k.strip()]

    total = 0
    for kw in keywords:
        logger.info('=' * 50)
        logger.info('开始采集关键词：%s' % kw)
        try:
            total += crawl(kw, proxy=proxy, max_sites=args.max_sites,
                           out_file=out_file)
        except G.BROWSER_ERRORS as e:
            logger.error('关键词「%s」采集失败：%s' % (kw, e))
        time.sleep(random.uniform(*SEARCH_DELAY))

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
        except Exception:                # noqa: BLE001
            pass
