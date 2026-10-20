# coding='utf-8'
"""国家大学生就业服务平台（ncss.cn）岗位采集：接口取列表 + 解析详情页，写入 xlsx。

与 GuoPin 保持一致的调用方式（get_page_info / parser_page_info / get_single_page / run）。

Cookie 唯一来源：config.ini 的 login.nscc_cookie_api
（由 newPlayWright.PlayWright.login 登录后写入，也可手工填写）；失效时自动拉起浏览器登录。
"""
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from getJobs import BaseSpider, _BASE_DIR
from Logger import logger


# ==================== 国家大学生就业服务平台采集 ====================
class CookieExpired(RuntimeError):
    """Cookie 失效：列表接口返回空 data，或详情页被重定向到登录页。"""


class StopRequested(RuntimeError):
    """用户点击停止：用于在请求/重试中快速退出。"""


class Ncss(BaseSpider):
    """国家大学生就业服务平台（ncss.cn）采集类：接口取列表 + 详情页解析，同步写入 xlsx。

    与 GuoPin 保持一致的调用方式（get_page_info / parser_page_info / get_single_page / run），
    便于 GUI 与命令行共用同一套逻辑。

    Cookie 唯一来源：config.ini 的 login.nscc_cookie_api
    （由 PlayWright.login 登录后写入，也可手工填写）；失效时自动拉起浏览器登录。
    """
    # 网站名称（写入「来源」列，同时用于界面标题）
    web_name = '国家大学生就业服务平台'

    # ==================== 数据来源平台 ====================
    # 国家大学生就业服务平台聚合了多个第三方平台的岗位，
    # sourcesType / sourcesName 用于指定要采集的来源（取值来自站点筛选条件）。
    SOURCES = {
        "国家大学生就业服务平台": {"sourcesType": "", "sourcesName": "0"},
        "省市及高校": {"sourcesType": "1", "sourcesName": ""},
        "boss直聘": {"sourcesType": "0", "sourcesName": "2000846399"},
        "中华英才网": {"sourcesType": "0", "sourcesName": "sx4tfd53g3drg3lhcabun0cjmylq8jan"},
        "猎聘": {"sourcesType": "0", "sourcesName": "2000846397"},
        "全联人才在线": {"sourcesType": "0", "sourcesName": "wppuiz6fu2k6pi030gvd45l8wky8l1ex"},
        "前程无忧": {"sourcesType": "0", "sourcesName": "19etdf5giehhg58vzrf5m0en8hldvkvw"},
        "智联招聘": {"sourcesType": "0", "sourcesName": "fawzqa3wo3hy2x4uqe1b1bwy4met2wpb"},
        "实习僧": {"sourcesType": "0", "sourcesName": "2xy7zytm7pt75iz09glwxs5554t621uf"},
        "国聘": {"sourcesType": "0", "sourcesName": "gn5yn9s9wjydmrlh5kre1rzkma8mmjbu"},
        "一览英才": {"sourcesType": "0", "sourcesName": "bbqeda1p0l0fkoinaywn8yra176xrz2l"},
        "中小企业信息网": {"sourcesType": "0", "sourcesName": "2000846398"},
        "中智招聘": {"sourcesType": "0", "sourcesName": "xrtjvzrkqlm0n2wo0nrh74dyo2kij9sm"},
        "北森": {"sourcesType": "0", "sourcesName": "1zl8wkl8ixb1e1c1095fmdtrzwzegltk"},
        "丁香人才": {"sourcesType": "0", "sourcesName": "rjrwyk6f2n6snh2c6fdz7dwfd6852gmb"},
        "易展翅": {"sourcesType": "0", "sourcesName": "1fgc34ei0xf5ure5ce82cxtwz4ovq6gf"},
        "北极星": {"sourcesType": "0", "sourcesName": "mfd56jlomqoq2efagv04o9i6cn0krhvl"},
    }
    # 默认采集的平台；如需只爬部分平台，改成 ["猎聘", "国聘"] 之类的列表即可
    CRAWL_SOURCES = list(SOURCES)

    LIST_API = 'https://www.ncss.cn/student/jobs/jobslist/ajax/'
    LIST_PAGE = 'https://www.ncss.cn/student/jobs/index.html'
    DETAIL_URL = 'https://www.ncss.cn/student/jobs/{job_id}/detail.html'

    # 分页 / 频率 / 重试
    DEFAULT_PAGE_SIZE = 10        # 与接口 limit 一致
    DEFAULT_PAGES = 60            # 服务端 count 上限 500 条（每页 10 条）
    DEFAULT_DELAY = 1.0           # 每次请求间隔（秒）
    RETRY_TIMES = 3               # 单次请求最大尝试次数
    RETRY_BACKOFF = 2.0           # 重试退避基数（秒）
    MAX_PAGE_FAILS = 3            # 连续多少页列表失败后停止
    REQUEST_TIMEOUT = 15          # 单次请求超时（秒）
    SAVE_INTERVAL = 10            # 两次写盘的最小间隔（秒），避免每页都重写整本 xlsx

    # 登录
    CONFIG_SECTION = 'login'
    CONFIG_OPTION = 'nscc_cookie'                 # Cookie 实际取 login.nscc_cookie_api
    CONFIG_FILE = os.path.join(_BASE_DIR, 'config.ini')
    AUTO_LOGIN = True                             # Cookie 失效时是否自动弹出浏览器登录
    LOGIN_URL = ('https://account.chsi.com.cn/passport/login'
                 '?service=https://www.ncss.cn/student/connect/chsi&entrytype=stu')
    LOGIN_ELEMENT = '//span[@class="user-name" and @id="stuName"]'

    USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36')

    _session = None
    _total_pages = 0
    # 当前任务状态（供请求重试/逐条抓取详情时判断是否该中止）
    _pause_event = None
    # 运行状态探针：存的是可调用对象（如 lambda: panel.is_running），不是布尔值
    _running_probe = None
    _save_ts = 0.0

    # ==================== Cookie ====================

    @classmethod
    def load_cookie(cls):
        """读取 config.ini 的 login.nscc_cookie_api（PlayWright.login 写入的 api cookie 串）。"""
        try:
            from Config import get_config_value
        except Exception as e:
            logger.error(f'{cls.web_name} 无法加载配置模块：{e}')
            return ''
        try:
            return (get_config_value(cls.CONFIG_SECTION, f'{cls.CONFIG_OPTION}_api',
                                     file=cls.CONFIG_FILE) or '').strip()
        except Exception as e:
            logger.error(f'{cls.web_name} 读取 {os.path.basename(cls.CONFIG_FILE)} 失败：{e}')
            return ''

    @classmethod
    def close_browser(cls):
        """关闭登录用浏览器，并重置单例状态，便于下次重新启动。"""
        try:
            from newPlayWright import PlayWright
        except Exception:
            return
        try:
            PlayWright.close()
        except Exception as e:
            logger.info(f'{cls.web_name} 关闭浏览器失败：{e}')
        finally:
            for attr in ('playwright', 'browser', 'context', 'page'):
                setattr(PlayWright, attr, None)

    @classmethod
    def login(cls):
        """打开浏览器登录学信网；成功后 PlayWright.login 把 Cookie 写入 config.ini。"""
        try:
            from newPlayWright import PlayWright
        except Exception as e:
            logger.error(f'{cls.web_name} 无法加载 PlayWright（请安装 playwright/screeninfo）：{e}')
            return False

        logger.info(f'{cls.web_name} 正在打开浏览器，请完成学信网登录（最长等待 3 分钟）…')
        try:
            ok = PlayWright.login(
                cls.LOGIN_URL,
                cls.LOGIN_ELEMENT,
                f'{cls.CONFIG_SECTION}.{cls.CONFIG_OPTION}',
                file=cls.CONFIG_FILE,
            )
        except Exception as e:
            logger.error(f'{cls.web_name} 登录过程异常：{e}')
            ok = False
        finally:
            cls.close_browser()

        if not ok:
            logger.error(f'{cls.web_name} 未检测到登录成功状态')
            return False
        if not cls.load_cookie():
            logger.error(f'{cls.web_name} 登录成功但 {os.path.basename(cls.CONFIG_FILE)} '
                         f'中没有 login.{cls.CONFIG_OPTION}_api，请检查写入权限')
            return False
        logger.info(f'{cls.web_name} 登录成功，Cookie 已写入 config.ini')
        return True

    @classmethod
    def ensure_cookie(cls, auto_login=None):
        """确保存在可用 Cookie；失效时（可选）自动登录一次。"""
        if auto_login is None:
            auto_login = cls.AUTO_LOGIN
        cookie = cls.load_cookie()
        if cls.verify_cookie(cookie):
            return cookie

        hint = f'请在 {os.path.basename(cls.CONFIG_FILE)} 的 [login] 中配置 {cls.CONFIG_OPTION}_api'
        logger.info(f'{cls.web_name} 当前 Cookie 不可用（缺失或已过期）')
        if not auto_login:
            raise CookieExpired(f'Cookie 失效，{hint}')
        if not cls.login():
            raise CookieExpired(f'自动登录失败，{hint}')

        cookie = cls.load_cookie()
        if not cls.verify_cookie(cookie):
            raise CookieExpired('登录后 Cookie 仍不可用，请检查账号是否有查看岗位的权限')
        return cookie

    # ==================== 会话与请求 ====================

    @classmethod
    def session(cls):
        if cls._session is None:
            s = requests.Session()
            s.headers.update({
                'user-agent': cls.USER_AGENT,
                'accept-language': 'zh-CN,zh;q=0.9',
            })
            try:
                s.get(cls.LIST_PAGE, timeout=20)
            except requests.RequestException as e:
                # 预热失败不致命：接口请求仍会带 Cookie 重试
                logger.info(f'{cls.web_name} 访问列表页失败：{e}')
            cookie = cls.load_cookie()
            if cookie:
                s.headers['cookie'] = cookie
            else:
                logger.info(f'{cls.web_name} 未配置 Cookie，列表可能在第 5 页后中断')
            s.headers.update({
                'x-requested-with': 'XMLHttpRequest',
                'referer': cls.LIST_PAGE,
                'accept': 'application/json, text/javascript, */*; q=0.01',
            })
            cls._session = s
        return cls._session

    @classmethod
    def reset_session(cls):
        """换 Cookie / 登录后必须重建会话。"""
        if cls._session is not None:
            try:
                cls._session.close()
            except Exception:
                pass
        cls._session = None

    @classmethod
    def verify_cookie(cls, cookie, timeout=15):
        """用一个轻量请求校验 Cookie 是否可用。"""
        if not cookie:
            return False
        headers = {
            'user-agent': cls.USER_AGENT,
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'x-requested-with': 'XMLHttpRequest',
            'referer': cls.LIST_PAGE,
            'cookie': cookie,
        }
        params = {'offset': 1, 'limit': 1, '_': int(time.time() * 1000)}
        try:
            resp = requests.get(cls.LIST_API, params=params, headers=headers, timeout=timeout)
            payload = resp.json()
        except (requests.RequestException, ValueError):
            return False
        return bool((payload.get('data') or {}).get('list'))

    @classmethod
    def _get(cls, url, params=None):
        """带超时与退避重试的 GET；最终失败抛出最后一次异常。"""
        last_error = None
        for attempt in range(1, cls.RETRY_TIMES + 1):
            if cls._should_stop():
                raise StopRequested('用户终止采集')
            try:
                resp = cls.session().get(url, params=params, timeout=cls.REQUEST_TIMEOUT)
                if resp.status_code in (403, 429, 500, 502, 503, 504):
                    raise requests.HTTPError(f'HTTP {resp.status_code}')
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_error = e
                if attempt < cls.RETRY_TIMES:
                    wait = cls.RETRY_BACKOFF * attempt
                    logger.info(f'{cls.web_name} 请求失败，{wait:.1f}s 后重试（{attempt}/{cls.RETRY_TIMES}）：{e}')
                    # 重试等待同样可被停止/暂停打断
                    if not cls._sleep(wait):
                        raise StopRequested('用户终止采集')
        raise last_error

    @classmethod
    def relogin(cls, auto_login=None):
        """Cookie 失效时重新登录；成功则重建会话。"""
        if auto_login is None:
            auto_login = cls.AUTO_LOGIN
        if not auto_login or not cls.login():
            return False
        cls.reset_session()
        return True

    # ==================== 页面数据 ====================

    @classmethod
    def resolve_source(cls, source=None):
        """把平台名 / (sourcesType, sourcesName) / dict 统一解析成 (名称, sourcesType, sourcesName)。

        source 为空时使用 SOURCES 的第一个平台（国家大学生就业服务平台）。
        """
        if source is None:
            source = cls.CRAWL_SOURCES[0] if cls.CRAWL_SOURCES else '国家大学生就业服务平台'
        if isinstance(source, str):
            config = cls.SOURCES.get(source)
            if config is None:
                # 允许直接传 sourcesName
                return source, '0', source
            return source, config.get('sourcesType', ''), config.get('sourcesName', '')
        name = (source.get('name') or source.get('sourcesName') or '').strip()
        return name, source.get('sourcesType', ''), source.get('sourcesName', '')

    @classmethod
    def get_page_info(cls, page_id=1, page_size=None, source=None):
        """获取某页岗位列表；失败返回 False（与 GuoPin 保持一致）。"""
        size = page_size or cls.DEFAULT_PAGE_SIZE
        name, sources_type, sources_name = cls.resolve_source(source)
        params = {
            'jobType': '', 'areaCode': '', 'jobName': '', 'monthPay': '',
            'industrySectors': '', 'property': '', 'categoryCode': '',
            'memberLevel': '', 'recruitType': '', 'offset': page_id, 'limit': size,
            'keyUnits': '', 'degreeCode': '',
            'sourcesName': sources_name, 'sourcesType': sources_type,
            '_': int(time.time() * 1000),
        }
        try:
            resp = cls._get(cls.LIST_API, params=params)
        except requests.RequestException as e:
            logger.error(f'【{cls.web_name}】第 {page_id} 页请求失败：{e}')
            return False
        try:
            payload = resp.json()
        except ValueError:
            logger.error(f'【{cls.web_name}】第 {page_id} 页返回非 JSON（可能被风控）')
            return False

        data = payload.get('data')
        if not data:
            logger.error(f'【{cls.web_name}】{name} 第 {page_id} 页返回空数据，'
                         f'Cookie 可能已失效（{os.path.basename(cls.CONFIG_FILE)} 的 '
                         f'login.{cls.CONFIG_OPTION}_api）')
            return False
        items = data.get('list') or []
        count = int((data.get('pagenation') or {}).get('count') or 0)
        cls._total_pages = (count + size - 1) // size if count else 0
        return items

    @classmethod
    def fetch_page(cls, page_id, source=None, auto_login=None):
        """取列表页；失败时重登一次再试。返回 list 或 False（失败 / 空数据）。"""
        page_info = cls.get_page_info(page_id=page_id, source=source)
        if isinstance(page_info, bool) and cls.relogin(auto_login):
            page_info = cls.get_page_info(page_id=page_id, source=source)
        return page_info

    @classmethod
    def get_job_detail(cls, job_id):
        """获取并解析岗位详情；失败返回 False（跳登录页视为 Cookie 失效）。"""
        try:
            resp = cls._get(cls.DETAIL_URL.format(job_id=job_id))
        except requests.RequestException as e:
            logger.error(f'【{cls.web_name}】详情请求失败（{job_id}）：{e}')
            return False
        if 'passport.chsi.com.cn' in resp.url or 'account.chsi.com.cn' in resp.url:
            logger.error(f'【{cls.web_name}】详情页被重定向到登录页，Cookie 已失效')
            return False
        try:
            return cls.parser_detail(resp.text)
        except Exception as e:
            logger.error(f'【{cls.web_name}】详情解析失败（{job_id}）：{e}')
            return False

    @staticmethod
    def clean_text(value):
        return re.sub(r'\s+', ' ', str(value or '')).strip()

    @classmethod
    def parser_detail(cls, html):
        """解析详情页，返回字段字典。"""
        soup = BeautifulSoup(html, 'html.parser')

        def text_of(selector, default=''):
            node = soup.select_one(selector)
            return cls.clean_text(node.get_text(' ', strip=True)) if node else default

        title_node = soup.select_one('#jobName')
        job_name = ''
        if title_node:
            job_name = cls.clean_text(title_node.get('title') or title_node.get_text(' ', strip=True))

        # 薪资 / 学历 / 招聘人数 / 更新时间 依次排列在 ul.salary 中
        salary_spans = []
        salary_ul = soup.select_one('ul.salary')
        if salary_ul:
            salary_spans = [cls.clean_text(li.get_text(' ', strip=True))
                            for li in salary_ul.find_all('li')]

        # 公司信息块按标签取值（公司性质 / 公司规模 / 所在地址）
        company = {}
        for li in soup.select('.con-right .company li'):
            label = cls.clean_text(li.get_text(' ', strip=True))
            value_node = li.select_one('span.show.fr')
            if not value_node:
                continue
            value = cls.clean_text(value_node.get_text(' ', strip=True))
            if label.startswith('公司性质'):
                company['property'] = value
            elif label.startswith('公司规模'):
                company['scale'] = value
            elif label.startswith('所在地址'):
                company['address'] = value

        detail_node = soup.select_one('.jobdetail-box .mainContent') or soup.select_one('.mainContent')
        detail = detail_node.get_text('\n', strip=True) if detail_node else ''
        detail = re.sub(r'\n{3,}', '\n\n', detail).strip()

        return {
            'job_name': job_name,
            'salary_text': salary_spans[0] if salary_spans else '',
            'degree_text': salary_spans[1] if len(salary_spans) > 1 else '',
            'major': text_of('.major'),
            'location': text_of('.site-tag'),
            'company_name': text_of('#realCorpName'),
            'company_property': company.get('property', ''),
            'company_scale': company.get('scale', ''),
            'company_industry': text_of('#mainindustries'),
            'company_address': text_of('#companyNameMap') or company.get('address', ''),
            'job_detail': detail,
        }

    # ==================== 字段规整 ====================

    MUNICIPALITIES = {'北京', '上海', '天津', '重庆'}
    PROVINCE_SUFFIXES = ('省', '自治区', '特别行政区')
    CITY_SUFFIXES = ('市', '自治州', '地区', '盟')
    PROPERTY_MAP = {
        '国有企业': '国企',
        '民营企业': '民企',
        '私营企业': '民企',
        '三资企业': '外企',
        '外商投资企业': '外企',
        '机关': '政府机关',
        '事业单位': '事业单位',
    }

    @classmethod
    def split_area(cls, location, fallback_city=''):
        """把「北京市海淀区」「四川省成都市锦江区」拆成 (省, 市, 区县)。"""
        text = cls.clean_text(location)
        if not text:
            city = fallback_city
            return (city[:-1] if city.endswith('市') else city), city, ''

        # 直辖市：北京市海淀区 -> (北京, 北京市, 海淀区)
        if text[:2] in cls.MUNICIPALITIES:
            province = text[:2]
            rest = text[2:]
            if rest.startswith('市'):
                rest = rest[1:]
            return province, province + '市', rest

        province, rest = '', text
        for suffix in cls.PROVINCE_SUFFIXES:
            idx = text.find(suffix)
            if idx > 0:
                province = text[:idx]
                rest = text[idx + len(suffix):]
                break

        # 自治区简称：广西壮族 -> 广西、新疆维吾尔 -> 新疆、宁夏回族 -> 宁夏
        for ethnic in ('壮族', '回族', '维吾尔'):
            if province.endswith(ethnic):
                province = province[:-len(ethnic)]

        city = ''
        for suffix in cls.CITY_SUFFIXES:
            idx = rest.find(suffix)
            if idx > 0:
                city = rest[:idx + len(suffix)]
                rest = rest[idx + len(suffix):]
                break

        district = rest
        if not city:
            city = fallback_city or text
        if not province:
            province = city[:-1] if city.endswith('市') else city
        return province, city, district

    @classmethod
    def parse_salary(cls, item, detail):
        """薪资优先用列表接口的月薪区间（单位：千元），否则回退详情页文本。"""
        try:
            low = float(item.get('lowMonthPay') or 0)
            high = float(item.get('highMonthPay') or 0)
        except (TypeError, ValueError):
            low = high = 0
        if low > 0 or high > 0:
            return '%d~%d 元/月' % (int(low * 1000), int(high * 1000))

        text = (detail.get('salary_text') or '').replace(' ', '')
        m = re.match(r'^(\d+(?:\.\d+)?)k?-(\d+(?:\.\d+)?)k?$', text, re.I)
        if m:
            unit = 1000 if 'k' in text.lower() else 1
            return '%d~%d 元/月' % (int(float(m.group(1)) * unit), int(float(m.group(2)) * unit))
        return text or '面议'

    @classmethod
    def normalize_degree(cls, text):
        value = cls.clean_text(text)
        if not value:
            return ''
        if '不限' in value or value in ('--', '-'):
            return '无学历要求'
        for level in ('博士', '硕士', '本科', '大专', '中专', '高中'):
            if value.startswith(level):
                return level
        return value

    @classmethod
    def normalize_scale(cls, text):
        value = cls.clean_text(text)
        if not value or value in ('--', '-'):
            return ''
        if value == '不公开' or value.endswith('人'):
            return value
        if value.endswith('以上') or value.endswith('以下'):
            return value[:-2] + '人' + value[-2:]
        return value + '人'

    @staticmethod
    def normalize_head_count(value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return '若干'
        return str(number) if number > 0 else '若干'

    @classmethod
    def build_row(cls, item, detail, source_name=None, crawl_date=None):
        """把列表项 + 详情合并成一行（列顺序见 XLSX_HEADERS）。"""
        province, city, district = cls.split_area(
            detail.get('location'), item.get('areaCodeName', ''))

        job_name = item.get('jobName') or detail.get('job_name') or ''
        is_intern = '实习' in job_name or '实习' in (detail.get('job_detail') or '')[:200]
        if is_intern:
            recruit_type, nature = '实习', '实习'
        elif str(item.get('recruitType', '')) == '1':
            recruit_type, nature = '校园招聘', '校招'
        else:
            recruit_type, nature = '社会招聘', '社招'

        company_property = detail.get('company_property') or ''
        property_name = cls.PROPERTY_MAP.get(company_property, company_property)

        industry = detail.get('company_industry') or ''
        if industry in ('--', '-'):
            industry = ''

        work_city = city[:-1] if city.endswith('市') else city
        work_place = f'{work_city}-{district}' if district else work_city

        address = detail.get('company_address') or ''
        # 部分地址会把「市+区」重复拼接（北京市丰台区北京市丰台区xxx），去掉重复前缀
        for size in range(len(address) // 2, 3, -1):
            if address[:size] == address[size:size * 2]:
                address = address[size:]
                break

        return [
            crawl_date or datetime.now().strftime('%Y-%m-%d'),
            source_name or cls.web_name,
            province,
            city,
            job_name,
            item.get('recName') or detail.get('company_name') or '',
            property_name,
            cls.normalize_scale(item.get('recScale') or detail.get('company_scale')),
            industry,
            recruit_type,
            nature,
            '',
            cls.parse_salary(item, detail),
            cls.normalize_head_count(item.get('headCount')),
            cls.normalize_degree(item.get('degreeName') or detail.get('degree_text')),
            '',
            cls.clean_text(item.get('major')) or detail.get('major') or '专业不限',
            work_place,
            address,
            '',
            detail.get('job_detail') or '',
        ]

    @classmethod
    def parser_page_info(cls, page_info, pause_event=None, is_running=None, on_row=None,
                         source_name=None, crawl_date=None):
        """把一页岗位列表解析成数据行（逐条请求详情页，可暂停/停止）。

        on_row(row) 每成功组装一条就回调，便于界面实时展示与及时落盘。
        """
        rows = []
        for item in page_info:
            # 暂停时阻塞；点停止立即返回
            if not cls._wait():
                break
            job_id = item.get('jobId')
            if not job_id:
                continue
            try:
                detail = cls.get_job_detail(job_id)
            except StopRequested:
                break
            if isinstance(detail, bool) or not detail:
                continue
            try:
                row = cls.build_row(item, detail, source_name, crawl_date)
            except Exception as e:
                logger.error(f'【{cls.web_name}】数据组装失败（{job_id}）：{e}')
                continue
            if row[4]:
                rows.append(row)
                if on_row:
                    on_row(row)
            if not cls._sleep(cls.DEFAULT_DELAY):
                break
        return rows

    # ==================== 采集流程（与 GuoPin 对齐） ====================

    @classmethod
    def get_single_page(cls, wb, ws, data_file, page_id=1, yesterday_data=None,
                        write=True, page_info=None, pause_event=None,
                        is_running=None, auto_login=None, on_row=None,
                        source=None, seen=None):
        """采集单页；write=False 时只返回不写盘。on_row 用于逐条回调。"""
        all_rows = []
        if seen is None:
            seen = set(tuple(r) for r in (yesterday_data or []))

        # 暂停时阻塞；点停止立即返回
        if not cls._wait():
            return all_rows
        if page_info is None:
            page_info = cls.fetch_page(page_id, source, auto_login)
        if isinstance(page_info, bool):
            return all_rows
        if not page_info:
            logger.info(f'【{cls.web_name}】第 {page_id} 页采集 0 条数据')
            return all_rows

        source_name, _st, _sn = cls.resolve_source(source)
        crawl_date = datetime.now().strftime('%Y-%m-%d')
        parsed = cls.parser_page_info(page_info, pause_event, is_running,
                                      source_name=source_name, crawl_date=crawl_date)
        if not parsed and not cls._should_stop() and cls.relogin(auto_login):
            # 详情全部失败，多半是 Cookie 失效
            cls.reset_session()
            parsed = cls.parser_page_info(page_info, pause_event, is_running,
                                          source_name=source_name, crawl_date=crawl_date)

        cls._append_rows(parsed, all_rows, seen, ws, write, on_row)
        if write and all_rows:
            cls._save(wb, data_file)

        logger.info(f'【{cls.web_name}】{source_name} 第 {page_id} 页采集 '
                    f'{len(all_rows)} 条有效数据')
        return all_rows

    @classmethod
    def run(cls, data_file='国家大学生就业服务平台.xlsx', delay=None, max_pages=None,
            auto_login=None, pause_event=None, is_running=None, sources=None,
            on_progress=None, on_page=None, on_data=None, on_complete=None, on_error=None):
        """采集入口：按来源平台逐个翻页 -> 逐条取详情 -> 写入 xlsx。

        sources: 平台名称列表（见 cls.SOURCES），None 表示按 cls.CRAWL_SOURCES 全量采集。
        pause_event: threading.Event（暂停）; is_running: lambda 返回 False 时停止。
        on_progress(index, total, platform)：进入/完成某平台时的平台级进度
        on_page(page_id, page_added, platform_total, elapsed)：单页结果与耗时
        on_data(row) / on_complete(msg) / on_error(msg)
        """
        if delay is not None:
            cls.DEFAULT_DELAY = delay
        if max_pages is not None:
            cls.DEFAULT_PAGES = max_pages

        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)
        cls._begin_run(pause_event, is_running)
        cls._total_pages = 0        # 清掉上一轮残留，避免页数错乱

        source_list = list(sources) if sources else list(cls.CRAWL_SOURCES)
        total_sources = len(source_list)
        all_rows = []
        seen = set(tuple(r) for r in yesterday_data)
        failed_sources = []

        try:
            try:
                cls.ensure_cookie(auto_login)
            except CookieExpired as e:
                logger.error(f'【{cls.web_name}】{e}')
                if on_error:
                    on_error(str(e))
                if on_complete:
                    on_complete(f'{cls.web_name}采集失败')
                return []

            names = '、'.join(cls.resolve_source(s)[0] for s in source_list)
            logger.info(f'【{cls.web_name}】待采平台 {total_sources} 个：{names}')

            for index, source in enumerate(source_list, 1):
                name, sources_type, sources_name = cls.resolve_source(source)
                if not cls._wait():
                    logger.info(f'【{cls.web_name}】用户终止采集')
                    break
                if on_progress:
                    on_progress(index - 1, total_sources, name)
                logger.info(f'开始采集【{cls.web_name}】平台 {index}/{total_sources}：{name} '
                            f'(sourcesType={sources_type!r}, sourcesName={sources_name!r})')

                # 该平台第一页：失败时重登一次，仍失败则跳过该平台
                page_info = cls.fetch_page(1, source, auto_login)
                if isinstance(page_info, bool):
                    logger.error(f'【{cls.web_name}】{name} 列表获取失败，跳过该平台')
                    failed_sources.append(name)
                    if on_error:
                        on_error(f'{name}: 列表获取失败，已跳过')
                    continue
                if not page_info:
                    logger.info(f'【{cls.web_name}】{name} 当前无在招岗位，跳过')
                    if on_progress:
                        on_progress(index, total_sources, name)
                    continue

                pages = min(cls._total_pages or cls.DEFAULT_PAGES, cls.DEFAULT_PAGES)
                logger.info(f'【{cls.web_name}】{name} 共 {pages} 页，每页 {cls.DEFAULT_PAGE_SIZE} 条，'
                            f'间隔 {cls.DEFAULT_DELAY}s')

                page_fails = 0
                platform_rows = 0
                for page_id in range(1, pages + 1):
                    if not cls._wait():
                        logger.info(f'【{cls.web_name}】用户终止采集')
                        break

                    if page_id > 1:
                        # 页间等待可被停止/暂停打断
                        if not cls._sleep(cls.DEFAULT_DELAY):
                            logger.info(f'【{cls.web_name}】用户终止采集')
                            break
                        page_info = cls.fetch_page(page_id, source, auto_login)
                        if isinstance(page_info, bool):
                            page_fails += 1
                            if on_error:
                                on_error(f'{name} 第 {page_id} 页列表获取失败'
                                         f'（{page_fails}/{cls.MAX_PAGE_FAILS}）')
                            if page_fails >= cls.MAX_PAGE_FAILS:
                                logger.error(f'【{cls.web_name}】{name} 连续多页列表失败，结束该平台')
                                break
                            if not cls._sleep(cls.RETRY_BACKOFF * page_fails):
                                break
                            continue
                        page_fails = 0
                        if not page_info:
                            break

                    label = f'{name} 第 {page_id}/{pages} 页'
                    logger.info(f'开始采集【{cls.web_name}】{label}')
                    page_started = time.time()

                    try:
                        rows = cls.get_single_page(
                            wb, ws, data_file, page_id,
                            yesterday_data=yesterday_data, write=True,
                            page_info=page_info,
                            pause_event=pause_event,
                            is_running=is_running,
                            auto_login=auto_login,
                            on_row=on_data if on_data else None,
                            source=source,
                            seen=seen,
                        )
                        all_rows.extend(rows)
                        platform_rows += len(rows)
                        elapsed = time.time() - page_started
                        logger.info(f'【{cls.web_name}】{label} 完成：新增 {len(rows)} 条，'
                                    f'本平台累计 {platform_rows} 条，本页 {elapsed:.1f}s')
                        if on_page:
                            on_page(page_id, len(rows), platform_rows, elapsed)
                    except StopRequested:
                        logger.info(f'【{cls.web_name}】用户终止采集')
                        break
                    except Exception as e:
                        logger.error(f'【{cls.web_name}】{label} 采集异常：{e}')
                        if on_error:
                            on_error(f'{label}: {e}')

                    if cls._should_stop():
                        logger.info(f'【{cls.web_name}】用户终止采集')
                        break

                logger.info(f'【{cls.web_name}】{name} 采集结束：新增 {platform_rows} 条')
                if on_progress:
                    on_progress(index, total_sources, name)
                if cls._should_stop():
                    break
        finally:
            # 无论正常结束还是中途停止，都把内存里的数据落盘
            try:
                cls._save(wb, data_file, force=True)
            except Exception as e:
                logger.error(f'【{cls.web_name}】保存失败：{e}')

        if failed_sources:
            logger.info(f'【{cls.web_name}】失败平台：{"、".join(failed_sources)}')
        if on_complete:
            on_complete(cls._finish_message(len(all_rows), cls._should_stop(),
                                            len(failed_sources)))
        return all_rows


