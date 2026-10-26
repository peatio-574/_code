# coding='utf-8'
"""BOSS 直聘岗位采集

对接接口（必须在浏览器环境内请求，requests 直连返回 code=37）：
  - 列表：POST /wapi/zpgeek/search/joblist.json   参数在 body（form-urlencoded）
  - 详情：GET  /wapi/zpgeek/job/detail.json       securityId + lid

数据来源（均为外部文件，不打包进 exe，可自行增减粒度）：
  - BossCity.json     省/市/区县 及其 code
                      粒度由文件内容决定：每个市 1 条即为市级，
                      拆到区县即为区县级
  - BossJobType.json  岗位分类及 code

注意：
  securityId 由列表接口随响应下发，时效很短，
  必须「取一页列表 → 立刻取该页每条详情」，不可缓存复用。
"""
import os
import re
import sys
import json
import time
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from getJobs import BaseSpider
from PatchRightClass import PatchRightClass
from Logger import logger
from Config import get_config_value

try:
    from patchright.sync_api import (TimeoutError as PlaywrightTimeout,
                                     Error as PlaywrightError)
except ImportError:  # 兜底：patchright 未安装时用 playwright 的异常类型
    from playwright.sync_api import (TimeoutError as PlaywrightTimeout,
                                     Error as PlaywrightError)

# ==================== 路径 ====================
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 城市/岗位字典已迁移到 config/ 目录；为兼容旧位置，先查 config，再回退根目录
_CONFIG_DIR = os.path.join(_BASE_DIR, 'config')


def _resolve_data_file(name):
    """优先在 config/ 下查找，找不到再回退到脚本同级目录。"""
    for base in (_CONFIG_DIR, _BASE_DIR):
        path = os.path.join(base, name)
        if os.path.exists(path):
            return path
    return os.path.join(_CONFIG_DIR, name)


CITY_FILE = _resolve_data_file('BossCity.json')
JOBTYPE_FILE = _resolve_data_file('BossJobType.json')
CONFIG_FILE = os.path.join(_CONFIG_DIR, 'config.ini')

# ==================== 浏览器内请求脚本 ====================
JS_POST = """
async ({url, body}) => {
    const form = new URLSearchParams(body).toString();
    const r = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json, text/plain, */*',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: form,
    });
    const t = await r.text();
    let d;
    try { d = JSON.parse(t); } catch (e) { d = {raw: t.slice(0, 300)}; }
    return {status: r.status, data: d};
}
"""

JS_GET = """
async ({url}) => {
    const r = await fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: {
            'Accept': 'application/json, text/plain, */*',
            'X-Requested-With': 'XMLHttpRequest',
        },
    });
    const t = await r.text();
    let d;
    try { d = JSON.parse(t); } catch (e) { d = {raw: t.slice(0, 300)}; }
    return {status: r.status, data: d};
}
"""

# ==================== 字段映射 ====================
# jobType -> 招聘类型（实测 0=社招，5=校招/应届）
JOB_TYPE_MAP = {
    0: '社会招聘',
    1: '实习',
    2: '实习',
    3: '兼职',
    4: '兼职',
    5: '校园招聘',
}

# 专业要求线索词（从职位描述兜底提取时用）
_MAJOR_PATTERNS = (
    r'(?:所学专业|专业要求|专业方向|专业类别|专业背景|专业)\s*[:：]\s*([^\n，,。；;]{1,60})',
    r'([^\n，,。；;：:]{2,60}?)(?:等)?(?:相关)?专业',
)
_MAJOR_HINT = (
    '学', '工程', '科学', '管理', '技术', '信息', '医学', '教育', '经济', '金融',
    '会计', '财务', '设计', '电子', '机械', '化学', '生物', '计算机', '软件',
    '通信', '自动化', '建筑', '能源', '动力', '制药', '药学', '营销', '传播',
    '法学', '法律', '畜牧', '兽医', '环境', '安全', '物流', '贸易', '英语',
    '统计', '数学', '物理', '护理', '临床', '中医', '中药', '食品', '农',
)


class Boss(BaseSpider):
    """BOSS 直聘采集类

    流程：加载城市/岗位字典 -> 逐城市 × 逐岗位 -> 翻页取列表 -> 逐条取详情 -> 入库
    说明：
      * 浏览器用 PatchRight（Playwright 反检测 fork），可过 BOSS 的 JS 风控
      * 所有接口请求都在浏览器内用 fetch 发出，携带真实 cookie 与 TLS 指纹
      * securityId 时效很短，列表与详情必须成对紧邻请求
    """
    web_name = 'BOSS直聘'

    # 接口
    LIST_API = 'https://www.zhipin.com/wapi/zpgeek/search/joblist.json'
    DETAIL_API = 'https://www.zhipin.com/wapi/zpgeek/job/detail.json'

    # 采集参数
    DEFAULT_PAGE_SIZE = 15
    DEFAULT_PAGES = 100000      # 安全上限；实际靠空页/末页结束
    DEFAULT_DELAY = 4.0         # 每条详情间隔（秒）；过快会触发 code=37 风控
    PAGE_DELAY = 2.0            # 翻页间隔（秒）
    RETRY_SLEEP = 5             # 单次请求失败重试等待
    RETRY_TIMES = 2
    SAVE_INTERVAL = 10

    # 每个「城市 × 岗位」组合最多采集多少条**新**职位（0 或负数 = 不限制）
    # 已存在于 xlsx 的岗位不计数，会继续往后翻页直到凑够条数或没有更多页
    MAX_JOBS_PER_POSITION = 5
    # 每个组合最多翻几页；只要新岗位没凑够，就会一直翻到该上限
    MAX_PAGES = 5

    # xlsx 列顺序（XLSX_HEADERS 去掉「采集日期/来源/省份」）
    ROW_ORDER = ['城市', '职位名称', '岗位编号', '公司名称', '公司性质', '公司规模', '公司行业',
                 '招聘类型', '职位性质', '职位类别', '薪资范围', '招聘人数',
                 '学历要求', '经验要求', '专业要求', '工作地点', '详细地址',
                 '报名截止', '职位描述']

    # ==================== 字典加载 ====================
    _cities = None       # 城市字典缓存（BossCity.json 全部条目）
    _job_types = None    # 原始 848 条岗位
    _city_province = None   # 城市名 -> 省份名

    @classmethod
    def load_cities(cls):
        """读取 BossCity.json，返回城市/区县列表

        结构：[{province, provinceCode, provinceFullName, city, cityCode,
                cityFullName, district, districtCode, fullName}, ...]

        市级条目的 district 为空、districtCode 等于 cityCode；
        重庆为区县级条目，districtCode 为 BOSS 区县码。

        该文件为外部数据字典（不打包进 exe）。缺失时不做崩溃，
        返回空列表并在日志中给出明确放置指引。
        """
        if cls._cities is None:
            try:
                with open(CITY_FILE, encoding='utf-8') as f:
                    cls._cities = json.load(f)
            except FileNotFoundError:
                cls._cities = []
                cls._city_province = {}
                cls._dict_error = (
                    '缺少城市字典 BossCity.json，请放到：%s'
                    % os.path.dirname(CITY_FILE))
                logger.error('【BOSS直聘】' + cls._dict_error)
                return cls._cities
            except (OSError, json.JSONDecodeError) as e:
                cls._cities = []
                cls._city_province = {}
                cls._dict_error = '城市字典 BossCity.json 解析失败：%s' % e
                logger.error('【BOSS直聘】' + cls._dict_error)
                return cls._cities

            # 构建 城市名 -> 省份名（列表接口只返回 cityName，需要补省份）
            cls._city_province = {}
            for c in cls._cities:
                name, prov = c.get('city'), c.get('province')
                if name and prov:
                    cls._city_province.setdefault(name, prov)
            logger.info('【BOSS直聘】加载城市字典 %d 条' % len(cls._cities))
        return cls._cities

    @classmethod
    def load_job_types(cls):
        """读取 BossJobType.json，返回岗位列表

        结构：[{code, name, category, subcategory}, ...]
        该文件为外部数据字典（不打包进 exe），缺失时返回空并给出指引。
        """
        if cls._job_types is None:
            try:
                with open(JOBTYPE_FILE, encoding='utf-8') as f:
                    cls._job_types = json.load(f)
            except FileNotFoundError:
                cls._job_types = []
                cls._dict_error = (
                    '缺少岗位字典 BossJobType.json，请放到：%s'
                    % os.path.dirname(JOBTYPE_FILE))
                logger.error('【BOSS直聘】' + cls._dict_error)
                return cls._job_types
            except (OSError, json.JSONDecodeError) as e:
                cls._job_types = []
                cls._dict_error = '岗位字典 BossJobType.json 解析失败：%s' % e
                logger.error('【BOSS直聘】' + cls._dict_error)
                return cls._job_types
            logger.info('【BOSS直聘】加载岗位字典 %d 条' % len(cls._job_types))
        return cls._job_types

    @classmethod
    def province_of(cls, city_name):
        """按城市名查省份"""
        if cls._city_province is None:
            cls.load_cities()
        return (cls._city_province or {}).get(city_name, '')

    # ==================== 采集范围 ====================
    # 省份缩写 -> 省份名，便于 scope='sc' 这类简写
    PROVINCE_ALIAS = {
        'sc': '四川', 'yn': '云南', 'gz': '贵州', 'cq': '重庆',
        '四川': '四川', '云南': '云南', '贵州': '贵州', '重庆': '重庆',
    }

    @classmethod
    def target_cities(cls, scope='all'):
        """选定要采集的城市/区县

        scope:
          'all'        全部城市条目（文件里有多少条就多少条）
          'sc'/'yn'/'gz'/'cq'  按省份筛选（可用中文省份名）
          ['成都', '渝中区']    按区县名或城市名筛选
          [101270100, ...]     按 cityCode 筛选
        返回城市字典列表（每项含 districtCode，用于请求 city 参数）
        """
        cities = cls.load_cities()

        if scope in (None, '', 'all'):
            return list(cities)

        # 省份（仅字符串 scope 才查别名表，避免 list 触发 unhashable）
        if isinstance(scope, str):
            prov = cls.PROVINCE_ALIAS.get(scope)
            if prov:
                picked = [c for c in cities if c.get('province') == prov]
                return picked or list(cities)

        # 列表：名称或 code
        if isinstance(scope, (list, tuple, set)):
            wanted_names = {str(x).strip() for x in scope if not str(x).isdigit()}
            wanted_codes = {int(x) for x in scope if str(x).isdigit()}
            picked = []
            for c in cities:
                if (c.get('district') in wanted_names
                        or c.get('city') in wanted_names
                        or c.get('districtCode') in wanted_codes
                        or c.get('cityCode') in wanted_codes):
                    picked.append(c)
            return picked

        # 字符串但不是省份别名：当作单个区县/城市名
        s = str(scope).strip()
        if s.isdigit():
            return [c for c in cities
                    if c.get('districtCode') == int(s) or c.get('cityCode') == int(s)]
        return [c for c in cities
                if c.get('district') == s or c.get('city') == s]

    @classmethod
    def target_job_types(cls, scope='all'):
        """选定要采集的岗位

        scope:
          'all'            全部 848 个岗位
          ['兽医', 'Java']  按岗位名筛选（精确匹配，无结果时自动模糊匹配）
          ['100101', ...]  按岗位 code 筛选
          '医疗健康'        按一级分类筛选
          '后端开发'        按二级分类筛选
        返回岗位字典列表
        """
        types = cls.load_job_types()

        if scope in (None, '', 'all'):
            return list(types)

        if isinstance(scope, (list, tuple, set)):
            wanted_codes = {str(x).strip() for x in scope if str(x).isdigit()}
            wanted_names = [str(x).strip() for x in scope if not str(x).strip().isdigit()]

            picked = [t for t in types if t.get('code') in wanted_codes]
            # 逐个关键词处理：先精确，无结果再按名称包含兜底
            # （如「兽医」无精确项 -> 命中「畜牧兽医」；「护士」有精确项 -> 直接命中）
            for name in wanted_names:
                exact = [t for t in types if t.get('name') == name]
                if exact:
                    picked.extend(exact)
                else:
                    picked.extend([t for t in types
                                   if name and name in str(t.get('name') or '')])

            # 按 code 去重，保持原有顺序
            seen, out = set(), []
            for t in picked:
                key = t.get('code')
                if key not in seen:
                    seen.add(key)
                    out.append(t)
            return out

        s = str(scope).strip()
        if s.isdigit():
            return [t for t in types if t.get('code') == s]
        # 先按分类匹配，再按名称匹配
        by_cat = [t for t in types
                  if t.get('category') == s or t.get('subcategory') == s]
        if by_cat:
            return by_cat
        by_name = [t for t in types if t.get('name') == s]
        if by_name:
            return by_name
        # 再兜底：名称包含
        return [t for t in types if s in str(t.get('name') or '')]

    # ==================== 浏览器 / 登录 ====================
    _pw = None
    _last_city_code = None      # 当前页面所在城市，刷新 stoken 时复用

    @classmethod
    def launch(cls):
        """启动浏览器（PatchRight 单例），已启动则复用"""
        if cls._pw is not None:
            return cls._pw
        cls._pw = PatchRightClass()
        cls._pw.start_browser()
        cookie = get_config_value('login', 'boss_cookie', file=CONFIG_FILE)
        if cookie:
            try:
                cls._pw.context.add_cookies(eval(cookie))
            except Exception as e:
                logger.warning('【BOSS直聘】注入 cookie 失败：%s' % e)
        return cls._pw

    @classmethod
    def close(cls):
        """关闭浏览器"""
        if cls._pw is not None:
            try:
                cls._pw.close()
            except Exception as e:
                logger.warning('【BOSS直聘】关闭浏览器异常：%s' % e)
            cls._pw = None

    @classmethod
    def login(cls):
        """校验登录态（cookie 有效时会直接进首页）"""
        if cls._pw is None:
            cls.launch()
        try:
            ok = cls._pw.login(
                'https://www.zhipin.com/web/user/?ka=header-login',
                '//div[@class="user-nav"]//a[text()="消息"]',
                key='login.boss_cookie', file=CONFIG_FILE)
            if ok:
                logger.info('【BOSS直聘】登录成功')
            return ok
        except Exception as e:
            logger.error('【BOSS直聘】登录异常：%s' % e)
            return False

    @classmethod
    def goto_jobs(cls, city_code):
        """进入职位页

        必须先加载一次页面，让前端 JS 生成/刷新 __zp_stoken__，
        否则后续 fetch 会被判定「环境异常」(code=37)。

        注意超时要短：用户点「停止」时最多等这一下，
        原来 30s + 40s 两段等待会让停止像卡死一样。
        """
        if cls._pw is None:
            cls.launch()
        if cls._should_stop():
            return
        cls._last_city_code = city_code
        try:
            cls._pw.page.goto(
                'https://www.zhipin.com/web/geek/jobs?city=%s' % city_code,
                wait_until='domcontentloaded', timeout=15000)
        except PlaywrightError as e:
            logger.warning('【BOSS直聘】打开职位页失败（可继续用旧 stoken）：%s' % e)
            return
        if cls._should_stop():
            return
        try:
            cls._pw.page.wait_for_selector('[class*="job-card"]', timeout=8000)
        except PlaywrightTimeout:
            # 该城市可能无职位，卡片不出现也继续（后续用接口判断）
            logger.info('【BOSS直聘】city=%s 页面无职位卡片，继续接口请求' % city_code)

    # ==================== 接口层 ====================
    @classmethod
    def _post(cls, url, body):
        return cls._pw.page.evaluate(JS_POST, {'url': url, 'body': body})

    @classmethod
    def _get(cls, url):
        return cls._pw.page.evaluate(JS_GET, {'url': url})

    @classmethod
    def build_list_body(cls, page, city_code, position_code='', query=''):
        """构造列表请求体（顺序与真实请求一致）"""
        return {
            'page': page,
            'pageSize': cls.DEFAULT_PAGE_SIZE,
            'city': str(city_code),
            'position': str(position_code) if position_code else '',
            'query': query or '',
            'expectInfo': '',
            'multiSubway': '',
            'multiBusinessDistrict': '',
            'jobType': '',
            'salary': '',
            'experience': '',
            'degree': '',
            'industry': '',
            'scale': '',
            'stage': '',
            'scene': 1,
            'encryptExpectId': '',
        }

    @classmethod
    def get_page_info(cls, page_id, city_code, position_code='', query=''):
        """获取单页职位列表

        返回 (jobList, total)；失败返回 (None, 0) 以便上层重试
        """
        url = '%s?_=%d' % (cls.LIST_API, int(time.time() * 1000))
        body = cls.build_list_body(page_id, city_code, position_code, query)

        for attempt in range(1, cls.RETRY_TIMES + 2):
            if cls._should_stop():
                return None, 0
            try:
                res = cls._post(url, body)
            except Exception as e:
                logger.warning('【BOSS直聘】列表请求异常(%d)：%s' % (attempt, e))
                if not cls._sleep(cls.RETRY_SLEEP):
                    return None, 0
                continue

            data = res.get('data') or {}
            if data.get('code') == 0:
                zp = data.get('zpData') or {}
                return (zp.get('jobList') or []), (zp.get('totalCount') or 0)

            logger.warning('【BOSS直聘】列表 code=%s msg=%s (page=%s city=%s pos=%s)'
                           % (data.get('code'), data.get('message'),
                              page_id, city_code, position_code))
            # code=37 环境异常：重新走一次职位页刷新 stoken
            if data.get('code') == 37:
                try:
                    cls.goto_jobs(city_code)
                except (PlaywrightError, OSError) as e:
                    logger.warning('【BOSS直聘】刷新 stoken 失败：%s' % e)
            if not cls._sleep(cls.RETRY_SLEEP):
                return None, 0

        return None, 0

    @classmethod
    def fetch_detail(cls, security_id, lid='', city_code=None):
        """获取职位详情，返回 zpData；失败返回 None

        BOSS 的 __zp_stoken__ 有时效，连续请求详情几十次后会被判定
        「环境异常」(code=37)。命中时重新加载职位页以刷新 stoken 后重试，
        而不是单纯 sleep 等待（sleep 无法恢复已过期的 stoken）。
        """
        if not security_id:
            return None
        url = '%s?securityId=%s' % (cls.DETAIL_API, security_id)
        if lid:
            url += '&lid=%s' % lid
        url += '&_=%d' % int(time.time() * 1000)

        for attempt in range(1, cls.RETRY_TIMES + 2):
            if cls._should_stop():
                return None
            try:
                res = cls._get(url)
            except Exception as e:
                logger.warning('【BOSS直聘】详情请求异常(%d)：%s' % (attempt, e))
                if not cls._sleep(cls.RETRY_SLEEP):
                    return None
                continue

            data = res.get('data') or {}
            if data.get('code') == 0:
                return data.get('zpData') or {}

            code = data.get('code')
            logger.warning('【BOSS直聘】详情 code=%s msg=%s (尝试 %d/%d)'
                           % (code, data.get('message'), attempt,
                              cls.RETRY_TIMES + 1))

            # 环境异常 / 频控：刷新页面重新生成 stoken 再试
            if code in (37, -6, 200013):
                if cls._should_stop():
                    return None
                try:
                    cls.goto_jobs(city_code or cls._last_city_code or '101270100')
                except Exception as e:
                    logger.warning('【BOSS直聘】刷新 stoken 失败：%s' % e)
                # 刷新后多等一会儿，给风控一个冷却窗口
                if not cls._sleep(max(cls.RETRY_SLEEP, 2.5) * attempt):
                    return None
                continue

            if not cls._sleep(cls.RETRY_SLEEP):
                return None
        return None

    # ==================== 字段加工 ====================
    @staticmethod
    def extract_major_from_skills(skills):
        """从 showSkills 结构化标签提取专业要求

        '兽医相关专业' -> 兽医 ; '专业不限' -> 不限 ; 无专业标签 -> ''
        """
        if not skills:
            return ''
        for s in skills:
            s = str(s).strip()
            if not s:
                continue
            if re.search(r'专业\s*不?\s*限|不限专业', s):
                return '不限'
            m = re.match(r'^(.+?)(?:相关)?专业$', s)
            if m:
                cand = m.group(1).strip()
                if cand and len(cand) <= 30 and not re.search(r'经验|技能|证书|资格', cand):
                    return cand
        return ''

    @classmethod
    def extract_major(cls, description, skills=None):
        """专业要求：showSkills 优先 -> 描述正则 -> 兜底「不限」"""
        major = cls.extract_major_from_skills(skills)
        if major:
            return major

        if not description:
            return '不限'
        text = re.sub(r'<[^>]+>', '\n', str(description))

        for pattern in _MAJOR_PATTERNS:
            for m in re.finditer(pattern, text):
                cand = (m.group(1) or '').strip(' 　，,、;；:：/')
                cand = re.sub(r'[等或和与及]?\s*(?:相关|其它|其他|类似).*$', '', cand)
                cand = re.sub(r'(?:优先|者优先|均可|不限|即可).*$', '', cand).strip()
                if not cand or len(cand) > 60:
                    continue
                if '不限' in cand:
                    return '不限'
                if any(h in cand for h in _MAJOR_HINT):
                    return cand

        if re.search(r'专业\s*不?\s*限|不限专业', text):
            return '不限'
        return '不限'

    @staticmethod
    def _recruit_type(job_type, experience):
        """招聘类型：社会招聘 / 校园招聘 / 实习"""
        label = JOB_TYPE_MAP.get(job_type)
        if label:
            return label
        exp = experience or ''
        if '在校' in exp or '应届' in exp:
            return '校园招聘'
        return '社会招聘'

    @staticmethod
    def _job_nature(job_type, job_name, recruit_type):
        """职位性质：全职 / 兼职 / 实习"""
        if recruit_type == '实习' or '实习' in (job_name or ''):
            return '实习'
        if recruit_type == '兼职' or job_type in (3, 4):
            return '兼职'
        return '全职'

    @classmethod
    def item_to_row(cls, item, detail):
        """把「列表项 + 详情」整理成字段字典（不含采集日期/来源/省份）"""
        ji = (detail or {}).get('jobInfo') or {}
        br = (detail or {}).get('brandComInfo') or {}

        city = item.get('cityName') or ji.get('locationName') or ''
        area = item.get('areaDistrict') or ''
        business = item.get('businessDistrict') or ''
        location = '-'.join(x for x in (city, area, business) if x)

        job_type = ji.get('jobType', item.get('jobType'))
        experience = ji.get('experienceName') or item.get('jobExperience') or ''
        job_name = ji.get('jobName') or item.get('jobName') or ''
        recruit_type = cls._recruit_type(job_type, experience)
        nature = cls._job_nature(job_type, job_name, recruit_type)

        description = ji.get('postDescription') or ''
        # 专业要求：详情 showSkills 优先，其次列表 skills
        skills = ji.get('showSkills') or item.get('skills') or []

        return {
            '城市': city,
            '职位名称': job_name,
            '岗位编号': str(ji.get('encryptId') or item.get('encryptJobId') or ''),
            '公司名称': br.get('brandName') or item.get('brandName') or '',
            # BOSS 无「公司性质」，用融资阶段替代
            '公司性质': br.get('stageName') or item.get('brandStageName') or '',
            '公司规模': br.get('scaleName') or item.get('brandScaleName') or '',
            '公司行业': br.get('industryName') or item.get('brandIndustry') or '',
            '招聘类型': recruit_type,
            '职位性质': nature,
            '职位类别': ji.get('positionName') or '',
            '薪资范围': ji.get('salaryDesc') or item.get('salaryDesc') or '',
            '招聘人数': ji.get('recruitmentCountDesc') or '若干',
            '学历要求': ji.get('degreeName') or item.get('jobDegree') or '不限',
            '经验要求': experience or '不限',
            '专业要求': cls.extract_major(description, skills),
            '工作地点': location,
            '详细地址': ji.get('address') or '',
            '报名截止': '长期有效',        # BOSS 无截止时间
            '职位描述': description,
        }

    @classmethod
    def parser_page_info(cls, province_name, page_info, crawl_date=None,
                         with_detail=True, on_item=None):
        """把单页岗位列表解析为 xlsx 行

        page_info : get_page_info 返回的 jobList
        with_detail: True 时逐条请求详情（拿到职位描述/地址）；False 只用列表字段
        on_item   : 每成功解析一条时的回调（用于实时日志）
        返回 [[采集日期, 来源, 省份, 城市, ...], ...]

        逐条之间检查停止标志、等待可被打断：否则点「停止」要等整页
        （3 条 × 请求 + 2s 间隔）跑完才响应。
        """
        crawl_date = crawl_date or datetime.now().strftime('%Y-%m-%d')
        rows = []

        for item in (page_info or []):
            if cls._should_stop():
                logger.info('【BOSS直聘】用户终止采集')
                break
            detail = None
            if with_detail:
                detail = cls.fetch_detail(item.get('securityId'), item.get('lid'))
                if detail is None:
                    logger.warning('【BOSS直聘】详情获取失败，跳过：%s'
                                   % item.get('jobName'))
                    continue

            d = cls.item_to_row(item, detail)
            row = [crawl_date, cls.source_code,
                   province_name or cls.province_of(d.get('城市'))] \
                  + [d.get(k, '') for k in cls.ROW_ORDER]
            rows.append(row)
            if on_item:
                on_item(row)
            if with_detail:
                # 可打断的间隔（原来是 time.sleep，点停止要干等 2 秒）
                if not cls._sleep(cls.DEFAULT_DELAY):
                    break

        return rows

    # ==================== 单组合采集 ====================
    @classmethod
    def get_single_combo(cls, wb=None, ws=None, data_file=None,
                         city_info=None, job_type_info=None,
                         yesterday_data=None, write=True, with_detail=True,
                         max_pages=None, on_data=None, on_page=None,
                         existing_ids=None, seen_ids=None):
        """采集「一个城市 × 一个岗位」的新职位

        city_info    : BossCity.json 中的一条（用 districtCode 作 city 参数）
        job_type_info: BossJobType.json 中的一条（用 code 作 position 参数）
                       传 None 表示不限定岗位
        existing_ids : 历史上已采集过的岗位编号集合（跨组合共享）。命中即跳过，
                       且**不占用** MAX_JOBS_PER_POSITION 的名额。
        seen_ids     : 本轮已采到的编号集合（跨组合共享），作用同上。

        暂停/停止由 BaseSpider 的类级状态（_pause_event / _running_probe）控制，
        通过 cls._wait() / cls._sleep() 生效。
        返回本组合新增行
        """
        city_info = city_info or {}
        city_code = city_info.get('districtCode') or city_info.get('cityCode')
        city_name = city_info.get('district') or city_info.get('city') or ''
        province_name = city_info.get('province') or ''

        position_code = ''
        position_name = '全部岗位'
        if job_type_info:
            position_code = str(job_type_info.get('code') or '')
            position_name = job_type_info.get('name') or position_code

        all_rows = []
        crawl_date = datetime.now().strftime('%Y-%m-%d')
        seen = cls.init_seen(yesterday_data)
        # 已知岗位：历史库 + 本轮已采，命中直接跳过
        known_ids = existing_ids if existing_ids is not None else set()
        if seen_ids is not None:
            known_ids = known_ids | seen_ids
        pages = max_pages or cls.DEFAULT_PAGES
        # 本组合最多取几条**新**职位：Boss.MAX_JOBS_PER_POSITION（0 或负数 = 不限制）
        limit = cls.MAX_JOBS_PER_POSITION
        added = 0               # 本组合已采到的新职位条数（重复的不算）
        scanned = 0             # 本组合已扫描过的列表条目数（用于日志）
        started = time.time()

        for page_id in range(1, pages + 1):
            if not cls._wait():
                logger.info('【BOSS直聘】用户终止采集')
                break

            if limit > 0 and added >= limit:
                break

            page_started = time.time()
            page_list, total = cls.get_page_info(
                page_id, city_code, position_code)

            if page_list is None:
                logger.info('【BOSS直聘】%s-%s 第%d页请求失败'
                            % (city_name, position_name, page_id))
                if not cls._sleep(cls.RETRY_SLEEP):
                    break
                page_list, total = cls.get_page_info(
                    page_id, city_code, position_code)
                if page_list is None:
                    break

            if not page_list:
                break

            # 末页判断要用原始页长度，必须在过滤前记录
            raw_page_len = len(page_list)

            # 只保留没采过的岗位；已存在的直接跳过，不占名额
            fresh = [it for it in page_list
                     if str(it.get('encryptJobId') or '') not in known_ids]
            skipped = raw_page_len - len(fresh)
            scanned += raw_page_len

            # 只取还差的那几条（多出的不请求详情）
            if limit > 0:
                remaining = limit - added
                if remaining <= 0:
                    break
                if len(fresh) > remaining:
                    fresh = fresh[:remaining]
            if not fresh:
                logger.info('【BOSS直聘】%s-%s 第%d页 %d 条均为已采岗位，继续翻页'
                            % (city_name, position_name, page_id, skipped))
                # 没有新岗位时继续翻页找，而不是直接结束
                if raw_page_len < cls.DEFAULT_PAGE_SIZE:
                    break
                if total and page_id * cls.DEFAULT_PAGE_SIZE >= total:
                    break
                if not cls._sleep(cls.PAGE_DELAY):
                    break
                continue

            parsed = cls.parser_page_info(
                province_name, fresh, crawl_date,
                with_detail=with_detail)
            count = cls._append_rows(parsed, all_rows, seen, ws, write, on_data)
            # 采到的编号登记为已知，避免后续组合重复请求
            for it in fresh:
                jid = str(it.get('encryptJobId') or '')
                if jid:
                    known_ids.add(jid)
                    if seen_ids is not None:
                        seen_ids.add(jid)
            added += count

            if write and count and wb is not None and data_file is not None:
                cls._save(wb, data_file)

            elapsed = time.time() - started
            logger.info('【BOSS直聘】%s-%s 第%d页 新增%d条（跳过已采%d条），'
                        '本组合累计%d/%s条，本页%.1fs，累计%.1fs'
                        % (city_name, position_name, page_id, count, skipped,
                           added, limit or '不限',
                           time.time() - page_started, elapsed))
            if on_page is not None:
                on_page(page_id, count, len(all_rows), elapsed)

            # 已达本组合上限
            if limit > 0 and added >= limit:
                break

            # 末页判断（用原始页长度）
            if raw_page_len < cls.DEFAULT_PAGE_SIZE:
                break
            if total and page_id * cls.DEFAULT_PAGE_SIZE >= total:
                break
            if not cls._sleep(cls.PAGE_DELAY):
                break

        if limit > 0 and added < limit:
            logger.info('【BOSS直聘】%s-%s 本组合仅采到 %d/%d 条新职位'
                        '（扫描 %d 条列表，可用页已翻完）'
                        % (city_name, position_name, added, limit, scanned))

        return all_rows

    # ==================== 主流程 ====================
    @classmethod
    def run(cls, data_file=None, city_scope='all', position_scope='all',
            update_duplicate=None,
            max_pages=None, with_detail=True, delay=None, page_delay=None,
            pause_event=None, is_running=None,
            on_progress=None, on_data=None, on_city_done=None, on_page=None,
            on_complete=None, on_error=None):
        """采集入口：登录 -> 逐城市 × 逐岗位 -> 增量写入 xlsx

        city_scope     : 见 target_cities
        position_scope : 见 target_job_types；传 None/[] 表示不限定岗位
        max_pages      : 每个「城市×岗位」组合最多翻几页
                         传 None 时取 Boss.MAX_PAGES
        每个「城市×岗位」组合最多采 Boss.MAX_JOBS_PER_POSITION 条**新**职位
        （默认 3）。已存在于 xlsx 的岗位会被跳过且不占名额，会继续翻页找新的。
        with_detail    : 是否逐条取详情（关掉更快，但无职位描述/详细地址）
        回调：
          on_progress(done, total, label)   组合级进度
          on_data(row)                      每条新数据
          on_city_done(city_name)           一个城市结束
          on_page(page_id, added, city_total, elapsed)  页级进度
          on_complete(msg) / on_error(msg)
        """
        data_file = data_file or os.path.join(_BASE_DIR, 'BOSS直聘数据.xlsx')
        if max_pages is None:
            max_pages = cls.MAX_PAGES
        if delay is not None:
            cls.DEFAULT_DELAY = delay
        if page_delay is not None:
            cls.PAGE_DELAY = page_delay

        cities = cls.target_cities(city_scope)
        job_types = cls.target_job_types(position_scope) \
            if position_scope not in (None, '', []) else [None]

        # 数据字典缺失时给出明确提示（字典是外部文件，不打包进 exe）
        if not cities:
            msg = getattr(cls, '_dict_error', None) or \
                '未找到匹配的城市，请检查 city_scope 或 config\\BossCity.json'
            logger.error('【BOSS直聘】' + msg)
            if on_complete:
                on_complete(msg)
            return 0, None

        if position_scope not in (None, '', []) and not any(job_types):
            msg = getattr(cls, '_dict_error', None) or \
                '未找到匹配的岗位，请检查 position_scope 或 config\\BossJobType.json'
            logger.error('【BOSS直聘】' + msg)
            if on_complete:
                on_complete(msg)
            return 0, None

        combos = len(cities) * len(job_types)

        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)
        # 历史全部岗位编号：跨组合共享，命中即跳过（保证只采没采过的岗位）
        existing_ids = cls.load_existing_ids(data_file)
        seen_ids = set()
        cls._begin_run(pause_event, is_running,
                            update_duplicate=update_duplicate)

        logger.info('【BOSS直聘】历史已有 %d 个岗位编号，本次只采新增岗位'
                    % len(existing_ids))

        total_rows = 0
        failed = []
        stopped = False

        try:
            cls.launch()
            if not cls.login():
                msg = '登录未确认成功，已停止'
                logger.error('【BOSS直聘】' + msg)
                if on_complete:
                    on_complete(msg)
                return 0, None

            logger.info('【BOSS直聘】待采 %d 个城市 × %d 个岗位 = %d 个组合，'
                        '每组合最多 %d 页 / %s 条新职位'
                        % (len(cities), len(job_types), combos, max_pages,
                           cls.MAX_JOBS_PER_POSITION or '不限'))

            done = 0
            for city_info in cities:
                if not cls._wait():
                    logger.info('【BOSS直聘】用户终止采集')
                    stopped = True
                    break

                city_name = city_info.get('district') or city_info.get('city')
                city_code = city_info.get('districtCode') or city_info.get('cityCode')

                # 每个城市只加载一次职位页（刷新 stoken）
                try:
                    cls.goto_jobs(city_code)
                except Exception as e:
                    logger.warning('【BOSS直聘】%s 页面加载异常：%s' % (city_name, e))

                for job_type_info in job_types:
                    if not cls._wait():
                        stopped = True
                        break

                    done += 1
                    label = '%s/%s' % (
                        city_name,
                        (job_type_info or {}).get('name') or '全部岗位')
                    if on_progress:
                        on_progress(done, combos, label)

                    try:
                        rows = cls.get_single_combo(
                            wb, ws, data_file,
                            city_info=city_info,
                            job_type_info=job_type_info,
                            yesterday_data=yesterday_data,
                            write=True, with_detail=with_detail,
                            max_pages=max_pages,
                            on_data=on_data, on_page=on_page,
                            existing_ids=existing_ids, seen_ids=seen_ids)
                        total_rows += len(rows)
                    except Exception as e:
                        key = '%s-%s' % (city_name, label)
                        failed.append(key)
                        logger.error('【BOSS直聘】%s 采集异常：%s' % (key, e))
                        if on_error:
                            on_error('%s: %s' % (key, e))

                    if cls._should_stop():
                        stopped = True
                        break
                    if not cls._sleep(cls.PAGE_DELAY):
                        stopped = True
                        break

                if on_city_done:
                    on_city_done(city_name)
                if stopped or cls._should_stop():
                    stopped = True
                    break

        finally:
            try:
                cls._save(wb, data_file, force=True)
            except Exception as e:
                logger.error('【BOSS直聘】保存失败：%s' % e)
            cls.close()

        if failed:
            logger.info('【BOSS直聘】失败组合 %d 个：%s'
                        % (len(failed), '、'.join(failed[:10])))

        msg = cls._finish_message(total_rows, stopped, len(failed))
        logger.info('【BOSS直聘】' + msg)
        if on_complete:
            on_complete(msg)
        return total_rows, cls._saved_path or data_file


# ==================== 简易入口（脚本直接运行） ====================
if __name__ == '__main__':
    from getJobs import XLSX_HEADERS

    print('BOSS 直聘采集')
    print('  城市字典:', CITY_FILE)
    print('  岗位字典:', JOBTYPE_FILE)
    print()

    cities = Boss.target_cities('sc')
    types = Boss.target_job_types(['兽医', '护士'])
    print('示例范围：四川 %d 个城市条目 × %d 个岗位 = %d 组合'
          % (len(cities), len(types), len(cities) * len(types)))
    print('  岗位:', [t['name'] for t in types])
    print()
    print('采集参数（Boss 类属性）：')
    print('  每组合最多 %s 条新职位 / %d 页'
          % (Boss.MAX_JOBS_PER_POSITION or '不限', Boss.MAX_PAGES))
    print()
    print('字段顺序：')
    for i, h in enumerate(XLSX_HEADERS):
        print('  %2d. %s' % (i + 1, h))
    print()
    print('调用示例：')
    print("  Boss.run(city_scope='cq', position_scope=['兽医'], max_pages=1)")
