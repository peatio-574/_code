# coding='utf-8'
"""智联招聘（四川 + 重庆）岗位采集。

数据采集流程：登录（手机号 + 短信验证码）-> 逐城市分页采集 -> 去重增量写入 xlsx。
接口需要浏览器登录态，内部用 Playwright 维护后台事件循环与浏览器页面，
对外暴露与 GuoPin 风格一致的类方法（get_page_info / parser_page_info / get_single_city / run）。
"""
import asyncio
import ast
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from html import unescape as html_unescape

# 浏览器驱动：优先用 patchright（与 playwright API 完全兼容）。
# 这样打包时只需捆绑一份驱动（约 100MB），可裁掉 playwright 驱动，显著减小体积。
# patchright 是 playwright 的反检测 fork，对普通站点同样可用。
try:
    from patchright.async_api import async_playwright
except ImportError:                                    # 未装 patchright 时回退
    from playwright.async_api import async_playwright

from getJobs import XLSX_HEADERS, BaseSpider, load_config
from Logger import logger


# ==================== 城市配置（config/zhipin_cities.json） ====================
# 原先硬编码 21 个城市，现改为读 JSON；文件缺失时回退到内置默认值。
_DEFAULT_ZHIPIN_CITIES = [
    {'province': '四川', 'city': n, 'cityCode': c, 'cityFull': f}
    for n, c, f in [
        ('成都', 801, '成都市'), ('自贡', 802, '自贡市'),
        ('攀枝花', 803, '攀枝花市'), ('泸州', 804, '泸州市'),
        ('德阳', 805, '德阳市'), ('绵阳', 806, '绵阳市'),
        ('广元', 807, '广元市'), ('遂宁', 808, '遂宁市'),
        ('内江', 809, '内江市'), ('乐山', 810, '乐山市'),
        ('南充', 811, '南充市'), ('眉山', 812, '眉山市'),
        ('宜宾', 813, '宜宾市'), ('广安', 814, '广安市'),
        ('达州', 815, '达州市'), ('雅安', 816, '雅安市'),
        ('巴中', 817, '巴中市'), ('资阳', 818, '资阳市'),
        ('阿坝', 819, '阿坝藏族羌族自治州'), ('甘孜', 820, '甘孜藏族自治州'),
        ('凉山', 821, '凉山彝族自治州'), ('重庆', 551, '重庆市'),
    ]
]

_CITY_CFG = load_config('zhipin_cities.json', {}) or {}
ZHIPIN_CITIES = _CITY_CFG.get('cities') or _DEFAULT_ZHIPIN_CITIES


class ZhiPin(BaseSpider):
    """智联招聘（四川 + 重庆）岗位采集类。
    数据采集流程：登录（手机号 + 短信验证码）-> 逐城市分页采集 -> 去重增量写入 xlsx。
    说明：
      * 智联接口需要浏览器登录态，本类内部用 Playwright 维护一个后台事件循环与浏览器页面，
        对外暴露与 GuoPin 风格一致的类方法（get_page_info / parser_page_info / get_single_city / run）。
      * run() 会在命令行提示输入手机号与短信验证码（可传 phone 并在复用登录态时自动跳过）。
    """
    # 网站名称
    web_name = '智联招聘'
    API = "https://fe-api.zhaopin.com/c/i/search/positions"

    # 四川 21 市 + 重庆（来自 config/zhipin_cities.json，缺失时用内置默认）
    SC_CITIES = [(c['province'], c['city']) for c in ZHIPIN_CITIES]
    CITY_ID = {c['city']: c['cityCode'] for c in ZHIPIN_CITIES}
    CITY_FULL = {c['city']: c['cityFull'] for c in ZHIPIN_CITIES}

    # 页面 / 抓取参数（越大越容易触发风控，可按需调整）
    DEFAULT_PAGE_SIZE = 20            # 每页条数（与接口 pageSize 一致）
    DEFAULT_PAGES = 100000            # 安全上限；实际循环靠“空页/末页”自动结束，即有多少爬多少
    DEFAULT_DELAY = 0.8               # 每页间隔秒数
    RETRY_SLEEP = 5                   # 单页请求失败后的重试等待（秒）
    SAVE_INTERVAL = 10                # 两次写盘的最小间隔（秒），避免每页都重写整本 xlsx

    # xlsx 列顺序（与 XLSX_HEADERS 去掉「采集日期/来源/省份」后的部分一致）
    ROW_ORDER = ["城市", "职位名称", "岗位编号", "公司名称", "公司性质", "公司规模", "公司行业",
                 "招聘类型", "职位性质", "职位类别", "薪资范围", "招聘人数",
                 "学历要求", "经验要求", "专业要求", "工作地点", "详细地址",
                 "报名截止", "职位描述"]

    # 登录态：与其他平台一致，存程序同级的 config.ini
    # 打包后 __file__ 位于临时解压目录(_MEIPASS)，不可用；以 exe 所在目录为基准。
    if getattr(sys, 'frozen', False):
        _base = os.path.dirname(sys.executable)
    else:
        _base = os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE = os.path.join(_base, "config.ini")
    CONFIG_SECTION = "login"
    CONFIG_OPTION = "zhipin_cookie"    # 存 str([cookie, ...])，另存 zhipin_cookie_api

    # 类级浏览器/事件循环状态（懒加载，供同步方法复用）
    _loop = None
    _thread = None
    _pw = None
    _browser = None
    _context = None
    _page = None

    # ==================== 清洗 / 字段映射 ====================

    @staticmethod
    def clean_html(s):
        """去除 HTML 标签，保留段落换行，HTML 实体反转义。"""
        if not s:
            return ""
        s = str(s)
        s = re.sub(r"(?i)<br\s*/?>", "\n", s)
        s = re.sub(r"(?i)</(p|div|li|ul|ol|h[1-6]|tr|table|section)>", "\n", s)
        s = re.sub(r"(?i)<(p|div|li|ul|ol|h[1-6]|tr|table|section)[^>]*>", "", s)
        s = re.sub(r"<[^>]+>", "", s)
        s = html_unescape(s)
        lines = [ln.strip() for ln in s.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    # ---------- 专业要求抽取 ----------
    # 智联搜索接口没有结构化的“专业要求”字段（needMajor 恒为空），
    # 专业要求只存在于职位描述文本里，这里按常见写法做启发式提取。
    _MAJOR_NOT_EXACT = set(
        "管理 技术 设计 工程 学科 专业 知识 能力 技能 培训 团队 服务 咨询 经验 "
        "工作 运营 发展 实践 相关 优先 学历 本科 大专 要求".split())
    _MAJOR_NOT_SUFFIX = (
        "知识", "能力", "技能", "培训", "团队", "服务", "咨询", "讲解", "介绍",
        "素养", "水平", "评估", "测试", "顾问", "机构", "岗位", "课程", "方案",
        "建议", "指导", "风险", "认知", "职责", "人员", "精神", "理解", "素质",
        "经验", "运营", "成长", "实践", "形象", "术语", "词汇", "文书",
        "面试", "回答", "答辩", "训练", "协同", "分包", "优先", "以及", "背景")
    _MAJOR_HINT = (
        "学", "工程", "科学", "管理", "技术", "信息", "医学", "教育", "经济", "金融",
        "会计", "财务", "设计", "电子", "机械", "材", "化学", "生物", "计算机", "软件",
        "通信", "自动化", "建筑", "土木", "车辆", "能源", "动力", "制药", "药学", "营销",
        "传播", "法学", "法律", "农", "畜牧", "兽医", "环境", "安全", "工业", "物流",
        "贸易", "英语", "语", "美术", "视觉", "动画", "艺术", "新闻", "政治", "国际",
        "统计", "数学", "物理", "地理", "地质", "测绘", "测控", "仪器", "电气", "电力",
        "物联网", "网络", "智能", "数据", "分析", "审计", "税务", "工商", "行政", "人力",
        "护理", "临床", "中医", "中药", "机电", "烹饪", "食品", "纺织", "服装",
        "广告", "旅游", "酒店", "供应链", "冶金", "矿业", "石油", "海")
    _MAJOR_LEAD = re.compile(
        r"^(?:\s*(?:任职要求|岗位要求|职位要求|任职资格|应聘要求|资格要求|人员要求|招聘要求|"
        r"学历要求|教育背景|教育经历|专业要求|专业方向|专业类别|所学专业|专业|要求|"
        r"统招|全日制|正规院校|国家|省属|重点|一本|二本|三本|985|211|"
        r"本科|大专|专科|硕士|博士|研究生|中专|高中|初中|毕业|应届|在校|学生|"
        r"及以上|以上|以下|学历|学位|具有|具备|优先|均可|即可|相关|其他|以及|\d+|"
        r"[（(][^）)]*[）)])\s*[,，、;；:：.。\-—/]?\s*)+")

    @classmethod
    def _tidy_major(cls, cand):
        cand = cand.strip(" 　，,、;；:：/")
        cand = re.sub(r"(?:等)?(?:相关)?专业.*$", "", cand)
        cand = re.sub(r"(?:等|或|和|与|及|、)?\s*(?:相关|其它|其他|类似).*$", "", cand)
        cand = re.sub(r"(?:等|及|和|与|或|其他|其它|、|，|,|/|·|-|—|的)+$", "", cand).strip()
        cand = re.sub(r"(?:优先|者优先|均可|不限|即可).*$", "", cand).strip()
        cand = cls._MAJOR_LEAD.sub("", cand)
        cand = re.sub(r"^[的或及和与相关、，,;；:：/-—]+", "", cand)
        return cand.strip(" 　，,、;；:：/")

    @classmethod
    def _looks_like_major(cls, cand):
        if not cand or len(cand) > 80:
            return False
        toks = [t.strip() for t in re.split(r"[、，,/]|及|和|与|或", cand) if t.strip()]
        for t in toks:
            if t in cls._MAJOR_NOT_EXACT:
                continue
            if any(t.endswith(w) for w in cls._MAJOR_NOT_SUFFIX):
                continue
            if any(h in t for h in cls._MAJOR_HINT):
                return True
        return False

    @classmethod
    def extract_major(cls, text):
        """从职位描述文本中提取“专业要求”；提取不到返回空串（调用方回退为“不限”）。"""
        if not text:
            return ""
        t = cls.clean_html(text)
        # 1) “专业要求：xxx / 专业：xxx”等显式标签
        for m in re.finditer(
                r"(?:所学专业|专业要求|专业方向|专业类别|专业背景|专业)\s*[:：]\s*([^\n]{1,80})", t):
            raw = m.group(1)
            if "不限" in raw:
                return "不限"
            cand = cls._tidy_major(raw)
            if cls._looks_like_major(cand):
                return cand
        # 2) “专业不限 / 不限专业 / 专业、教资不限”
        if re.search(r"专业\s*不?\s*限|不限专业", t) \
                or re.search(r"专业[、，,][^，,。；;\n]{0,8}不限", t):
            return "不限"
        # 3) “xx、yy等相关专业”列表
        for m in re.finditer(r"([^，,。；;：:\n]{2,80}?)(?:等)?(?:相关)?专业", t):
            cand = cls._tidy_major(m.group(1))
            if cls._looks_like_major(cand):
                tail = t[m.end():m.end() + 6]
                if any(w in tail for w in ("知识", "技能", "能力", "术语", "词汇")):
                    continue
                return cand
        return ""

    # ---------- 学历要求抽取 ----------
    # 列表接口在不同卡片类型（登录/推荐/广告位）下字段位置不一致：
    # 有时只在顶层 education，有时只在 jobDetailData.position.base.education，
    # 偶尔两者都缺，只能从职位描述里提取。这里按多来源兜底。
    _EDU_KEYS = ("education", "educationName", "degreeName", "degree",
                 "educationCn", "educationLevel")
    _EDU_DESC_PATTERNS = (
        r"(?:学历要求|学历|最低学历|教育背景)\s*[:：]\s*([^\n，,。；;]{1,20})",
        r"(博士|硕士|本科|大专|专科|中专|高中|初中|学历不限|不限学历)",
    )
    _EDU_LEVELS = ("博士", "硕士", "本科", "大专", "专科", "中专", "高中", "初中")
    _edu_warned = False

    @staticmethod
    def _first_text(*values):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def extract_education(cls, text):
        """从职位描述中提取学历要求；提取不到返回空串。"""
        if not text:
            return ""
        body = cls.clean_html(text)
        for pattern in cls._EDU_DESC_PATTERNS:
            matched = re.search(pattern, body)
            if not matched:
                continue
            raw = matched.group(1) if matched.groups() else matched.group(0)
            if "不限" in raw:
                return "不限"
            for level in cls._EDU_LEVELS:
                if level in raw:
                    return "大专" if level == "专科" else level
        return ""

    @classmethod
    def _normalize_education(cls, value):
        text = (value or "").strip()
        if not text:
            return ""
        if "不限" in text:
            return "不限"
        for level in cls._EDU_LEVELS:
            if level in text:
                return "大专" if level == "专科" else level
        return text

    @classmethod
    def _warn_missing_education(cls, it):
        """首次遇到学历缺失时记录一条明细，便于排查接口字段变化。"""
        if cls._edu_warned:
            return
        cls._edu_warned = True
        logger.warning('【智联招聘】学历要求字段缺失，jobId=%s，jdCardType=%s，顶层字段=%s'
                       % (it.get("jobId"), it.get("jdCardType"),
                          ",".join(sorted(it.keys()))[:500]))

    @staticmethod
    def item_to_row(it, prov, city):
        """把接口返回的单条岗位数据整理成字段字典（不含采集日期/省份）。"""
        jd = it.get("jobDetailData") or {}
        position = jd.get("position") or {}
        pb = position.get("base") or {}
        dt = position.get("date") or {}
        de = position.get("desc") or {}
        jt = position.get("jobType") or {}
        # 城市全称：优先查表，缺失时降级为原名（原写法直接索引会 KeyError）
        city_full = ZhiPin.CITY_FULL.get(city, city)
        district = it.get("cityDistrict") or ""
        work_place = ("%s-%s" % (it.get("workCity") or city, district)) if district \
            else (it.get("workCity") or city)

        edu = ZhiPin._first_text(
            *(it.get(key) for key in ZhiPin._EDU_KEYS),
            *(pb.get(key) for key in ZhiPin._EDU_KEYS),
        )
        if not edu:
            edu = ZhiPin.extract_education(de.get("description") or it.get("jobSummary") or "")
        if not edu:
            ZhiPin._warn_missing_education(it)
        edu = ZhiPin._normalize_education(edu) or "不限"

        exp = ZhiPin._first_text(it.get("workingExp"), pb.get("positionWorkingExp"),
                                 pb.get("workingExp")) or "不限"
        # ---------- 薪资 ----------
        # 取值优先级：salaryReal（结构化区间）> salary60（展示文案）> salary
        # 智联部分岗位只给「面议」「薪资面议」这类文案，直接落到 0~0 会让
        # 数据看起来像异常，这里统一规范化为「面议」。
        salary_text = ""
        raw_salary = it.get("salaryReal") or pb.get("salaryReal") or ""
        matched = re.match(r"\s*(\d+)\s*[-~至]\s*(\d+)", str(raw_salary))
        if matched:
            low, high = int(matched.group(1)), int(matched.group(2))
            salary_text = "%s~%s 元/月" % (low, high)
        else:
            text_salary = (it.get("salary60") or pb.get("salary") or "").strip()
            # 文案里若带数字区间，提取出来
            m2 = re.search(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*[kK千万]?",
                           text_salary)
            if m2:
                salary_text = text_salary
            elif text_salary and re.search(r"面议|商议|谈判|保密", text_salary):
                salary_text = "面议"
            elif text_salary and not re.fullmatch(r"0+[-~至]0+.*", text_salary):
                salary_text = text_salary
            else:
                salary_text = "面议"
        # 兜底：显式的 0~0 也当作未公开
        if re.fullmatch(r"\s*0+\s*~\s*0+\s*(元/月)?\s*", salary_text):
            salary_text = "面议"
        work_type = it.get("workType") or pb.get("workType") or ""
        is_intern = "实习" in work_type or (it.get("internshipMonths") or 0) > 0
        # 招聘类型：实习 / 校园招聘 / 社会招聘
        if is_intern:
            recruit_type = "实习"
        elif it.get("campusJobDetail") or "校" in work_type:
            recruit_type = "校园招聘"
        else:
            recruit_type = "社会招聘"
        # 职位性质：全职 / 兼职 / 实习
        if "兼职" in work_type:
            nature = "兼职"
        elif is_intern:
            nature = "实习"
        else:
            nature = "全职"
        # 专业要求：优先用结构化 needMajor，否则从职位描述中提取
        major_items = it.get("needMajor") or []
        major = ""
        if isinstance(major_items, list) and major_items:
            major = "、".join(
                item.get("name") if isinstance(item, dict) else str(item)
                for item in major_items if item)
        if not major:
            major = ZhiPin.extract_major(de.get("description") or it.get("jobSummary") or "")
        if not major:
            major = "不限"
        recruit = int(it.get("recruitNumber") or 0) or int(pb.get("recruitNumber") or 0)
        recruit_text = str(recruit) if recruit > 0 else "若干"
        cat = it.get("subJobTypeLevelName") or jt.get("subJobTypeLevelName") or "不限"
        card = it.get("cardCustomJson")
        addr = ""
        if isinstance(card, str):
            try:
                addr = json.loads(card).get("address") or ""
            except Exception:
                addr = ""
        row = {
            "城市": city_full,
            "职位名称": it.get("name") or pb.get("positionName") or "",
            "岗位编号": str(it.get("jobId") or it.get("positionId") or ""),
            "公司名称": it.get("companyName") or "",
            "公司性质": it.get("propertyName") or it.get("property") or "不限",
            "公司规模": it.get("companySize") or "不限",
            "公司行业": it.get("industryName") or "不限",
            "招聘类型": recruit_type,
            "职位性质": nature,
            "职位类别": cat,
            "薪资范围": salary_text,
            "招聘人数": recruit_text,
            "学历要求": edu,
            "经验要求": exp,
            "专业要求": major,
            "工作地点": work_place,
            "详细地址": addr,
            "报名截止": dt.get("dateEnd") or "长期有效",
            "职位描述": (de.get("description") or it.get("jobSummary") or "").strip(),
        }
        return {k: (ZhiPin.clean_html(v) if isinstance(v, str) else v)
                for k, v in row.items()}

    # ==================== 请求构造 ====================

    @staticmethod
    def build_body(city, page_index):
        return {"S_SOU_FULL_INDEX": "", "S_SOU_WORK_CITY": str(ZhiPin.CITY_ID[city]),
                "order": 4, "actionid": str(uuid.uuid4()), "pageSize": 20,
                "pageIndex": page_index, "at": "", "rt": "",
                "eventScenario": "pcSearchedSouSearch", "anonymous": 1,
                "clickFilterBlackCompany": False, "platform": 13, "version": "0.0.0"}

    @staticmethod
    def build_url():
        cid = uuid.uuid4()
        rid = cid.hex + "-%d-%d" % (int(time.time() * 1000), random.randint(1, 9999))
        return ("%s?platform=13&version=0.0.0&_v=0.%d&x-zp-page-request-id=%s"
                "&x-zp-client-id=%s" % (ZhiPin.API, random.randint(100000000, 900000000),
                                        rid, str(cid)))

    @classmethod
    async def _fetch_positions_async(cls, city, page_index):
        """在浏览器页面内用 fetch 请求接口（携带登录态 Cookie）。返回解析后的 JSON 或 None。"""
        js = ("async ([a,b]) => { const r = await fetch(a, {method:'POST',"
              "credentials:'include',headers:{'content-type':'application/json;charset=UTF-8',"
              "'accept':'application/json, text/plain, */*',"
              "'x-zp-business-system':'1','x-zp-page-code':'4089',"
              "'x-zp-platform':'13'},body: JSON.stringify(b)});"
              " return {s:r.status, t:await r.text()}; }")
        res = await cls._page.evaluate(js, [cls.build_url(), cls.build_body(city, page_index)])
        if res["s"] != 200:
            return None
        try:
            return json.loads(res["t"])
        except Exception:
            return None

    @classmethod
    def get_page_info(cls, page_id, province_name='四川', city_name='成都', city_code=None):
        """获取单个城市某一页的原始岗位列表；请求失败返回 None。"""
        if cls._should_stop():
            return None
        try:
            # 超时不宜过长：点「停止」后最多等这一下
            j = cls._submit(cls._fetch_positions_async(city_name, page_id), timeout=12)
            if j is None:
                return None
            return (j.get("data") or {}).get("list") or []
        except Exception as e:
            logger.error('【%s】第%d页请求异常：%s' % (city_name, page_id, e))
            return None

    # ==================== 解析 ====================

    @classmethod
    def parser_page_info(cls, province_name, city_name, page_info, crawl_date=None):
        """把单页岗位列表解析为 xlsx 行；返回 [[采集日期,来源,省份,城市,...], ...]。"""
        crawl_date = crawl_date or datetime.now().strftime('%Y-%m-%d')
        rows = []
        for it in (page_info or []):
            d = cls.item_to_row(it, province_name, city_name)
            rows.append([crawl_date, cls.web_name, province_name]
                        + [d.get(k, '') for k in cls.ROW_ORDER])
        return rows

    # ==================== 城市范围 ====================

    @classmethod
    def target_cities(cls, scope='all'):
        """选定要采集的城市

        scope:
          'all'        全部城市（四川 21 市 + 重庆）
          'sc'         仅四川
          'cq'         仅重庆
          '成都,绵阳'   按名称筛选（逗号分隔）
        数据来自 config/zhipin_cities.json 的 province 字段，不再写死。
        """
        all_pairs = list(cls.SC_CITIES)

        if scope in (None, '', 'all'):
            return all_pairs
        if scope == 'sc':
            return [x for x in all_pairs if x[0] == '四川']
        if scope == 'cq':
            return [x for x in all_pairs if x[0] == '重庆']

        # 逗号分隔的城市名
        prov_of = {city: prov for prov, city in all_pairs}
        picked = [x.strip() for x in str(scope).split(',') if x.strip()]
        return [(prov_of[n], n) for n in picked if n in prov_of]

    # ==================== 单城市采集 ====================

    @classmethod
    def get_single_city(cls, wb=None, ws=None, data_file=None, province_name='四川',
                        city_name='成都', yesterday_data=None, write=True,
                        pause_event=None, is_running=None, on_data=None, on_page=None):
        """采集单个城市，write=False 时仅返回数据不写入。返回本城市新增行。
        pause_event: threading.Event，暂停时 wait() 阻塞；is_running: 返回布尔，False 停止。
        on_data(row): 每采集到一条新数据立即回调，用于 GUI 实时刷新。
        on_page(page_id, page_added, city_total, elapsed): 每页结束回调（含耗时）。"""
        all_rows = []
        page_count = cls.DEFAULT_PAGE_SIZE
        pages = cls.DEFAULT_PAGES
        crawl_date = datetime.now().strftime('%Y-%m-%d')
        started = time.time()
        # 去重集合：整行(不含采集日期)作键；采集到一条就加入，避免本次分页重叠重复
        seen = cls.init_seen(yesterday_data)
        for page_id in range(1, pages + 1):
            # 暂停时阻塞；点停止立刻返回
            if not cls._wait():
                logger.info('【智联招聘】用户终止采集')
                break
            page_started = time.time()
            page_list = cls.get_page_info(page_id=page_id, province_name=province_name,
                                          city_name=city_name)
            if page_list is None:
                logger.info('【智联招聘】%s-%s 第%d页请求失败，%ds 后重试'
                            % (province_name, city_name, page_id, cls.RETRY_SLEEP))
                if not cls._sleep(cls.RETRY_SLEEP):
                    break
                page_list = cls.get_page_info(page_id=page_id, province_name=province_name,
                                              city_name=city_name)
                if page_list is None:
                    break
            if not page_list:
                break

            parsed = cls.parser_page_info(province_name, city_name, page_list,
                                          crawl_date=crawl_date)
            count = cls._append_rows(parsed, all_rows, seen, ws, write, on_data)
            # 写盘节流：避免每页都整本重写导致界面卡顿
            if write and count and wb is not None and data_file is not None:
                cls._save(wb, data_file)
            elapsed = time.time() - started
            logger.info('【智联招聘】%s-%s 第%d页 新增%d条，本城市累计%d条，'
                        '本页%.1fs，累计%.1fs'
                        % (province_name, city_name, page_id, count, len(all_rows),
                           time.time() - page_started, elapsed))
            if on_page is not None:
                on_page(page_id, count, len(all_rows), elapsed)
            if len(parsed) < page_count:
                break
            # 页间隔可被停止/暂停打断
            if not cls._sleep(cls.DEFAULT_DELAY):
                break
        return all_rows

    # ==================== 浏览器 / 事件循环（Playwright） ====================

    @classmethod
    def _ensure_loop(cls):
        """懒启动一个常驻的 asyncio 事件循环（运行于独立守护线程）。
        Playwright 是异步库，用后台循环让同步的类方法也能驱动异步协程。"""
        if cls._loop is not None and cls._loop.is_running():
            return cls._loop
        cls._loop = asyncio.new_event_loop()

        def _runner():
            asyncio.set_event_loop(cls._loop)
            cls._loop.run_forever()

        cls._thread = threading.Thread(target=_runner, daemon=True)
        cls._thread.start()
        return cls._loop

    @classmethod
    def _submit(cls, coro, timeout=180):
        """把协程提交到后台事件循环并同步等待结果（异步->同步桥梁）。"""
        cls._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, cls._loop)
        return fut.result(timeout=timeout)

    # ==================== 登录态（config.ini） ====================

    @classmethod
    def load_cookies(cls):
        """从 config.ini 读取智联 cookie 列表；没有或损坏时返回空列表。

        存储格式与 BOSS 的 boss_cookie 一致（Playwright context.cookies()
        的字符串形式，即 Python 列表字面量），便于人工查看和跨机迁移。
        """
        try:
            from Config import get_config_value
            raw = (get_config_value(cls.CONFIG_SECTION, cls.CONFIG_OPTION,
                                    file=cls.CONFIG_FILE) or '').strip()
        except Exception as e:
            logger.warning('【智联招聘】读取 config.ini 失败：%s' % e)
            return []
        if not raw:
            return []
        try:
            cookies = ast.literal_eval(raw)
        except (ValueError, SyntaxError) as e:
            logger.warning('【智联招聘】config.ini 里的 %s 无法解析：%s'
                           % (cls.CONFIG_OPTION, e))
            return []
        if not isinstance(cookies, list):
            return []
        return [c for c in cookies if isinstance(c, dict) and c.get('name')]

    @classmethod
    def save_cookies(cls, cookies):
        """把当前 context 的智联 cookie 写回 config.ini（同时存一份 api 串）。"""
        try:
            from Config import write_config_value
            zp = [c for c in (cookies or [])
                  if 'zhaopin' in (c.get('domain') or '')]
            if not zp:
                logger.warning('【智联招聘】登录后没有智联 cookie，未写入 config.ini')
                return False
            api = '; '.join('%s=%s' % (c.get('name'), c.get('value')) for c in zp)
            write_config_value(cls.CONFIG_SECTION,
                               {cls.CONFIG_OPTION: str(zp),
                                cls.CONFIG_OPTION + '_api': api},
                               file=cls.CONFIG_FILE)
            logger.info('【智联招聘】已保存 %d 条 cookie 到 config.ini' % len(zp))
            return True
        except Exception as e:
            logger.error('【智联招聘】写入 config.ini 失败：%s' % e)
            return False

    @classmethod
    def clear_saved_cookies(cls):
        """清空 config.ini 里保存的智联 cookie。"""
        try:
            from Config import write_config_value
            write_config_value(cls.CONFIG_SECTION,
                               {cls.CONFIG_OPTION: '',
                                cls.CONFIG_OPTION + '_api': ''},
                               file=cls.CONFIG_FILE)
            logger.info('【智联招聘】已清空 config.ini 中的智联 cookie')
        except Exception as e:
            logger.warning('【智联招聘】清空 config.ini 失败：%s' % e)

    # ==================== 浏览器 / 事件循环（Playwright） ====================

    @classmethod
    async def _launch_async(cls):
        if cls._page is not None:
            return cls._page
        cls._pw = await async_playwright().start()
        # 只传 launch 支持的参数；viewport/locale 属于 context 选项，不能放在这里
        launch_kwargs = dict(headless=False)
        # 优先使用系统浏览器（不随包内置，减小体积）：
        # 未指定 PLAYWRIGHT_CHANNEL 时依次尝试 系统 Edge -> 系统 Chrome -> 内置 Chromium。
        forced = (os.environ.get('PLAYWRIGHT_CHANNEL') or '').strip()
        channels = [forced] if forced else ['msedge', 'chrome', None]
        last_err = None
        for channel in channels:
            kwargs = dict(launch_kwargs)
            if channel:
                kwargs['channel'] = channel
            logger.info('【智联招聘】启动浏览器（channel=%s）' % (channel or 'bundled-chromium'))
            browser = None
            try:
                browser = await cls._pw.chromium.launch(**kwargs)
                # 与其他平台一致：普通上下文 + config.ini 里的 cookie
                context = await browser.new_context(
                    locale="zh-CN",
                    viewport={"width": 1360, "height": 900},
                )
                cookies = cls.load_cookies()
                if cookies:
                    try:
                        await context.add_cookies(cookies)
                        logger.info('【智联招聘】已从 config.ini 注入 %d 条 cookie' % len(cookies))
                    except Exception as e:
                        logger.warning('【智联招聘】注入 cookie 失败（将走登录流程）：%r' % e)
                else:
                    logger.info('【智联招聘】config.ini 无智联 cookie，将走登录流程')
                cls._browser = browser
                cls._context = context
                cls._page = await context.new_page()
                return cls._page
            except Exception as e:
                last_err = e
                logger.warning('【智联招聘】channel=%s 启动失败：%r' % (channel or 'bundled', e))
                cls._browser = cls._context = None
                # launch 成功但 new_context 失败时，浏览器进程会残留，这里关掉
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        # 所有方式都失败：停掉 playwright，避免下次 launch 重复 start 造成泄漏
        try:
            await cls._pw.stop()
        except Exception:
            pass
        cls._pw = None
        raise last_err if last_err else RuntimeError('未找到可用浏览器（Edge/Chrome/Chromium）')

    @classmethod
    def launch(cls):
        logger.info('【智联招聘】启动浏览器（登录态：%s）' % cls.CONFIG_FILE)
        return cls._submit(cls._launch_async(), timeout=120)

    @classmethod
    async def _close_async(cls):
        try:
            if cls._context is not None:
                await cls._context.close()
        except Exception as e:
            logger.warning('【智联招聘】关闭浏览器上下文异常：%r' % (e,))
        try:
            if cls._browser is not None:
                await cls._browser.close()
        except Exception as e:
            logger.warning('【智联招聘】关闭浏览器异常：%r' % (e,))
        if cls._pw is not None:
            try:
                await cls._pw.stop()
            except Exception as e:
                logger.warning('【智联招聘】停止 Playwright 异常：%r' % (e,))
        cls._page = cls._context = cls._browser = cls._pw = None

    @classmethod
    def close(cls):
        if cls._loop is not None:
            try:
                cls._submit(cls._close_async(), timeout=30)
            except Exception as e:
                logger.warning('【智联招聘】关闭浏览器异常：%s' % e)

    # ==================== 登录（手机号 + 短信验证码） ====================

    @classmethod
    async def _goto_jobs_page(cls):
        await cls._page.goto("https://www.zhaopin.com/jobs?jl=551", timeout=60000)
        await cls._wait_eo_pass(timeout=60)
        await cls._page.wait_for_timeout(4000)

    @classmethod
    def goto_jobs_page(cls):
        cls._submit(cls._goto_jobs_page(), timeout=120)

    @classmethod
    async def _wait_eo_pass(cls, timeout=180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if "Security Verification" not in await cls._page.title():
                    return True
            except Exception:
                pass
            await cls._page.wait_for_timeout(1500)
        return False

    @classmethod
    async def _check_agreement(cls):
        sel = 'input[type="checkbox"], [role="checkbox"]'
        try:
            n = await cls._page.locator(sel).count()
        except Exception:
            n = 0
        if n == 0:
            logger.info('[登录] 协议控件未渲染（已接受或无需勾选），跳过勾选。')
            return True
        cb = cls._page.locator(sel).first
        try:
            if await cb.is_checked():
                logger.info('[登录] 协议已处于勾选状态。')
                return True
        except Exception:
            pass
        try:
            await cb.click(force=True, timeout=5000)
            await cls._page.wait_for_timeout(300)
            logger.info('[登录] 已勾选用户协议/隐私政策。')
            return True
        except Exception as e:
            logger.info('[登录] 勾选协议失败（%r）。' % (e,))
            return False

    @classmethod
    async def _ensure_agreement(cls, timeout=20):
        t0 = time.time()
        tries = 0
        while time.time() - t0 < timeout and tries < 2:
            tries += 1
            if await cls._check_agreement():
                logger.info('[登录] 协议确认勾选。')
                return True
            try:
                await cls._page.wait_for_timeout(400)
            except Exception:
                break
        logger.info('[登录] 警告：未能确认协议勾选，继续尝试登录（如失败请手动勾选）。')
        return False

    @classmethod
    async def _is_logged_in(cls):
        try:
            if await cls._page.locator('input[placeholder="手机号"]').count():
                return False
        except Exception:
            pass
        url = cls._page.url
        if "passport.zhaopin.com" not in url:
            return None
        if "passport.zhaopin.com/login" in url:
            return None
        return True

    @classmethod
    async def _clear_zp_login(cls):
        ctx = cls._page.context
        try:
            cookies = await ctx.cookies()
            zp = [c for c in cookies if "zhaopin" in (c.get("domain") or "")]
            if zp:
                await ctx.clear_cookies(domain=re.compile(r".*zhaopin.*"))
                logger.info('[登录] 已清除 %d 条智联登录 cookie（强制重新登录）' % len(zp))
        except Exception as e:
            logger.info('[登录] 清除 cookie 失败（可忽略）: %r' % (e,))
        # config.ini 里存的也一并清掉，避免下次启动又被注入回去
        cls.clear_saved_cookies()

    @classmethod
    async def _click_code_button(cls):
        for sel in ('button:has-text("获取验证码")', 'button:has-text("获取 验证码")',
                    'button:has-text("验证码")', 'a:has-text("获取验证码")'):
            try:
                loc = cls._page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=8000)
                    return True
            except Exception:
                continue
        return False

    @classmethod
    async def _click_submit_button(cls):
        for sel in ('button:has-text("登录/注册")', 'button:has-text("立即登录")',
                    'button:has-text("登 录")', 'button:has-text("登录")'):
            try:
                loc = cls._page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=8000)
                    return True
            except Exception:
                continue
        return False

    @classmethod
    async def _do_login(cls, phone, ask=input):
        logger.info('[登录] 打开 sou.zhaopin.com 过安全验证(如有勾选请在弹出窗口手动完成)…')
        await cls._page.goto("https://sou.zhaopin.com/", timeout=60000)
        ok = await cls._wait_eo_pass()
        if not ok:
            logger.info('[登录] 请在弹出的窗口手动完成安全验证（滑块/勾选）……')
            await cls._wait_eo_pass(120)
        logger.info('[登录] 正在打开智联登录页……')
        await cls._page.goto("https://passport.zhaopin.com/login", timeout=60000)
        await cls._page.wait_for_timeout(2000)
        try:
            if await cls._page.locator('input[placeholder="手机号"]').count() == 0:
                logger.info('[登录] 检测到已有登录态，跳过短信验证。')
                return True
        except Exception:
            pass
        await cls._page.wait_for_selector('input[placeholder="手机号"]', timeout=60000)
        if not phone:
            phone = ask("请输入智联绑定手机号: ").strip()
        await cls._page.fill('input[placeholder="手机号"]', phone)
        await cls._ensure_agreement()
        if not await cls._click_code_button():
            logger.info('[登录] 未能定位“获取验证码”按钮，请在浏览器中手动获取验证码。')
        logger.info('[登录] 已请求短信验证码，请查看手机短信（若弹出滑块请在窗口完成）。')
        sent = False
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                bt = await cls._page.eval_on_selector_all(
                    "button", "els => els.map(e => (e.innerText||'').trim())")
                if any(("重新获取" in b) or ("后重发" in b) or ("s后" in b) for b in bt):
                    sent = True
                    break
            except Exception:
                pass
            try:
                if await cls._page.locator('input[placeholder*="验证码"]').count():
                    sent = True
                    break
            except Exception:
                pass
            await cls._page.wait_for_timeout(1000)
        logger.info('[登录] 短信状态: ' + ("已发送" if sent else "未确认(若弹滑块请先在窗口完成)"))
        code = ask("请输入短信验证码: ").strip()
        sms_sel = 'input[placeholder="短信验证码"]'
        try:
            if not await cls._page.locator(sms_sel).count():
                alt = cls._page.locator('input[placeholder*="验证码"]').first
                if await alt.count():
                    sms_sel = 'input[placeholder*="验证码"]'
        except Exception:
            pass
        try:
            await cls._page.fill(sms_sel, code)
        except Exception:
            pass
        await cls._ensure_agreement()
        if not await cls._click_submit_button():
            logger.info('[登录] 未能定位“登录/注册”按钮，请在浏览器中手动点击登录。')
        logger.info('[登录] 已提交，等待登录成功…')
        confirmed = False
        t0 = time.time()
        while time.time() - t0 < 30:
            await cls._page.wait_for_timeout(1000)
            try:
                if await cls._page.locator('input[placeholder="手机号"]').count() == 0:
                    confirmed = True
                    break
            except Exception:
                pass
            if "passport.zhaopin.com/login" not in cls._page.url:
                confirmed = True
                break
        if confirmed:
            logger.info('[登录] 登录成功，当前页: ' + str(cls._page.url))
            # 关键：把登录后的 cookie 写入 config.ini，下次启动直接注入，
            # 不再依赖 zp_profile 目录
            try:
                await cls._save_cookies_async()
            except Exception as e:
                logger.warning('[登录] 保存 cookie 到 config.ini 失败：%r' % (e,))
        else:
            logger.info('[登录] 警告：未能确认登录成功。请检查浏览器窗口，可能需要重新获取验证码。')
        await cls._page.wait_for_timeout(3000)
        return confirmed

    @classmethod
    async def _save_cookies_async(cls):
        """异步取当前 context 的 cookie 并写盘（供登录流程调用）。"""
        cookies = await cls._context.cookies()
        return cls.save_cookies(cookies)

    @classmethod
    async def _ensure_login(cls, phone, force=False, ask=input):
        if force:
            logger.info('[登录] force=True，清除智联登录态并强制重新登录……')
            await cls._clear_zp_login()
        logger.info('[登录] 正在打开智联登录页……')
        await cls._page.goto("https://passport.zhaopin.com/login", timeout=60000)
        ok = await cls._wait_eo_pass(60)
        if not ok:
            logger.info('[登录] 若出现安全验证/滑块，请在浏览器窗口手动完成……')
            await cls._wait_eo_pass(120)
        await cls._page.wait_for_timeout(3000)
        state = await cls._is_logged_in()
        if state is True and not force:
            logger.info('[登录] 检测到已有登录态，跳过手机号与短信验证，直接开始采集。')
            # 顺手刷新 config.ini 里的 cookie（延长有效期）
            try:
                await cls._save_cookies_async()
            except Exception as e:
                logger.warning('[登录] 刷新 config.ini cookie 失败：%r' % (e,))
            return True
        if state is None:
            logger.info('[登录] 登录态无法判定，默认进入手机号 + 短信验证码登录流程。')
        logger.info('[登录] 未登录，进入【手机号 + 短信验证码】登录流程。')
        try:
            confirmed = await cls._do_login(phone, ask=ask)
        except Exception as e:
            logger.info('[登录] 登录流程异常：%r' % (e,))
            return False
        if not confirmed:
            logger.info('[登录] 登录未确认成功，已停止，不会开始采集。请检查浏览器窗口后重新运行。')
            return False
        logger.info('[登录] 登录确认成功，开始采集。')
        return True

    @classmethod
    def login(cls, phone='', force=False, ask=input):
        return cls._submit(cls._ensure_login(phone, force, ask=ask), timeout=300)

    # ==================== 主流程 ====================

    @classmethod
    def _log_field_summary(cls, ws, total_rows):
        """采集结束后统计关键字段覆盖率，便于确认「学历要求」等是否写入。

        列索引按 XLSX_HEADERS 动态查找，避免新增列后此处错位。
        """
        try:
            idx_edu = XLSX_HEADERS.index('学历要求')
            idx_exp = XLSX_HEADERS.index('经验要求')
            idx_salary = XLSX_HEADERS.index('薪资范围')
            empty_edu = empty_exp = empty_salary = 0
            count = 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or len(row) < len(XLSX_HEADERS):
                    continue
                count += 1
                if not str(row[idx_edu] or '').strip():
                    empty_edu += 1
                if not str(row[idx_exp] or '').strip():
                    empty_exp += 1
                if not str(row[idx_salary] or '').strip():
                    empty_salary += 1
            if not count:
                return
            logger.info('【智联招聘】本次新增 %d 条；xlsx 共 %d 条，学历要求为空 %d 条，'
                        '经验要求为空 %d 条，薪资为空 %d 条'
                        % (total_rows, count, empty_edu, empty_exp, empty_salary))
        except Exception as e:
            logger.warning('【智联招聘】字段统计失败：%s' % e)

    @classmethod
    def run(cls, data_file='智联数据.xlsx', phone='', force=False, scope='all',
            update_duplicate=None,
            delay=None, max_pages=None, ask=input,
            pause_event=None, is_running=None,
            on_progress=None, on_data=None, on_city_done=None, on_page=None,
            on_complete=None, on_error=None):
        """采集入口：登录 -> 逐城市采集 -> 增量写入 xlsx。
        pause_event: threading.Event（暂停时阻塞）；is_running: lambda 返回布尔，False 停止。
        on_progress(current, total, city) / on_data(row) / on_city_done(city)
        on_complete(msg) / on_error(msg)；供 GUI 展示进度与数据。

        登录态存 config/config.ini（[login] zhipin_cookie），与 BOSS/国聘一致，
        不再使用浏览器 profile 目录。"""
        if delay is not None:
            cls.DEFAULT_DELAY = delay
        if max_pages is not None:
            cls.DEFAULT_PAGES = max_pages

        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)
        cls._begin_run(pause_event, is_running,
                            update_duplicate=update_duplicate)

        try:
            cls.launch()
            # 启动浏览器可能耗时若干秒，期间用户点了停止就别继续登录
            if cls._should_stop():
                logger.info('【智联招聘】用户终止采集')
                if on_complete:
                    on_complete('用户终止采集')
                return
            if not cls.login(phone=phone, force=force, ask=ask):
                logger.error('【智联招聘】登录未确认成功，停止采集。')
                if on_complete:
                    on_complete('登录未确认成功，已停止')
                return
            if cls._should_stop():
                logger.info('【智联招聘】用户终止采集')
                if on_complete:
                    on_complete('用户终止采集')
                return
            cls.goto_jobs_page()

            cities = cls.target_cities(scope)
            if not cities:
                logger.error('【智联招聘】未获取到有效城市列表，停止采集。')
                if on_complete:
                    on_complete('未获取到有效城市列表')
                return
            logger.info('【智联招聘】待抓 %d 市：%s，页间隔 %.1fs'
                        % (len(cities), ", ".join(c for _p, c in cities), cls.DEFAULT_DELAY))

            stopped = False
            total_rows = 0
            failed = []
            for prov, city in cities:
                # 暂停时阻塞；点停止立刻返回
                if not cls._wait():
                    logger.info('【智联招聘】用户终止采集')
                    stopped = True
                    break
                logger.info('开始采集【智联招聘%s-%s】' % (prov, city))
                try:
                    rows = cls.get_single_city(wb, ws, data_file, prov, city,
                                               yesterday_data, write=True,
                                               pause_event=pause_event,
                                               is_running=is_running,
                                               on_data=on_data, on_page=on_page)
                    total_rows += len(rows)
                    if on_progress:
                        on_progress(prov, city, len(rows))
                    if on_city_done:
                        on_city_done(city)
                except Exception as e:
                    failed.append('%s-%s' % (prov, city))
                    logger.error('【智联招聘】%s-%s 采集异常：%s' % (prov, city, e))
                    if on_error:
                        on_error('%s-%s: %s' % (prov, city, e))
                if cls._should_stop():
                    logger.info('【智联招聘】用户终止采集')
                    stopped = True
                    break
                if not cls._sleep(cls.DEFAULT_DELAY):
                    stopped = True
                    break
            cls._log_field_summary(ws, total_rows)
        finally:
            # 先落盘、再关闭浏览器，最后通知界面（避免界面已恢复“开始”时仍在写盘）
            try:
                cls._save(wb, data_file, force=True)
            except Exception as e:
                logger.error('【智联招聘】保存失败：%s' % e)
            cls.close()

        if failed:
            logger.info('【智联招聘】失败城市 %d 个：%s' % (len(failed), "、".join(failed[:10])))
        if on_complete:
            on_complete(cls._finish_message(total_rows, stopped, len(failed)))
