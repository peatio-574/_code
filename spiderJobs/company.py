# coding='utf-8'
"""智联招聘 —— 按公司名称采集岗位（全量）。

本文件完全自包含：不依赖 zhipin.py / getJobs.py，
只需要同目录上一级的 Logger.py / Config.py（其它采集器也共用这两个）。

数据来源：`A股2021年新上市公司.xlsx` 里的「股票简称」列。
对每家公司：用公司名在智联搜索接口检索 -> 逐页翻到末页 -> 只保留公司名匹配的岗位
-> 按岗位编号去重 -> 增量写入 xlsx。

为什么这么做（实测结论）：
  * 智联没有可匿名访问的「公司维度岗位接口」，公司主页需要登录且会跳回首页，
    所以只能走搜索接口 `POST /c/i/search/positions`。
  * 搜索是「全文匹配」，会把职位描述里提到该公司名的其它公司岗位也带出来，
    因此必须按 companyName 再过滤一遍。
  * 接口 pageSize 上限 20（传 50/100 也只回 20 条），要拿全量只能逐页翻。
  * 翻页上限约 50 页（≈1000 条）后 isEndPage=1；对这批复牌的小公司完全够用。
  * 列表接口已内联 jobDetailData（含完整职位描述、学历、经验、薪资），
    不需要再单独抓详情页。
  * 请求体里的 anonymous 必须为 1：设成 0 会直接触发风控
    （isVerification=1、返回 0 条），即使带着有效 cookie 也一样。

用法：
    python company.py                # 不带参数 -> 打开图形界面
    python company.py --gui          # 显式打开图形界面

    python company.py --cli                            # 命令行采集全部公司
    python company.py --cli --limit 5                  # 只跑前 5 家（试跑）
    python company.py --cli --company "中瓷电子,祖名股份"  # 只跑指定公司
    python company.py --cli --file 公司列表.xlsx         # 换一份公司清单
    python company.py --cli --out 结果.xlsx             # 指定输出文件
    python company.py --cli --force                    # 强制重新登录
"""
import argparse
import json
import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime
from html import unescape as html_unescape
from tkinter import ttk

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Logger import logger

try:
    from patchright.sync_api import sync_playwright
except ImportError:                                    # 未装 patchright 时回退
    from playwright.sync_api import sync_playwright


# ==================== 基础常量 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认公司清单（程序同级的 A股2021年新上市公司.xlsx，取「股票简称」列）
DEFAULT_COMPANY_FILE = 'A股2021年新上市公司.xlsx'
DEFAULT_OUTPUT_FILE = '智联公司岗位.xlsx'
COMPANY_COLUMNS = ('股票简称', '公司简称', '证券简称', '简称', '公司名称')

# 输出表的列（与原智联采集器完全一致，便于两张表合并）
HEADERS = [
    '采集日期', '来源', '省份', '城市',
    '职位名称', '岗位编号', '公司名称', '公司性质', '公司规模', '公司行业',
    '招聘类型', '职位性质', '职位类别', '薪资范围', '招聘人数',
    '学历要求', '经验要求', '专业要求', '工作地点', '详细地址',
    '报名截止', '职位描述',
]
SOURCE_NAME = '智联招聘'

# 工作表名：主表放岗位，副表记录「哪些公司已经完整采过」
SHEET_JOBS = '职位数据'
SHEET_CRAWLED = '已爬取公司'
CRAWLED_HEADERS = ['公司名称', '新增岗位数', '完成时间']

# 岗位字段顺序（对应 HEADERS 的第 4 列起）
ROW_ORDER = [
    '城市', '职位名称', '岗位编号', '公司名称', '公司性质', '公司规模',
    '公司行业', '招聘类型', '职位性质', '职位类别', '薪资范围', '招聘人数',
    '学历要求', '经验要求', '专业要求', '工作地点', '详细地址',
    '报名截止', '职位描述',
]
# 「岗位编号」在整行里的下标（0-based），去重靠它
ID_INDEX = HEADERS.index('岗位编号')

# ==================== 采集参数 ====================
MAX_PAGES = 200              # 单公司最多翻多少页（20 条/页）；实际靠 isEndPage 结束
PAGE_DELAY = (0.6, 1.2)      # 每页之间的随机间隔（秒）
COMPANY_DELAY = (1.2, 2.4)   # 两家公司之间的间隔
API_TIMEOUT = 20
MAX_EMPTY_PAGES = 2          # 连续几页没匹配到目标公司就提前收工
LOGIN_TIMEOUT = 300          # 登录等待上限（秒），够手动收短信了

API = 'https://fe-api.zhaopin.com/c/i/search/positions'

# 登录态与 zhipin.py 共用同一个 config.ini 配置项，两边可互换使用
CONFIG_FILE_NAME = 'config.ini'
CONFIG_SECTION = 'login'
CONFIG_OPTION = 'zhipin_cookie'

# ==================== 请求头 ====================
_HTTP_HEADERS = {
    'content-type': 'application/json;charset=UTF-8',
    'accept': 'application/json, text/plain, */*',
    'x-zp-business-system': '1',
    'x-zp-page-code': '4089',
    'x-zp-platform': '13',
    'origin': 'https://www.zhaopin.com',
    'referer': 'https://www.zhaopin.com/',
    'user-agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/131.0.0.0 Safari/537.36'),
}


def _config_path():
    """config.ini 的绝对路径（程序同级目录）。"""
    return os.path.join(BASE_DIR, CONFIG_FILE_NAME)


# ==================== 登录态（config.ini） ====================
def load_cookie_list():
    """从 config.ini 读取 cookie 列表；没有或损坏时返回空列表。"""
    import ast
    try:
        from Config import get_config_value
        raw = (get_config_value(CONFIG_SECTION, CONFIG_OPTION,
                               file=_config_path()) or '').strip()
    except Exception as e:                 # noqa: BLE001
        logger.warning('【按公司】读取 config.ini 失败：%s' % e)
        return []
    if not raw:
        return []
    try:
        cookies = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(cookies, list):
        return []
    return [c for c in cookies if isinstance(c, dict) and c.get('name')]


def load_cookie():
    """读出请求头用的 cookie 字符串（`k=v; k=v`）。

    优先用 zhipin_cookie_api（已经是拼接好的形式）；
    没有时退回解析 zhipin_cookie 列表，两种存法都能用。
    """
    try:
        from Config import get_config_value
        api = (get_config_value(CONFIG_SECTION, CONFIG_OPTION + '_api',
                               file=_config_path()) or '').strip()
        if api:
            return api
    except Exception:                      # noqa: BLE001
        pass
    cookies = load_cookie_list()
    return '; '.join('%s=%s' % (c.get('name'), c.get('value'))
                     for c in cookies if c.get('name'))


def save_cookies(cookies):
    """把 cookie 写回 config.ini（同时存一份 api 串）。"""
    try:
        from Config import write_config_value
        zp = [c for c in (cookies or [])
              if 'zhaopin' in (c.get('domain') or '')]
        if not zp:
            logger.warning('【按公司】登录后没有智联 cookie，未写入 config.ini')
            return False
        api = '; '.join('%s=%s' % (c.get('name'), c.get('value')) for c in zp)
        write_config_value(CONFIG_SECTION,
                           {CONFIG_OPTION: str(zp),
                            CONFIG_OPTION + '_api': api},
                           file=_config_path())
        logger.info('【按公司】已保存 %d 条 cookie 到 config.ini' % len(zp))
        return True
    except Exception as e:                 # noqa: BLE001
        logger.error('【按公司】写入 config.ini 失败：%s' % e)
        return False


def has_login():
    """config.ini 里是否已有看起来有效的登录态。"""
    cookie = load_cookie()
    if not cookie:
        return False
    return any(k in cookie for k in ('at=', 'x_passport_sid=', 'rt='))


# ==================== 浏览器登录 ====================
def _find_browser(pw):
    """依次尝试系统 Edge / Chrome / 内置 Chromium，返回 (browser, channel)。"""
    last_err = None
    for channel in ('msedge', 'chrome', None):
        kwargs = {'headless': False}
        if channel:
            kwargs['channel'] = channel
        try:
            logger.info('【按公司】启动浏览器：%s' % (channel or '内置 Chromium'))
            return pw.chromium.launch(**kwargs), channel
        except Exception as e:             # noqa: BLE001
            last_err = e
            logger.info('【按公司】%s 启动失败：%s'
                        % (channel or '内置', str(e)[:120]))
    raise RuntimeError('未找到可用浏览器（Edge / Chrome / Chromium）：%s'
                       % last_err)


def _page_logged_in(page, context):
    """判断当前是否已登录。

    命中任一即认为「已登录」：
      · 登录页的手机号输入框已经消失
      · cookie 里出现了鉴权 token（at）
    只要还停在 login 页且手机号框还在，就当作未登录。
    """
    try:
        if page.locator('input[placeholder="手机号"]').count():
            return False
    except Exception:                      # noqa: BLE001
        pass
    try:
        url = (page.url or '').lower()
        if 'passport.zhaopin.com/login' in url:
            return False
    except Exception:                      # noqa: BLE001
        pass
    try:
        for c in context.cookies():
            if c.get('name') == 'at' and (c.get('value') or '').strip():
                return True
    except Exception:                      # noqa: BLE001
        pass
    return True


def _wait_eo_pass(page, timeout=180):
    """等待智联的安全验证页（Security Verification）消失。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if 'Security Verification' not in (page.title() or ''):
                return True
        except Exception:                  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
    return False


def _check_agreement(page):
    """勾选登录页的用户协议 / 隐私政策复选框。"""
    sel = 'input[type="checkbox"], [role="checkbox"]'
    try:
        n = page.locator(sel).count()
    except Exception:                      # noqa: BLE001
        n = 0
    if n == 0:
        return True
    cb = page.locator(sel).first
    try:
        if cb.is_checked():
            return True
    except Exception:                      # noqa: BLE001
        pass
    try:
        cb.click(force=True, timeout=5000)
        page.wait_for_timeout(300)
        return True
    except Exception as e:                 # noqa: BLE001
        logger.info('[登录] 勾选协议失败：%s' % str(e)[:80])
        return False


def _click_button(page, *selectors):
    """依次尝试点击多个选择器命中的按钮，成功返回 True。"""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=8000)
                return True
        except Exception:                  # noqa: BLE001
            continue
    return False


def browser_login(ask=input, phone='', timeout=LOGIN_TIMEOUT):
    """自动登录智联，成功后返回 cookie 字符串。

    与 zhipin.py 的登录流程一致：
      1. 注入 config.ini 里已有的 cookie（可能还有效）
      2. 打开 sou.zhaopin.com 过安全验证（如有滑块请在窗口完成）
      3. 打开登录页，已有登录态则直接复用
      4. 否则自动填手机号 + 短信验证码（手机号/验证码通过 ask 对话框获取）
      5. 登录成功 -> 保存 cookie -> 关闭浏览器
    """
    with sync_playwright() as pw:
        browser, _channel = _find_browser(pw)
        context = browser.new_context(
            locale='zh-CN',
            viewport={'width': 1360, 'height': 900},
        )
        try:
            old = load_cookie_list()
            if old:
                try:
                    context.add_cookies(old)
                    logger.info('【按公司】已注入 %d 条已有 cookie' % len(old))
                except Exception as e:     # noqa: BLE001
                    logger.info('【按公司】注入 cookie 失败：%s' % str(e)[:80])

            page = context.new_page()

            # 先过安全验证
            logger.info('[登录] 打开 sou.zhaopin.com 过安全验证……')
            try:
                page.goto('https://sou.zhaopin.com/', timeout=60000)
            except Exception as e:         # noqa: BLE001
                logger.info('[登录] 打开 sou 失败：%s' % str(e)[:80])
            if not _wait_eo_pass(page, 30):
                logger.info('[登录] 如出现滑块/勾选，请在浏览器窗口手动完成……')
                _wait_eo_pass(page, 120)

            # 打开登录页
            logger.info('[登录] 打开登录页……')
            try:
                page.goto('https://passport.zhaopin.com/login', timeout=60000)
                page.wait_for_timeout(2500)
            except Exception as e:         # noqa: BLE001
                logger.warning('[登录] 打开登录页失败：%s' % str(e)[:80])

            if _page_logged_in(page, context):
                logger.info('[登录] 检测到已有登录态，跳过短信验证')
                cookies = context.cookies()
                save_cookies(cookies)
                return load_cookie()

            # 等手机号输入框渲染
            try:
                page.wait_for_selector('input[placeholder="手机号"]',
                                       timeout=60000)
            except Exception as e:         # noqa: BLE001
                logger.warning('[登录] 未找到手机号输入框：%s' % str(e)[:80])

            if not phone:
                phone = (ask('请输入智联绑定手机号：') or '').strip()
            if not phone:
                logger.error('[登录] 手机号为空，无法登录')
                return ''

            try:
                page.fill('input[placeholder="手机号"]', phone)
            except Exception as e:         # noqa: BLE001
                logger.warning('[登录] 填写手机号失败：%s' % str(e)[:80])

            _check_agreement(page)

            if not _click_button(
                    page, 'button:has-text("获取验证码")',
                    'button:has-text("获取 验证码")',
                    'button:has-text("验证码")',
                    'a:has-text("获取验证码")'):
                logger.info('[登录] 未能定位「获取验证码」按钮，请在窗口手动获取。')

            logger.info('[登录] 已请求短信验证码，请查收手机短信'
                        '（如弹滑块请在窗口完成）')

            # 等验证码框出现（短信已发出）
            try:
                page.wait_for_selector('input[placeholder*="验证码"]',
                                       timeout=60000)
            except Exception:              # noqa: BLE001
                pass

            code = (ask('请输入短信验证码：') or '').strip()
            sms_sel = 'input[placeholder="短信验证码"]'
            try:
                if not page.locator(sms_sel).count():
                    alt = page.locator('input[placeholder*="验证码"]').first
                    if alt.count():
                        sms_sel = 'input[placeholder*="验证码"]'
            except Exception:              # noqa: BLE001
                pass
            try:
                page.fill(sms_sel, code)
            except Exception:              # noqa: BLE001
                pass

            _check_agreement(page)
            if not _click_button(
                    page, 'button:has-text("登录/注册")',
                    'button:has-text("立即登录")',
                    'button:has-text("登 录")',
                    'button:has-text("登录")'):
                logger.info('[登录] 未能定位登录按钮，请在窗口手动点击登录。')

            logger.info('[登录] 已提交，等待登录成功……')
            confirmed = False
            deadline = time.time() + 30
            while time.time() < deadline:
                page.wait_for_timeout(1000)
                try:
                    if page.locator('input[placeholder="手机号"]').count() == 0:
                        confirmed = True
                        break
                except Exception:          # noqa: BLE001
                    pass
                try:
                    if 'passport.zhaopin.com/login' not in page.url:
                        confirmed = True
                        break
                except Exception:          # noqa: BLE001
                    pass

            if not confirmed:
                logger.error('[登录] 未能确认登录成功，请检查浏览器窗口后重试')
                return ''

            logger.info('[登录] 登录成功')
            cookies = context.cookies()
            if not save_cookies(cookies):
                logger.error('[登录] 登录成功但保存 cookie 失败')
                return ''
            cookie = load_cookie()
            logger.info('[登录] cookie 长度 %d' % len(cookie))
            return cookie
        finally:
            try:
                context.close()
            except Exception:              # noqa: BLE001
                pass
            try:
                browser.close()
            except Exception:              # noqa: BLE001
                pass


def prepare_login(ask=input, force=False, phone=''):
    """确保有可用的登录 cookie，返回 (成功?, cookie)。"""
    if not force and has_login():
        logger.info('【按公司】检测到已保存的登录态，直接复用'
                    '（如需重新登录请勾选「强制重新登录」或加 --force）')
        return True, load_cookie()
    try:
        cookie = browser_login(ask=ask, phone=phone)
    except Exception as e:                 # noqa: BLE001
        logger.error('【按公司】登录异常：%s' % e)
        return False, ''
    if not cookie:
        return False, ''
    return True, cookie


# ==================== 文本清洗与字段解析 ====================
def clean_html(s):
    """去除 HTML 标签，保留段落换行，HTML 实体反转义。"""
    if not s:
        return ''
    s = str(s)
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</(p|div|li|ul|ol|h[1-6]|tr|table|section)>', '\n', s)
    s = re.sub(r'(?i)<(p|div|li|ul|ol|h[1-6]|tr|table|section)[^>]*>', '', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html_unescape(s)
    lines = [ln.strip() for ln in s.splitlines()]
    return '\n'.join(ln for ln in lines if ln)


# ---------- 专业要求抽取 ----------
# 智联搜索接口没有结构化的「专业要求」字段（needMajor 恒为空），
# 专业要求只存在于职位描述文本里，这里按常见写法做启发式提取。
_MAJOR_NOT_EXACT = set(
    '管理 技术 设计 工程 学科 专业 知识 能力 技能 培训 团队 服务 咨询 经验 '
    '工作 运营 发展 实践 相关 优先 学历 本科 大专 要求'.split())
_MAJOR_NOT_SUFFIX = (
    '知识', '能力', '技能', '培训', '团队', '服务', '咨询', '讲解', '介绍',
    '素养', '水平', '评估', '测试', '顾问', '机构', '岗位', '课程', '方案',
    '建议', '指导', '风险', '认知', '职责', '人员', '精神', '理解', '素质',
    '经验', '运营', '成长', '实践', '形象', '术语', '词汇', '文书',
    '面试', '回答', '答辩', '训练', '协同', '分包', '优先', '以及', '背景')
_MAJOR_HINT = (
    '学', '工程', '科学', '管理', '技术', '信息', '医学', '教育', '经济', '金融',
    '会计', '财务', '设计', '电子', '机械', '材', '化学', '生物', '计算机', '软件',
    '通信', '自动化', '建筑', '土木', '车辆', '能源', '动力', '制药', '药学', '营销',
    '传播', '法学', '法律', '农', '畜牧', '兽医', '环境', '安全', '工业', '物流',
    '贸易', '英语', '语', '美术', '视觉', '动画', '艺术', '新闻', '政治', '国际',
    '统计', '数学', '物理', '地理', '地质', '测绘', '测控', '仪器', '电气', '电力',
    '物联网', '网络', '智能', '数据', '分析', '审计', '税务', '工商', '行政', '人力',
    '护理', '临床', '中医', '中药', '机电', '烹饪', '食品', '纺织', '服装',
    '广告', '旅游', '酒店', '供应链', '冶金', '矿业', '石油', '海')
_MAJOR_LEAD = re.compile(
    r'^(?:\s*(?:任职要求|岗位要求|职位要求|任职资格|应聘要求|资格要求|人员要求|招聘要求|'
    r'学历要求|教育背景|教育经历|专业要求|专业方向|专业类别|所学专业|专业|要求|'
    r'统招|全日制|正规院校|国家|省属|重点|一本|二本|三本|985|211|'
    r'本科|大专|专科|硕士|博士|研究生|中专|高中|初中|毕业|应届|在校|学生|'
    r'及以上|以上|以下|学历|学位|具有|具备|优先|均可|即可|相关|其他|以及|\d+|'
    r'[（(][^）)]*[）)])\s*[,，、;；:：.。\-—/]?\s*)+')


def _tidy_major(cand):
    cand = cand.strip(' 　，,、;；:：/')
    cand = re.sub(r'(?:等)?(?:相关)?专业.*$', '', cand)
    cand = re.sub(r'(?:等|或|和|与|及|、)?\s*(?:相关|其它|其他|类似).*$', '', cand)
    cand = re.sub(r'(?:等|及|和|与|或|其他|其它|、|，|,|/|·|-|—|的)+$', '', cand).strip()
    cand = re.sub(r'(?:优先|者优先|均可|不限|即可).*$', '', cand).strip()
    cand = _MAJOR_LEAD.sub('', cand)
    cand = re.sub(r'^[的或及和与相关、，,;；:：/-—]+', '', cand)
    return cand.strip(' 　，,、;；:：/')


def _looks_like_major(cand):
    if not cand or len(cand) > 80:
        return False
    toks = [t.strip() for t in re.split(r'[、，,/]|及|和|与|或', cand) if t.strip()]
    for t in toks:
        if t in _MAJOR_NOT_EXACT:
            continue
        if any(t.endswith(w) for w in _MAJOR_NOT_SUFFIX):
            continue
        if any(h in t for h in _MAJOR_HINT):
            return True
    return False


def extract_major(text):
    """从职位描述中提取「专业要求」；提取不到返回空串（调用方回退为「不限」）。"""
    if not text:
        return ''
    t = clean_html(text)
    # 1) 「专业要求：xxx / 专业：xxx」等显式标签
    for m in re.finditer(
            r'(?:所学专业|专业要求|专业方向|专业类别|专业背景|专业)\s*[:：]\s*([^\n]{1,80})', t):
        raw = m.group(1)
        if '不限' in raw:
            return '不限'
        cand = _tidy_major(raw)
        if _looks_like_major(cand):
            return cand
    # 2) 「专业不限 / 不限专业」
    if re.search(r'专业\s*不?\s*限|不限专业', t) \
            or re.search(r'专业[、，,][^，,。；;\n]{0,8}不限', t):
        return '不限'
    # 3) 「xx、yy等相关专业」列表
    for m in re.finditer(r'([^，,。；;：:\n]{2,80}?)(?:等)?(?:相关)?专业', t):
        cand = _tidy_major(m.group(1))
        if _looks_like_major(cand):
            tail = t[m.end():m.end() + 6]
            if any(w in tail for w in ('知识', '技能', '能力', '术语', '词汇')):
                continue
            return cand
    return ''


# ---------- 学历抽取 ----------
# 列表接口在不同卡片类型（登录/推荐/广告位）下字段位置不一致：
# 有时只在顶层 education，有时只在 jobDetailData.position.base.education，
# 偶尔两者都缺，只能从职位描述里提取。这里按多来源兜底。
_EDU_KEYS = ('education', 'educationName', 'degreeName', 'degree',
             'educationCn', 'educationLevel')
_EDU_DESC_PATTERNS = (
    r'(?:学历要求|学历|最低学历|教育背景)\s*[:：]\s*([^\n，,。；;]{1,20})',
    r'(博士|硕士|本科|大专|专科|中专|高中|初中|学历不限|不限学历)',
)
_EDU_LEVELS = ('博士', '硕士', '本科', '大专', '专科', '中专', '高中', '初中')
_edu_warned = False


def _first_text(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def extract_education(text):
    """从职位描述中提取学历要求；提取不到返回空串。"""
    if not text:
        return ''
    body = clean_html(text)
    for pattern in _EDU_DESC_PATTERNS:
        matched = re.search(pattern, body)
        if not matched:
            continue
        raw = matched.group(1) if matched.groups() else matched.group(0)
        if '不限' in raw:
            return '不限'
        for level in _EDU_LEVELS:
            if level in raw:
                return '大专' if level == '专科' else level
    return ''


def normalize_education(value):
    text = (value or '').strip()
    if not text:
        return ''
    if '不限' in text:
        return '不限'
    for level in _EDU_LEVELS:
        if level in text:
            return '大专' if level == '专科' else level
    return text


def _warn_missing_education(it):
    """首次遇到学历缺失时记录一条明细，便于排查接口字段变化。"""
    global _edu_warned
    if _edu_warned:
        return
    _edu_warned = True
    logger.warning('【按公司】学历要求字段缺失，jobId=%s，jdCardType=%s，顶层字段=%s'
                   % (it.get('jobId'), it.get('jdCardType'),
                      ','.join(sorted(it.keys()))[:500]))


def item_to_row(it):
    """把接口返回的单条岗位整理成字段字典（键见 ROW_ORDER）。"""
    jd = it.get('jobDetailData') or {}
    position = jd.get('position') or {}
    pb = position.get('base') or {}
    dt = position.get('date') or {}
    de = position.get('desc') or {}
    jt = position.get('jobType') or {}

    city = it.get('workCity') or ''
    district = it.get('cityDistrict') or ''
    work_place = ('%s-%s' % (city, district)) if district else city

    # ---------- 学历 ----------
    edu = _first_text(*(it.get(k) for k in _EDU_KEYS),
                      *(pb.get(k) for k in _EDU_KEYS))
    if not edu:
        edu = extract_education(de.get('description') or it.get('jobSummary') or '')
    if not edu:
        _warn_missing_education(it)
    edu = normalize_education(edu) or '不限'

    exp = _first_text(it.get('workingExp'), pb.get('positionWorkingExp'),
                      pb.get('workingExp')) or '不限'

    # ---------- 薪资 ----------
    # 优先级：salaryReal（结构化区间）> salary60（展示文案）> salary
    # 智联部分岗位只给「面议」，直接落到 0~0 会让数据看起来像异常，
    # 这里统一规范化为「面议」。
    salary_text = ''
    raw_salary = it.get('salaryReal') or pb.get('salaryReal') or ''
    matched = re.match(r'\s*(\d+)\s*[-~至]\s*(\d+)', str(raw_salary))
    if matched:
        low, high = int(matched.group(1)), int(matched.group(2))
        salary_text = '%s~%s 元/月' % (low, high)
    else:
        text_salary = (it.get('salary60') or pb.get('salary') or '').strip()
        m2 = re.search(r'(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*[kK千万]?',
                       text_salary)
        if m2:
            salary_text = text_salary
        elif text_salary and re.search(r'面议|商议|谈判|保密', text_salary):
            salary_text = '面议'
        elif text_salary and not re.fullmatch(r'0+[-~至]0+.*', text_salary):
            salary_text = text_salary
        else:
            salary_text = '面议'
    if re.fullmatch(r'\s*0+\s*~\s*0+\s*(元/月)?\s*', salary_text):
        salary_text = '面议'

    work_type = it.get('workType') or pb.get('workType') or ''
    is_intern = '实习' in work_type or (it.get('internshipMonths') or 0) > 0
    # 招聘类型：实习 / 校园招聘 / 社会招聘
    if is_intern:
        recruit_type = '实习'
    elif it.get('campusJobDetail') or '校' in work_type:
        recruit_type = '校园招聘'
    else:
        recruit_type = '社会招聘'
    # 职位性质：全职 / 兼职 / 实习
    if '兼职' in work_type:
        nature = '兼职'
    elif is_intern:
        nature = '实习'
    else:
        nature = '全职'

    # ---------- 专业 ----------
    major_items = it.get('needMajor') or []
    major = ''
    if isinstance(major_items, list) and major_items:
        major = '、'.join(
            item.get('name') if isinstance(item, dict) else str(item)
            for item in major_items if item)
    if not major:
        major = extract_major(de.get('description') or it.get('jobSummary') or '')
    if not major:
        major = '不限'

    recruit = int(it.get('recruitNumber') or 0) or int(pb.get('recruitNumber') or 0)
    recruit_text = str(recruit) if recruit > 0 else '若干'
    cat = it.get('subJobTypeLevelName') or jt.get('subJobTypeLevelName') or '不限'

    addr = ''
    card = it.get('cardCustomJson')
    if isinstance(card, str):
        try:
            addr = json.loads(card).get('address') or ''
        except Exception:                  # noqa: BLE001
            addr = ''

    row = {
        '城市': city,
        '职位名称': it.get('name') or pb.get('positionName') or '',
        '岗位编号': str(it.get('jobId') or it.get('positionId') or ''),
        '公司名称': it.get('companyName') or '',
        '公司性质': it.get('propertyName') or it.get('property') or '不限',
        '公司规模': it.get('companySize') or '不限',
        '公司行业': it.get('industryName') or '不限',
        '招聘类型': recruit_type,
        '职位性质': nature,
        '职位类别': cat,
        '薪资范围': salary_text,
        '招聘人数': recruit_text,
        '学历要求': edu,
        '经验要求': exp,
        '专业要求': major,
        '工作地点': work_place,
        '详细地址': addr,
        '报名截止': dt.get('dateEnd') or '长期有效',
        '职位描述': (de.get('description') or it.get('jobSummary') or '').strip(),
    }
    return {k: (clean_html(v) if isinstance(v, str) else v)
            for k, v in row.items()}


# ==================== 公司名匹配 ====================
# 公司名归一化时剔除的通用词。目的是让「中瓷电子」能匹配
# 「河北中瓷电子科技股份有限公司」这类带地名/组织形式的全称。
_CORP_WORDS = (
    '股份有限公司', '有限责任公司', '有限公司', '股份公司', '集团公司',
    '控股集团', '集团', '控股', '股份', '公司',
    '科技', '技术', '实业', '发展', '投资', '产业', '企业',
)
# 股票简称里常见、但对「是不是同一家」没有区分度的行业词，
# 只在「直接包含」匹配失败时，才用「去行业词后的品牌词」再试一次。
_INDUSTRY_WORDS = (
    '医疗', '医药', '生物', '电子', '科技', '智能', '材料', '新材',
    '环保', '能源', '电力', '化工', '装备', '机械', '汽车', '食品',
    '软件', '信息', '网络', '数据', '通信', '半导体', '光电',
)


def norm_name(text):
    """公司名归一化：去空白/全角括号/标点，转小写。"""
    s = str(text or '')
    s = s.replace('\u3000', ' ').replace('\xa0', ' ')
    s = re.sub(r'[\s\(\)（）\[\]【】<>《》「」"\'·,，.。;；:：/\\\-—_*#&]+', '', s)
    return s.lower()


def _strip_words(text, words):
    s = text
    for w in words:
        s = s.replace(w.lower(), '')
    return s


def name_matches(target, company):
    """判断智联返回的公司名是不是要采集的那一家。

    三层匹配（从严到宽）：
      1. 归一化后直接包含 —— 处理「中瓷电子」vs「河北中瓷电子科技股份有限公司」
      2. 去掉公司后缀（股份/有限/公司/集团…）后再包含
      3. 再去掉行业通用词（医疗/电子/科技…）后用品牌词匹配

    第 3 层是最后兜底，因此额外要求品牌词长度 >= 2，
    避免「医疗」「科技」这种短词把不相干的公司全捞进来。
    """
    t = norm_name(target)
    c = norm_name(company)
    if not t or not c:
        return False
    if t in c:
        return True
    t2 = _strip_words(t, _CORP_WORDS)
    if t2 and t2 in c:
        return True
    t3 = _strip_words(t2, _INDUSTRY_WORDS)
    if len(t3) >= 2 and t3 in c:
        return True
    # 反过来：智联登记的是简称，清单里给的是长名
    c2 = _strip_words(c, _CORP_WORDS)
    return bool(c2) and len(c2) >= 2 and c2 in t


# ==================== 公司清单 ====================
def company_file_path(path=None):
    """公司清单文件的绝对路径。"""
    if path and os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path or DEFAULT_COMPANY_FILE)


def load_companies(path=None):
    """读取公司清单，返回 [公司名, ...]（去重、去空、保持原顺序）。

    只认 Excel 里的简称列：股票代码是 6 位数字，不能当搜索关键词用。
    """
    file = company_file_path(path)
    if not os.path.exists(file):
        logger.error('【按公司】公司清单不存在：%s' % file)
        return []

    wb = None
    try:
        wb = load_workbook(file, read_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = [str(c or '').strip() for c in next(rows, [])]
        col = None
        for want in COMPANY_COLUMNS:
            if want in header:
                col = header.index(want)
                break
        if col is None:
            logger.error('【按公司】%s 里找不到公司名列（表头：%s）'
                         % (os.path.basename(file), '/'.join(header)))
            return []

        out, seen = [], set()
        for row in rows:
            if not row or col >= len(row):
                continue
            name = str(row[col] or '').strip()
            if not name:
                continue
            key = norm_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(name)
        logger.info('【按公司】从 %s 读到 %d 家公司'
                    % (os.path.basename(file), len(out)))
        return out
    except Exception as e:                 # noqa: BLE001
        logger.error('【按公司】读取公司清单失败：%s' % e)
        return []
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:              # noqa: BLE001
                pass


# ==================== xlsx 读写 ====================
HEADER_FILL = PatternFill(start_color='4472C4', end_color='4472C4',
                          fill_type='solid')
HEADER_FONT = Font(name='微软雅黑', size=11, bold=True, color='FFFFFF')
THIN_BORDER = Border(left=Side(style='thin'), right=Side(style='thin'),
                     top=Side(style='thin'), bottom=Side(style='thin'))


def prepare_workbook(data_file):
    """打开（或新建）工作簿并写好表头样式，返回 (wb, ws)。

    同时确保存在「已爬取公司」工作表 —— 它记录哪些公司已经完整采过，
    后续运行据此直接跳过，避免每次都把 500 多家重新搜一遍。
    """
    wb = load_workbook(filename=data_file) if os.path.exists(data_file) else Workbook()
    ws = wb.worksheets[0] if wb.worksheets else wb.active
    ws.title = SHEET_JOBS
    ws.freeze_panes = 'A2'
    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = THIN_BORDER
    _ensure_crawled_sheet(wb)
    return wb, ws


def _ensure_crawled_sheet(wb):
    """确保「已爬取公司」工作表存在，返回该表。"""
    if SHEET_CRAWLED in wb.sheetnames:
        ws = wb[SHEET_CRAWLED]
        # 表头被删过就补回来
        if ws.max_row == 0 or not ws.cell(row=1, column=1).value:
            for col, header in enumerate(CRAWLED_HEADERS, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(horizontal='center',
                                          vertical='center')
            ws.freeze_panes = 'A2'
        return ws
    ws = wb.create_sheet(SHEET_CRAWLED)
    ws.freeze_panes = 'A2'
    for col, header in enumerate(CRAWLED_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = THIN_BORDER
    return ws


def load_crawled_companies(data_file):
    """读取「已爬取公司」工作表，返回 {归一化公司名: 该公司岗位数}。

    只有**完整采完**的公司才会被记进来，所以这里可以直接当作
    「下次不用再采」的名单。
    """
    done = {}
    if not data_file or not os.path.exists(data_file):
        return done
    wb = None
    try:
        wb = load_workbook(data_file, read_only=True)
        if SHEET_CRAWLED not in wb.sheetnames:
            return done
        ws = wb[SHEET_CRAWLED]
        rows = ws.iter_rows(values_only=True)
        header = [str(c or '').strip() for c in next(rows, [])]
        try:
            name_col = header.index(CRAWLED_HEADERS[0])
        except ValueError:
            name_col = 0
        count_col = None
        if '新增岗位数' in header:
            count_col = header.index('新增岗位数')
        for row in rows:
            if not row or name_col >= len(row):
                continue
            name = str(row[name_col] or '').strip()
            if not name:
                continue
            try:
                cnt = int(row[count_col] or 0) if count_col is not None \
                    and count_col < len(row) else 0
            except (TypeError, ValueError):
                cnt = 0
            done[norm_name(name)] = cnt
    except Exception as e:                 # noqa: BLE001
        logger.warning('【按公司】读取「已爬取公司」失败：%s' % e)
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:              # noqa: BLE001
                pass
    return done


def mark_company_crawled(wb, company, added, email=''):
    """把一家公司标记为「已爬取」（写入 xlsx 的独立工作表）。

    同一家公司重复标记时更新那一行（不会出现两条），
    这样重跑或补采后仍然是「一条记录」。
    """
    ws = _ensure_crawled_sheet(wb)
    key = norm_name(company)
    target_row = None
    for r in range(2, ws.max_row + 1):
        value = str(ws.cell(row=r, column=1).value or '').strip()
        if value and norm_name(value) == key:
            target_row = r
            break
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if target_row is None:
        target_row = ws.max_row + 1
        if target_row < 2:
            target_row = 2
    ws.cell(row=target_row, column=1, value=company)
    ws.cell(row=target_row, column=2, value=added)
    ws.cell(row=target_row, column=3, value=stamp)
    return target_row


def save_workbook(wb, data_file, tag=''):
    """保存工作簿；文件被 Excel 占用时改写时间戳文件，避免中断采集。"""
    try:
        wb.save(data_file)
        return data_file
    except PermissionError:
        fallback = os.path.join(
            os.path.dirname(data_file),
            '%s_%s.xlsx' % (os.path.splitext(os.path.basename(data_file))[0],
                            time.strftime('%Y%m%d_%H%M%S')))
        try:
            wb.save(fallback)
            logger.info('%s%s 被占用（请关闭 Excel），本次改写到 %s'
                        % (tag, os.path.basename(data_file),
                           os.path.basename(fallback)))
            return fallback
        except Exception as e:             # noqa: BLE001
            logger.error('%s保存失败：%s' % (tag, e))
            return data_file
    except Exception as e:                 # noqa: BLE001
        logger.error('%s保存失败：%s' % (tag, e))
        return data_file


def read_existing_ids(data_file):
    """读取表里已有的全部岗位编号（跨天去重用）。

    按表头名字定位「岗位编号」列，不写死下标 ——
    万一用户调整过列顺序（或用了别的采集器生成的表），也能读对。
    """
    ids = set()
    if not data_file or not os.path.exists(data_file):
        return ids
    wb = None
    try:
        wb = load_workbook(data_file, read_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = [str(c or '').strip() for c in next(rows, [])]
        col = None
        for i, name in enumerate(header):
            if name == '岗位编号':
                col = i
                break
        if col is None:
            # 表头缺失/被改坏时退回内置位置，至少不会整表丢掉去重信息
            col = ID_INDEX
        for row in rows:
            if row and len(row) > col:
                value = str(row[col] or '').strip()
                if value:
                    ids.add(value)
    except Exception as e:                 # noqa: BLE001
        logger.warning('【按公司】读取已有岗位编号失败：%s' % e)
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:              # noqa: BLE001
                pass
    return ids


# ==================== 采集控制 ====================
class Control:
    """采集控制：暂停 / 停止。

    为什么用两个独立事件而不是复用 is_running：
      · is_running 只在采集线程**真正结束**时才置 False，
        点「停止」时它必须还是 True（界面按钮状态才对），
        所以不能拿它当停止信号 —— 否则点停止永远不生效。
      · stop_event 由「停止」按钮立即置位，采集循环每个检查点都能看到。
      · pause_event 置位 = 运行中，复位 = 暂停；等待时也要能被停止打断。
    """

    def __init__(self, pause_event=None, is_running=None, stop_event=None):
        self.pause_event = pause_event or threading.Event()
        if pause_event is None:
            self.pause_event.set()
        self.stop_event = stop_event or threading.Event()
        self._is_running = is_running

    def stopped(self):
        """是否该停下来了（停止按钮被点）。"""
        if self.stop_event.is_set():
            return True
        # 兼容外部只传 is_running 的用法：线程已经不在了也算停止
        if self._is_running is not None:
            try:
                return not self._is_running()
            except Exception:              # noqa: BLE001
                return False
        return False

    def wait(self):
        """暂停时阻塞；返回 False 表示应该停止。"""
        # 暂停期间也要能被「停止」打断，不能用裸的 pause_event.wait()
        while not self.pause_event.is_set():
            if self.stop_event.is_set():
                return False
            time.sleep(0.1)
        return not self.stopped()

    def sleep(self, seconds):
        """可被暂停 / 停止打断的 sleep。

        暂停时不消耗剩余时长：恢复后重新计时，
        否则一暂停 10 分钟，恢复瞬间就跳过页面间隔了。
        """
        remaining = max(0.0, seconds)
        while remaining > 0:
            if self.stopped():
                return False
            if not self.pause_event.is_set():
                # 暂停中：等恢复（wait 里会检查停止）
                if not self.wait():
                    return False
                remaining = max(0.0, seconds)
                continue
            step = min(0.2, remaining)
            time.sleep(step)
            remaining -= step
        return not self.stopped()
        return not self.stopped()


# ==================== 接口请求 ====================
def _query_string():
    """构造带随机追踪参数的查询串（智联用来做风控/AB 实验）。"""
    cid = uuid.uuid4()
    rid = '%s-%d-%d' % (cid.hex, int(time.time() * 1000),
                        random.randint(1, 9999))
    return ('platform=13&version=0.0.0&_v=0.%d'
            '&x-zp-page-request-id=%s&x-zp-client-id=%s'
            % (random.randint(100000000, 900000000), rid, cid))


def build_body(keyword, page_index, city_code=''):
    """搜索请求体。S_SOU_FULL_INDEX 是全文关键词，city 为空表示全国。"""
    return {
        'S_SOU_FULL_INDEX': keyword,
        'S_SOU_WORK_CITY': str(city_code or ''),
        'order': 4,
        'actionid': str(uuid.uuid4()),
        'pageSize': 20,          # 接口上限就是 20，传更大也只回 20
        'pageIndex': page_index,
        'at': '',
        'rt': '',
        'eventScenario': 'pcSearchedSouSearch',
        'anonymous': 1,          # 必须为 1：设 0 会直接触发风控
        'clickFilterBlackCompany': False,
        'platform': 13,
        'version': '0.0.0',
    }


def fetch_page(keyword, page_index, session, cookie='', control=None):
    """请求一页搜索结果，返回 (岗位列表, 是否末页)。"""
    if control is not None and control.stopped():
        return [], True
    headers = dict(_HTTP_HEADERS)
    if cookie:
        headers['cookie'] = cookie
    url = '%s?%s' % (API, _query_string())
    body = build_body(keyword, page_index)
    try:
        resp = session.post(url, headers=headers, data=json.dumps(body),
                            timeout=API_TIMEOUT, verify=False)
    except requests.RequestException as e:
        logger.warning('【按公司】%s 第%d页请求失败：%s'
                       % (keyword, page_index, e))
        return [], False
    if resp.status_code != 200:
        logger.warning('【按公司】%s 第%d页 HTTP %d'
                       % (keyword, page_index, resp.status_code))
        return [], False
    try:
        payload = resp.json()
    except ValueError:
        logger.warning('【按公司】%s 第%d页返回非 JSON' % (keyword, page_index))
        return [], False
    data = payload.get('data') or {}
    # 被风控拦下时接口仍回 200，但 isVerification=1 且 list 为空。
    # 必须显式识别，否则会被误判成「这家公司没有岗位」。
    if data.get('isVerification'):
        logger.warning('【按公司】%s 第%d页触发风控验证（isVerification=1）'
                       % (keyword, page_index))
        return [], False
    items = data.get('list') or []
    end = bool(data.get('isEndPage'))
    return items, end or not items


# ==================== 单公司采集 ====================
def collect_company(company, session, cookie='', max_pages=None, control=None,
                    known_ids=None):
    """采集一家公司的**新**岗位，返回 (岗位列表, 是否完整采完)。

    翻页直到 isEndPage（或达到上限），逐页按公司名过滤 ——
    搜索结果会混入别家公司，过滤是必须的。

    known_ids: 结果表里已有的岗位编号集合。
        命中的岗位**直接丢弃、不进入后续解析与写表**，
        等价于「已有的岗位编号不再爬取」。

    返回的 complete 只有在这种情况才为 True：
        正常翻到末页（isEndPage）或翻到该公司的岗位已全部采过。
        中途停止、请求失败、达到页数上限都算「没采完」，
        不会写进「已爬取公司」，下次还会重试。
    """
    max_pages = max_pages or MAX_PAGES
    control = control or Control()
    known = known_ids if known_ids is not None else set()
    got, seen_ids = [], set()
    total_scanned = 0
    skipped_known = 0       # 因已存在而跳过的数量
    empty_streak = 0
    has_hit = False         # 是否命中过该公司的岗位
    complete = False        # 是否完整采完

    for page in range(1, max_pages + 1):
        if not control.wait():             # 暂停阻塞 / 停止立即返回
            logger.info('【按公司】用户终止采集')
            break

        items, end = fetch_page(company, page, session,
                                cookie=cookie, control=control)
        failed = (not items) and not end
        if failed:
            # 请求失败/被风控：这次不算采完，下次会重试
            logger.info('【按公司】%s 第%d页没有拿到数据，本次不标记完成'
                        % (company, page))
            break
        if not items:
            # 接口正常返回但没数据 = 确实到底了
            complete = True
            break
        total_scanned += len(items)

        page_hit = 0
        page_new = 0
        page_known = 0
        for it in items:
            if not name_matches(company, it.get('companyName') or ''):
                continue
            job_id = str(it.get('jobId') or it.get('positionId') or '')
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            page_hit += 1
            # 已有岗位编号：直接跳过，不进入后续解析/写表
            if job_id in known:
                page_known += 1
                continue
            page_new += 1
            got.append(it)

        skipped_known += page_known

        if page_hit:
            has_hit = True
            logger.info(
                '【按公司】%s 第%d页：共 %d 条，属于该公司 %d 条'
                '（新增 %d、已有 %d 跳过），累计新增 %d 个岗位%s'
                % (company, page, len(items), page_hit, page_new, page_known,
                   len(got), '，智联标记已到底' if end else ''))
        else:
            logger.info('【按公司】%s 第%d页：共 %d 条，没有该公司的岗位%s'
                        % (company, page, len(items),
                           '，智联标记已到底' if end else ''))

        # ---------- 是否继续翻页 ----------
        # 注意：**不能**因为「本页全是已有岗位」或「中间几页没命中」就停 ——
        # 智联的排序会变，新岗位可能排在任意位置；某公司也可能第 1 页有几条、
        # 第 5 页又有几十条。提前停会漏采，与「每个公司全量」的要求冲突。
        #
        # 唯一允许提前停的情况：**从头到尾一次都没命中过**该公司，
        # 说明这家公司在智联没有在招岗位（或关键词没命中），继续翻页纯属浪费。
        if page_hit:
            empty_streak = 0
        else:
            empty_streak += 1
            if not has_hit and empty_streak >= MAX_EMPTY_PAGES:
                logger.info('【按公司】%s 连续 %d 页都没出现该公司的岗位，'
                            '视为没有在招岗位' % (company, empty_streak))
                complete = True
                break

        if end:
            complete = True
            break
        if not control.sleep(random.uniform(*PAGE_DELAY)):
            break
    else:
        # for-else：正常跑完 max_pages 还没结束 -> 可能没翻完
        logger.info('【按公司】%s 达到翻页上限 %d 页，本次不标记完成'
                    '（如需更深可调大 --max-pages）' % (company, max_pages))

    if not got:
        if skipped_known:
            logger.info('【按公司】%s：%d 个岗位都已在结果表中，无需新增'
                        '（未重复采集）' % (company, skipped_known))
        elif complete:
            logger.info('【按公司】%s：扫描 %d 条结果，没有在招岗位'
                        % (company, total_scanned))
    elif skipped_known:
        logger.info('【按公司】%s：新增 %d 个，另有 %d 个已有岗位已跳过'
                    % (company, len(got), skipped_known))
    return got, complete


def items_to_rows(items, crawl_date=None):
    """把匹配到的岗位整理成 xlsx 行（列顺序与 HEADERS 对齐）。"""
    crawl_date = crawl_date or datetime.now().strftime('%Y-%m-%d')
    rows = []
    for it in items or []:
        detail = item_to_row(it)
        city = detail.get('城市') or ''
        # 搜索接口不给省份，用城市占位（与原智联采集器一致）
        rows.append([crawl_date, SOURCE_NAME, city]
                    + [detail.get(k, '') for k in ROW_ORDER])
    return rows


def append_rows(ws, rows, history_ids, on_row=None):
    """按岗位编号去重后追加到工作表，返回新增条数。"""
    count = 0
    for row in rows:
        job_id = str(row[ID_INDEX] or '').strip() if len(row) > ID_INDEX else ''
        if job_id and job_id in history_ids:
            continue
        if job_id:
            history_ids.add(job_id)
        ws.append(row)
        count += 1
        if on_row is not None:
            try:
                on_row(row)
            except Exception:              # noqa: BLE001
                pass
    return count


# ==================== 主流程 ====================
def run(data_file=None, company_file=None, companies=None, limit=None,
        force=False, skip_login=False, ask=input, max_pages=None,
        cookie=None, recrawl=False, phone='', stop_event=None, pause_event=None,
        is_running=None,
        on_progress=None, on_row=None, on_log=None,
        on_complete=None, on_error=None):
    """采集入口：登录 -> 读公司清单 -> 逐公司搜岗位 -> 增量写入 xlsx。

    companies   指定公司列表（None 表示从 company_file 读取）
    limit       只跑前 N 家（试跑用）
    force       强制重新登录（默认复用 config.ini 里已保存的登录态）
    skip_login  跳过登录直接匿名采集（不推荐，连续请求容易被风控）
    cookie      已登录好的 cookie；传了就不再走登录流程
                （界面上先点「登录」再点「开始」时用这个）
    recrawl     True 时忽略「已爬取公司」记录，把全部公司重新采一遍
    phone       登录用手机号（不传则在登录时弹框询问）
    stop_event  threading.Event，置位后采集立即退出（「停止」按钮）
    pause_event threading.Event，复位时暂停（「暂停」按钮）
    on_progress(index, total, company, added)  每家公司结束后回调
    on_row(row)                                每写入一行回调
    返回写入的总条数。
    """
    data_file = data_file or os.path.join(BASE_DIR, DEFAULT_OUTPUT_FILE)
    control = Control(pause_event, is_running, stop_event)

    # ---------- 1. 登录 ----------
    if cookie is None:
        cookie = ''
    if cookie:
        logger.info('【按公司】使用已登录的会话（无需再次登录）')
    elif skip_login:
        logger.warning('【按公司】已跳过登录，使用匿名请求。'
                       '连续大量采集容易被风控，建议正常登录。')
    else:
        ok, cookie = prepare_login(ask=ask, force=force, phone=phone)
        if not ok:
            msg = '登录未成功，已停止采集'
            logger.error('【按公司】' + msg)
            if on_complete:
                on_complete(msg)
            return 0
        if control.stopped():
            logger.info('【按公司】用户终止采集')
            if on_complete:
                on_complete('用户终止采集')
            return 0

    # ---------- 2. 公司清单 ----------
    targets = list(companies) if companies else load_companies(company_file)
    if not targets:
        msg = '没有可采集的公司（请检查公司清单文件）'
        logger.error('【按公司】' + msg)
        if on_complete:
            on_complete(msg)
        return 0
    if limit:
        targets = targets[:int(limit)]
    logger.info('【按公司】待采集公司 %d 家' % len(targets))

    # ---------- 3. 结果表 ----------
    wb, ws = prepare_workbook(data_file)
    history_ids = read_existing_ids(data_file)
    logger.info('【按公司】结果表已有 %d 个岗位编号，本次跳过这些岗位'
                % len(history_ids))

    # 已完整采过的公司：默认直接跳过（--recrawl 可强制重采）
    crawled = {} if recrawl else load_crawled_companies(data_file)
    if crawled:
        logger.info('【按公司】%d 家公司已标记为「已爬取」，本次直接跳过'
                    '（想重采请加 --recrawl）' % len(crawled))
        before = len(targets)
        targets = [c for c in targets if norm_name(c) not in crawled]
        skipped_crawled = before - len(targets)
        if skipped_crawled:
            logger.info('【按公司】跳过已爬取公司 %d 家，剩余 %d 家'
                        % (skipped_crawled, len(targets)))
        if not targets:
            msg = '所有公司都已爬取过，无需采集（想重采请加 --recrawl）'
            logger.info('【按公司】' + msg)
            if on_complete:
                on_complete(msg)
            try:
                save_workbook(wb, data_file, tag='【按公司】')
            except Exception:              # noqa: BLE001
                pass
            return 0
    else:
        skipped_crawled = 0

    session = requests.Session()
    session.verify = False
    try:
        requests.packages.urllib3.disable_warnings()
    except AttributeError:
        pass

    total_rows = 0
    failed = []
    empty_companies = []
    crawl_date = datetime.now().strftime('%Y-%m-%d')

    try:
        for idx, company in enumerate(targets, 1):
            if not control.wait():
                logger.info('【按公司】用户终止采集')
                break

            logger.info('=' * 54)
            logger.info('【按公司】(%d/%d) 开始采集：%s'
                        % (idx, len(targets), company))
            try:
                # 把已有岗位编号传进去：命中的岗位在采集阶段就被丢弃，
                # 不再解析、不再写表 —— 即「已有的岗位编号不再爬取」。
                items, complete = collect_company(
                    company, session, cookie=cookie, max_pages=max_pages,
                    control=control, known_ids=history_ids)
                added = 0
                if items:
                    rows = items_to_rows(items, crawl_date)
                    added = append_rows(ws, rows, history_ids, on_row=on_row)
                    total_rows += added
                    logger.info('【按公司】%s 新增 %d 条' % (company, added))
                else:
                    empty_companies.append(company)

                # 只有完整采完才标记为「已爬取」，下次运行直接跳过。
                # 中途停止 / 请求失败的不标记，下次还会重试。
                if complete:
                    mark_company_crawled(wb, company, added)
                    if added:
                        save_workbook(wb, data_file, tag='【按公司】')
                    elif not items and not control.stopped():
                        # 没有新岗位但确实采完了，也要落盘记下标记
                        save_workbook(wb, data_file, tag='【按公司】')
                else:
                    logger.info('【按公司】%s 未完整采完，不标记为已爬取'
                                % company)
                    if added:
                        save_workbook(wb, data_file, tag='【按公司】')

                if on_progress:
                    on_progress(idx, len(targets), company, added)
            except Exception as e:         # noqa: BLE001
                failed.append(company)
                logger.error('【按公司】%s 采集异常：%s' % (company, e))
                if on_error:
                    on_error('%s: %s' % (company, e))

            if control.stopped():
                break
            if idx < len(targets):
                if not control.sleep(random.uniform(*COMPANY_DELAY)):
                    break
    finally:
        try:
            save_workbook(wb, data_file, tag='【按公司】')
        except Exception as e:             # noqa: BLE001
            logger.error('【按公司】保存失败：%s' % e)
        try:
            session.close()
        except Exception:                  # noqa: BLE001
            pass

    # ---------- 4. 收尾统计 ----------
    stopped = control.stopped()
    logger.info('=' * 54)
    logger.info('【按公司】完成：写入 %d 条岗位%s'
                % (total_rows, '（用户终止）' if stopped else ''))
    if empty_companies:
        preview = '、'.join(empty_companies[:10])
        logger.info('【按公司】%d 家公司在智联没有在招岗位：%s%s'
                    % (len(empty_companies), preview,
                       '…' if len(empty_companies) > 10 else ''))
    if failed:
        logger.info('【按公司】失败公司 %d 家：%s'
                    % (len(failed), '、'.join(failed[:10])))

    if on_complete:
        if stopped:
            on_complete('采集已停止，本次新增 %d 条' % total_rows)
        else:
            on_complete('采集完成，本次新增 %d 条' % total_rows)
    return total_rows


# ==================== 图形界面 ====================
# 配色（浅色，与项目其它采集器一致）
_C_BG = '#f2f5fa'
_C_CARD = '#ffffff'
_C_BORDER = '#e1e7f0'
_C_FG = '#1e2532'
_C_MUTED = '#6b7686'
_C_ACCENT = '#2563eb'
_C_OK = '#15803d'
_C_WARN = '#b45309'
_C_ERR = '#dc2626'
_C_HEAD = '#eef3fb'

_F_UI = ('Microsoft YaHei UI', 9)
_F_BOLD = ('Microsoft YaHei UI', 9, 'bold')
_F_TITLE = ('Microsoft YaHei UI', 14, 'bold')
_F_SMALL = ('Microsoft YaHei UI', 8)
_F_MONO = ('Consolas', 9)

# 表格列：(列id, 标题, 宽度)
_COLUMNS = (
    ('idx', '#', 50),
    ('company', '公司名称', 240),
    ('name', '职位名称', 220),
    ('city', '城市', 90),
    ('salary', '薪资', 140),
    ('edu', '学历', 70),
    ('exp', '经验', 90),
    ('job_id', '岗位编号', 110),
)


class CompanyGUI:
    """智联「按公司采集」的独立图形界面。

    只用标准库 tkinter 实现，不依赖项目里的其它 GUI 基类：
    工具栏（开始/暂停/停止/清空/复制）、进度与统计、结果表格、可折叠日志。

    采集在后台线程里跑，通过 queue 把消息送回主线程 ——
    tkinter 不是线程安全的，所有控件操作都必须在主线程做。
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('智联招聘 · 按公司采集')
        self.root.configure(bg=_C_BG)
        self.root.geometry('1280x820')
        self.root.minsize(1000, 640)

        self.queue = queue.Queue()
        self.pause_event = threading.Event()
        self.pause_event.set()        # 置位 = 未暂停
        self.stop_event = threading.Event()   # 置位 = 请求停止
        self.is_running = False
        self.is_paused = False
        self.worker = None
        self.start_time = 0.0
        self.row_count = 0
        self.company_done = 0
        self.company_total = 0
        self._poll_id = None
        # 「登录」按钮拿到的 cookie；点「开始」时直接复用，不再弹浏览器
        self.cookie = ''
        # 「加载公司」按钮读到的公司清单；None 表示还没加载（开始时会自动读）
        self.companies = None

        self._build()
        self._center()
        self._attach_logger()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self._poll_id = self.root.after(120, self._poll)
        self._log('就绪。建议先点「登录」，再点「加载公司」确认清单，最后「开始采集」。',
                  'muted')
        # 启动时把已有登录态和公司清单状态显示出来，不用每次都点一遍
        if has_login():
            self.cookie = load_cookie()
            self.lbl_login.configure(text='登录状态：已登录（可复用）',
                                     fg=_C_OK)

    # ---------- 布局 ----------
    def _build(self):
        wrap = tk.Frame(self.root, bg=_C_BG)
        wrap.pack(fill='both', expand=True, padx=14, pady=(12, 8))

        self._build_toolbar(wrap)
        self._build_stats(wrap)
        self._build_table(wrap)
        self._build_log(wrap)
        self._build_status(wrap)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=_C_CARD, highlightbackground=_C_BORDER,
                         highlightthickness=1)
        outer.pack(fill='x', pady=(0, 10))
        inner = tk.Frame(outer, bg=_C_CARD)
        inner.pack(fill='both', expand=True, padx=14, pady=10)
        return inner

    def _build_toolbar(self, parent):
        inner = self._card(parent)
        row = tk.Frame(inner, bg=_C_CARD)
        row.pack(fill='x')

        self.btn_start = tk.Button(
            row, text='▶  开始采集', command=self._on_start,
            bg=_C_ACCENT, fg='#ffffff', font=_F_BOLD, bd=0,
            activebackground='#1d4ed8', activeforeground='#ffffff',
            padx=18, pady=7, cursor='hand2')
        self.btn_start.pack(side='left')

        self.btn_pause = tk.Button(
            row, text='⏸  暂停', command=self._on_pause, state='disabled',
            bg='#eef2f9', fg=_C_FG, font=_F_UI, bd=0, padx=14, pady=7,
            cursor='hand2')
        self.btn_pause.pack(side='left', padx=(10, 0))

        self.btn_stop = tk.Button(
            row, text='■  停止', command=self._on_stop, state='disabled',
            bg='#fdeaea', fg=_C_ERR, font=_F_UI, bd=0, padx=14, pady=7,
            cursor='hand2')
        self.btn_stop.pack(side='left', padx=(10, 0))

        # 登录：单独按钮，不必等「开始采集」才登录 ——
        # 可以先把登录态准备好（cookie 会存进 config.ini），
        # 之后点开始就不用再等浏览器。
        self.btn_login = tk.Button(
            row, text='🔑  登录', command=self._on_login,
            bg='#eef2f9', fg=_C_FG, font=_F_UI, bd=0, padx=14, pady=7,
            cursor='hand2')
        self.btn_login.pack(side='left', padx=(10, 0))

        # 加载公司：从 xlsx 读公司清单并显示在下方列表里，
        # 让用户采集前先确认「要采哪些公司」。
        self.btn_load = tk.Button(
            row, text='📋  加载公司', command=self._on_load_companies,
            bg='#eef2f9', fg=_C_FG, font=_F_UI, bd=0, padx=14, pady=7,
            cursor='hand2')
        self.btn_load.pack(side='left', padx=(10, 0))

        tk.Button(row, text='清空列表', command=self._clear_rows,
                  bg='#eef2f9', fg=_C_FG, font=_F_UI, bd=0, padx=14, pady=7,
                  cursor='hand2').pack(side='left', padx=(10, 0))
        tk.Button(row, text='复制本页', command=self._copy_rows,
                  bg='#eef2f9', fg=_C_FG, font=_F_UI, bd=0, padx=14, pady=7,
                  cursor='hand2').pack(side='left', padx=(10, 0))

        self.var_force = tk.BooleanVar(value=False)
        self.chk_force = tk.Checkbutton(
            row, text='强制重新登录', variable=self.var_force,
            bg=_C_CARD, fg=_C_MUTED, font=_F_SMALL, bd=0,
            activebackground=_C_CARD, selectcolor=_C_CARD,
            highlightthickness=0, cursor='hand2')
        self.chk_force.pack(side='right')

    def _build_stats(self, parent):
        inner = self._card(parent)
        row = tk.Frame(inner, bg=_C_CARD)
        row.pack(fill='x')

        self.lbl_company = tk.Label(row, text='公司 0/0', bg=_C_CARD,
                                    fg=_C_ACCENT, font=_F_TITLE)
        self.lbl_company.pack(side='left')

        info = tk.Frame(row, bg=_C_CARD)
        info.pack(side='left', padx=(16, 0), fill='x', expand=True)
        self.lbl_stage = tk.Label(info, text='等待开始', bg=_C_CARD,
                                  fg=_C_FG, font=_F_UI, anchor='w')
        self.lbl_stage.pack(anchor='w')
        self.lbl_rows = tk.Label(info, text='已写入 0 条', bg=_C_CARD,
                                 fg=_C_MUTED, font=_F_SMALL, anchor='w')
        self.lbl_rows.pack(anchor='w', pady=(2, 0))

        # 公司清单状态：加载后显示「已加载 524 家（A股2021年新上市公司.xlsx）」
        self.lbl_companies = tk.Label(info, text='公司清单：未加载',
                                      bg=_C_CARD, fg=_C_MUTED,
                                      font=_F_SMALL, anchor='w')
        self.lbl_companies.pack(anchor='w', pady=(2, 0))

        # 登录状态
        self.lbl_login = tk.Label(info, text='登录状态：未登录',
                                  bg=_C_CARD, fg=_C_MUTED,
                                  font=_F_SMALL, anchor='w')
        self.lbl_login.pack(anchor='w', pady=(2, 0))

        self.lbl_elapsed = tk.Label(row, text='', bg=_C_CARD, fg=_C_MUTED,
                                    font=_F_SMALL)
        self.lbl_elapsed.pack(side='right')

        self.pb = ttk.Progressbar(inner, mode='determinate', maximum=100)
        self.pb.pack(fill='x', pady=(8, 0))

    def _build_table(self, parent):
        outer = tk.Frame(parent, bg=_C_CARD, highlightbackground=_C_BORDER,
                         highlightthickness=1)
        outer.pack(fill='both', expand=True, pady=(0, 10))
        inner = tk.Frame(outer, bg=_C_CARD)
        inner.pack(fill='both', expand=True, padx=10, pady=8)

        head = tk.Frame(inner, bg=_C_CARD)
        head.pack(fill='x', pady=(0, 6))
        tk.Label(head, text='采集结果', bg=_C_CARD, fg=_C_FG,
                 font=_F_BOLD).pack(side='left')
        self.lbl_table_count = tk.Label(head, text='共 0 条', bg=_C_CARD,
                                       fg=_C_MUTED, font=_F_SMALL)
        self.lbl_table_count.pack(side='left', padx=(10, 0))

        wrap = tk.Frame(inner, bg=_C_CARD)
        wrap.pack(fill='both', expand=True)

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('Treeview', background=_C_CARD,
                        fieldbackground=_C_CARD, foreground=_C_FG,
                        rowheight=24, borderwidth=0, font=_F_UI)
        style.configure('Treeview.Heading', background=_C_HEAD,
                        foreground=_C_MUTED, font=_F_BOLD, relief='flat',
                        padding=(6, 5))

        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in _COLUMNS],
                                 show='headings', selectmode='extended')
        for cid, title, width in _COLUMNS:
            self.tree.heading(cid, text=title, anchor='w')
            self.tree.column(cid, width=width, minwidth=50, anchor='w',
                             stretch=(cid in ('company', 'name')))
        self.tree.tag_configure('odd', background='#fbfcfe')
        self.tree.tag_configure('even', background=_C_CARD)

        vsb = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)

    def _build_log(self, parent):
        outer = tk.Frame(parent, bg=_C_CARD, highlightbackground=_C_BORDER,
                         highlightthickness=1)
        outer.pack(fill='x')
        inner = tk.Frame(outer, bg=_C_CARD)
        inner.pack(fill='both', expand=True, padx=10, pady=8)

        head = tk.Frame(inner, bg=_C_CARD)
        head.pack(fill='x')
        self.btn_log = tk.Button(
            head, text='▾  运行日志', command=self._toggle_log,
            bg=_C_CARD, fg=_C_ACCENT, font=_F_BOLD, bd=0,
            activebackground='#e8effd', cursor='hand2', padx=0)
        self.btn_log.pack(side='left')
        tk.Button(head, text='清空', command=self._clear_log, bg='#eef2f9',
                  fg=_C_FG, font=_F_SMALL, bd=0, padx=10, pady=3,
                  cursor='hand2').pack(side='right')

        self.log_body = tk.Frame(inner, bg=_C_CARD)
        self.log_body.pack(fill='both', expand=True, pady=(6, 0))

        wrap = tk.Frame(self.log_body, bg='#fbfcfe',
                        highlightbackground=_C_BORDER, highlightthickness=1)
        wrap.pack(fill='both', expand=True)
        self.log = tk.Text(wrap, bg='#fbfcfe', fg=_C_FG, font=_F_MONO,
                           wrap='char', height=8, bd=0, highlightthickness=0,
                           padx=8, pady=6, state='disabled')
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)

        for tag, color in (('info', _C_FG), ('muted', _C_MUTED),
                           ('warn', _C_WARN), ('error', _C_ERR),
                           ('ok', _C_OK), ('accent', _C_ACCENT)):
            self.log.tag_config(tag, foreground=color)

    def _build_status(self, parent):
        self.lbl_status = tk.Label(parent, text='就绪', bg=_C_BG, fg=_C_MUTED,
                                   font=_F_SMALL, anchor='w')
        self.lbl_status.pack(fill='x')

    def _center(self):
        self.root.update_idletasks()
        w = min(max(1280, self.root.winfo_reqwidth()), 
                self.root.winfo_screenwidth() - 60)
        h = min(max(820, self.root.winfo_reqheight()),
                self.root.winfo_screenheight() - 80)
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 3)
        self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))

    # ---------- 日志 ----------
    def _attach_logger(self):
        """把项目 logger 的输出接到界面上（通过队列，避免跨线程操作控件）。"""
        import logging

        gui = self

        class _Handler(logging.Handler):
            def emit(self, record):
                try:
                    gui.queue.put(('log', record.levelname,
                                   record.getMessage()))
                except Exception:          # noqa: BLE001
                    pass

        base = logging.getLogger('main')
        base.setLevel(logging.DEBUG)
        for h in base.handlers:
            if isinstance(h, _Handler):
                return
        base.addHandler(_Handler())

    def _log(self, text, tag='info'):
        self.log.configure(state='normal')
        self.log.insert('end', '[%s] ' % time.strftime('%H:%M:%S'), 'muted')
        self.log.insert('end', text + '\n', tag)
        self.log.configure(state='disabled')
        self.log.see('end')

    def _toggle_log(self):
        if self.log_body.winfo_manager():
            self.log_body.pack_forget()
            self.btn_log.configure(text='▸  运行日志（已折叠）')
        else:
            self.log_body.pack(fill='both', expand=True, pady=(6, 0))
            self.btn_log.configure(text='▾  运行日志')

    def _clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    # ---------- 表格 ----------
    def _add_row(self, row):
        """把一行采集结果加到表格（主线程调用）。"""
        def pick(name):
            try:
                idx = HEADERS.index(name)
            except ValueError:
                return ''
            return row[idx] if idx < len(row) else ''

        self.row_count += 1
        values = (
            self.row_count,
            pick('公司名称'),
            pick('职位名称'),
            pick('城市'),
            pick('薪资范围'),
            pick('学历要求'),
            pick('经验要求'),
            pick('岗位编号'),
        )
        tag = 'odd' if self.row_count % 2 else 'even'
        self.tree.insert('', 'end', values=values, tags=(tag,))
        self.lbl_table_count.configure(text='共 %d 条' % self.row_count)
        self.tree.see(self.tree.get_children()[-1])
        self._update_rows_label()

    def _clear_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.row_count = 0
        self.lbl_table_count.configure(text='共 0 条')
        self._update_rows_label()

    def _copy_rows(self):
        lines = ['\t'.join(c[1] for c in _COLUMNS)]
        for item in self.tree.get_children():
            vals = self.tree.item(item, 'values')
            lines.append('\t'.join(str(v) for v in vals))
        self.root.clipboard_clear()
        self.root.clipboard_append('\n'.join(lines))
        self._log('已复制 %d 行到剪贴板' % (len(lines) - 1), 'ok')

    def _update_rows_label(self):
        self.lbl_rows.configure(text='已写入 %d 条' % self.row_count)

    # ---------- 运行状态 ----------
    def _set_running(self, running):
        self.is_running = running
        state = 'disabled' if running else 'normal'
        self.btn_start.configure(state=state)
        self.btn_login.configure(state=state)
        self.btn_load.configure(state=state)
        self.btn_pause.configure(state='normal' if running else 'disabled')
        self.btn_stop.configure(state='normal' if running else 'disabled')
        self.chk_force.configure(state=state)

    # ---------- 登录（独立按钮） ----------
    def _on_login(self):
        """点「登录」：先把登录态准备好（cookie 存进 config.ini）。

        这样点「开始采集」时就不用再等浏览器 —— 直接复用这份 cookie。
        如果已经有有效登录态且没勾「强制重新登录」，只做一次检查。
        """
        if self.is_running:
            return
        force = bool(self.var_force.get())
        if not force and has_login():
            self._log('已有登录态，无需重新登录'
                      '（想换账号请勾选「强制重新登录」）', 'ok')
            self.lbl_login.configure(text='登录状态：已登录（可复用）',
                                     fg=_C_OK)
            self.cookie = load_cookie()
            return

        self.btn_login.configure(state='disabled')
        self.lbl_login.configure(text='登录状态：登录中……', fg=_C_WARN)
        self._log('正在打开浏览器登录智联……', 'accent')

        def _work():
            try:
                cookie = browser_login(ask=self._ask)
                self.queue.put(('login', bool(cookie), cookie))
            except Exception as e:          # noqa: BLE001
                self.queue.put(('login', False, str(e)[:200]))

        threading.Thread(target=_work, daemon=True).start()

    def _on_login_result(self, ok, cookie):
        self.btn_login.configure(state='normal')
        if ok and cookie:
            self.cookie = cookie
            self.lbl_login.configure(text='登录状态：已登录（可复用）',
                                     fg=_C_OK)
            self._log('登录成功，cookie 已保存到 config.ini', 'ok')
        else:
            self.cookie = ''
            self.lbl_login.configure(text='登录状态：未登录', fg=_C_ERR)
            self._log('登录未成功：%s' % (cookie or '未知原因'), 'error')

    # ---------- 加载公司（独立按钮） ----------
    def _on_load_companies(self):
        """点「加载公司」：从 xlsx 读公司清单并显示在列表里。

        采集前先让用户确认「要采哪些公司」，
        比直接点开始才发现清单读错了要好。
        """
        if self.is_running:
            return
        path = company_file_path()
        if not os.path.exists(path):
            self._log('公司清单不存在：%s' % path, 'error')
            self.lbl_companies.configure(text='公司清单：文件不存在',
                                         fg=_C_ERR)
            from tkinter import messagebox
            messagebox.showerror(
                '找不到公司清单',
                '请把 %s 放到程序目录：\n%s'
                % (DEFAULT_COMPANY_FILE, BASE_DIR))
            return

        companies = load_companies()
        self.companies = companies or []
        if not companies:
            self.lbl_companies.configure(text='公司清单：读取失败', fg=_C_ERR)
            self._log('公司清单读取失败，请检查表头是否有「股票简称」列',
                      'error')
            return

        self.lbl_companies.configure(
            text='公司清单：已加载 %d 家（%s）'
                 % (len(companies), os.path.basename(path)),
            fg=_C_OK)
        self.lbl_company.configure(text='公司 0/%d' % len(companies))
        self._log('已加载 %d 家公司：%s'
                  % (len(companies), os.path.basename(path)), 'ok')
        self._log('前 10 家：%s' % '、'.join(companies[:10]), 'muted')

    def _on_pause(self):
        if not self.is_running:
            return
        if self.is_paused:
            self.pause_event.set()
            self.is_paused = False
            self.btn_pause.configure(text='⏸  暂停')
            self.lbl_stage.configure(text='已恢复')
            self._log('已恢复采集', 'ok')
        else:
            self.pause_event.clear()
            self.is_paused = True
            self.btn_pause.configure(text='▶  继续')
            self.lbl_stage.configure(text='已暂停')
            self._log('已暂停（当前请求结束后生效）', 'warn')

    def _on_stop(self):
        self.pause_event.set()          # 解除暂停，让线程能走到停止判断
        self.stop_event.set()           # 发出停止信号
        self.is_paused = False
        self.btn_pause.configure(text='⏸  暂停')
        self.btn_stop.configure(state='disabled')
        self.lbl_stage.configure(text='正在停止……')
        self._log('已请求停止（当前请求结束后退出）', 'warn')

    # ---------- 登录对话框 ----------
    def _ask(self, prompt):
        """登录时向用户要手机号 / 短信验证码。

        登录流程在后台线程里同步调用这个函数，
        而 tkinter 只能在主线程操作，所以用 after + Event 把对话框弹到主线程。
        """
        from tkinter import simpledialog

        res = {}
        evt = threading.Event()

        def _dialog():
            try:
                res['v'] = simpledialog.askstring('智联登录', prompt,
                                                  parent=self.root)
            except Exception:              # noqa: BLE001
                res['v'] = ''
            evt.set()

        self.root.after(0, _dialog)
        evt.wait()
        return (res.get('v') or '').strip()

    # ---------- 开始 ----------
    def _on_start(self):
        if self.is_running:
            return
        self.stop_event.clear()          # 新的一轮：清掉上次的停止信号
        self.pause_event.set()
        self.is_paused = False
        self.btn_pause.configure(text='⏸  暂停')
        self._clear_log()
        self._clear_rows()
        self.company_done = 0
        self.company_total = 0
        self.pb['value'] = 0
        self.lbl_company.configure(text='公司 0/0')
        self.lbl_stage.configure(text='准备开始……')
        self.lbl_status.configure(text='运行中')
        self._set_running(True)
        self.start_time = time.time()

        self._log('─' * 46, 'muted')
        if self.cookie:
            self._log('已登录，直接开始采集……', 'accent')
        else:
            self._log('开始采集（未登录时会先打开浏览器自动登录）……', 'accent')

        force = bool(self.var_force.get())
        self.worker = threading.Thread(target=self._run_worker,
                                       args=(force,), daemon=True)
        self.worker.start()

    def _run_worker(self, force):
        try:
            run(
                data_file=os.path.join(BASE_DIR, DEFAULT_OUTPUT_FILE),
                companies=self.companies,      # 已加载的公司清单；None 则自动读
                force=force,
                cookie=self.cookie,
                ask=self._ask,
                stop_event=self.stop_event,
                pause_event=self.pause_event,
                is_running=lambda: self.is_running,
                on_progress=lambda i, t, c, a: self.queue.put(
                    ('progress', i, t, c, a)),
                on_row=lambda row: self.queue.put(('row', row)),
                on_complete=lambda msg: self.queue.put(('done', msg)),
                on_error=lambda msg: self.queue.put(('error', msg)),
            )
        except Exception as e:             # noqa: BLE001
            import traceback
            self.queue.put(('error', '采集线程异常：%s' % e))
            self.queue.put(('log', 'ERROR', traceback.format_exc()[:2000]))
            self.queue.put(('done', '采集异常结束'))

    # ---------- 消息循环 ----------
    def _poll(self):
        """把后台线程的消息搬进界面。

        单条消息出错不能影响整个界面：一旦这里抛异常，
        after() 就不会再注册，界面会永久卡死。
        """
        try:
            while True:
                msg = self.queue.get_nowait()
                try:
                    self._handle(msg)
                except Exception as e:     # noqa: BLE001
                    self._log('处理界面消息失败：%s' % e, 'error')
        except queue.Empty:
            pass
        except Exception as e:             # noqa: BLE001
            self._log('界面轮询异常：%s' % e, 'error')
        finally:
            try:
                self._tick_elapsed()
            except Exception:              # noqa: BLE001
                pass
            self._poll_id = self.root.after(120, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == 'log':
            level = msg[1]
            tag = {'WARNING': 'warn', 'ERROR': 'error',
                   'CRITICAL': 'error'}.get(level, 'info')
            self._log(msg[2], tag)
        elif kind == 'login':
            self._on_login_result(msg[1], msg[2])
        elif kind == 'row':
            self._add_row(msg[1])
        elif kind == 'progress':
            _, idx, total, company, added = msg
            self.company_done = idx
            self.company_total = total
            self.lbl_company.configure(text='公司 %d/%d' % (idx, total))
            self.lbl_stage.configure(text='%s（新增 %d）' % (company, added))
            if total:
                self.pb['value'] = int(round(idx / total * 100))
        elif kind == 'error':
            self._log(msg[1], 'error')
        elif kind == 'done':
            self._set_running(False)
            self.lbl_stage.configure(text=msg[1])
            self.lbl_status.configure(text='已结束')
            if self.company_total:
                self.pb['value'] = 100
            self._log(msg[1], 'ok')
            self._log('结果文件：%s'
                      % os.path.join(BASE_DIR, DEFAULT_OUTPUT_FILE), 'accent')

    def _tick_elapsed(self):
        if self.start_time and self.is_running:
            sec = int(time.time() - self.start_time)
            self.lbl_elapsed.configure(
                text='已用时 %02d:%02d:%02d'
                     % (sec // 3600, sec % 3600 // 60, sec % 60))

    # ---------- 关闭 ----------
    def _on_close(self):
        if self.is_running:
            from tkinter import messagebox
            if not messagebox.askyesno(
                    '正在采集',
                    '采集尚未结束，确定要退出吗？\n（正在处理的那家公司可能会丢）'):
                return
            self.is_running = False
            self.stop_event.set()
            self.pause_event.set()
            if self.worker is not None:
                self.worker.join(timeout=3)
        try:
            if self._poll_id is not None:
                self.root.after_cancel(self._poll_id)
        except Exception:                  # noqa: BLE001
            pass
        self.root.destroy()

    def run(self):
        """进入界面主循环（阻塞到窗口关闭）。"""
        self.root.mainloop()


def launch_gui():
    """打开图形界面。"""
    CompanyGUI().run()
    return 0


# ==================== 命令行 ====================
def main(argv=None):
    """命令行 / 图形界面入口。"""
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    parser = argparse.ArgumentParser(
        description='智联招聘 —— 按公司名称采集岗位（全量）')
    parser.add_argument('-f', '--file', default=None,
                        help='公司清单 xlsx（默认 %s）' % DEFAULT_COMPANY_FILE)
    parser.add_argument('-o', '--out', default=DEFAULT_OUTPUT_FILE,
                        help='结果文件（默认 %s）' % DEFAULT_OUTPUT_FILE)
    parser.add_argument('-c', '--company', default=None,
                        help='只采集指定公司，多个用逗号分隔')
    parser.add_argument('-n', '--limit', type=int, default=None,
                        help='只采集前 N 家公司（试跑用）')
    parser.add_argument('--max-pages', type=int, default=None,
                        help='单公司最多翻多少页（默认 %d）' % MAX_PAGES)
    parser.add_argument('--force', action='store_true',
                        help='强制重新登录（默认复用已保存的登录态）')
    parser.add_argument('--skip-login', action='store_true',
                        help='跳过登录，直接匿名采集（不推荐，易被风控）')
    parser.add_argument('--recrawl', action='store_true',
                        help='忽略「已爬取公司」记录，把全部公司重新采一遍')
    parser.add_argument('--phone', default='',
                        help='登录用手机号（不传则在登录时询问）')
    parser.add_argument('--gui', action='store_true',
                        help='打开图形界面（不带任何参数时默认也是这个）')
    parser.add_argument('--cli', action='store_true',
                        help='强制使用命令行模式')
    args = parser.parse_args(argv)

    # 不带参数 -> 图形界面；显式 --gui 也是；--cli 走命令行
    if args.gui or (not argv and not args.cli):
        return launch_gui()

    companies = None
    if args.company:
        companies = [c.strip() for c in re.split(r'[,，]', args.company)
                     if c.strip()]

    out_file = (args.out if os.path.isabs(args.out)
                else os.path.join(BASE_DIR, args.out))

    print('=' * 60)
    print(' 智联招聘 —— 按公司名称采集岗位')
    print('=' * 60)
    print('公司清单：%s' % (args.file or DEFAULT_COMPANY_FILE))
    print('结果文件：%s' % out_file)
    print('登录：%s' % ('跳过' if args.skip_login
                      else ('强制重新登录' if args.force else '复用已保存的登录态')))
    if args.recrawl:
        print('模式：重新采集（忽略已爬取记录）')
    if companies:
        print('指定公司：%s' % '、'.join(companies))
    print()

    total = run(
        data_file=out_file,
        company_file=args.file,
        companies=companies,
        limit=args.limit,
        force=args.force,
        skip_login=args.skip_login,
        recrawl=args.recrawl,
        phone=args.phone,
        max_pages=args.max_pages,
    )
    print('\n完成，本次新增 %d 条，结果文件：%s' % (total or 0, out_file))
    return 0


if __name__ == '__main__':
    sys.exit(main())
