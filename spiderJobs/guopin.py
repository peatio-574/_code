# coding='utf-8'
"""国聘岗位采集：通过 HTTP 接口同步抓取岗位数据，写入 xlsx。

公共常量与 xlsx 工具在 getJobs.py，此处只保留国聘相关逻辑。
"""
import json
import time
from datetime import datetime

import requests

from getJobs import BaseSpider, create_session, load_config
from Logger import logger


# ==================== 国聘省市码（config/guopin_area.json） ====================
# 原为 480 行硬编码，现改为读取 JSON 配置，便于增删城市而无需改代码。
# JSON 结构：{"provinces": {省code: 省名}, "cities": {省code: {市名: 市code}}}
_AREA_CFG = load_config('guopin_area.json', {}) or {}
GUOPIN_PROVINCES = _AREA_CFG.get('provinces') or {}
GUOPIN_CITIES = _AREA_CFG.get('cities') or {}
GUOPIN_AREA = {"provinces": GUOPIN_PROVINCES, "cities": GUOPIN_CITIES}

if not GUOPIN_CITIES:
    logger.error('【国聘】未读取到省市配置（config/guopin_area.json），'
                 '采集将无可选城市，请检查配置文件')

# ==================== 国聘采集 ====================
class GuoPin(BaseSpider):
    """国聘采集类：通过 HTTP 接口同步抓取岗位数据，写入 xlsx。"""

    web_name = '国聘'
    # 区域码（config/guopin_area.json，缺失时为空，run 会提示）
    area_codes = GUOPIN_AREA

    # 接口 / 抓取参数
    API = 'https://gp-api.iguopin.com/api/jobs/v1/recom-job'
    USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')
    DEFAULT_PAGE_SIZE = 20        # 与接口 page_size 一致
    DEFAULT_PAGES = 20            # 单城市最大页数
    DEFAULT_DELAY = 0.5           # 城市之间额外等待（秒），0 表示不等待
    REQUEST_TIMEOUT = 8           # 单次请求超时（秒）；过长会让「停止」等很久
    RETRY_TIMES = 3               # 单页最大尝试次数
    RETRY_BACKOFF = 2.0           # 重试退避基数（秒）
    MAX_PAGE_FAILS = 3            # 连续多少页列表失败后停止该城市
    SAVE_INTERVAL = 10            # 两次写盘的最小间隔（秒）

    _session = None               # 复用连接与统一证书配置

    @classmethod
    def session(cls):
        """国聘专用 requests 会话（带 certifi + 系统证书库）。"""
        if cls._session is None:
            cls._session = create_session()
        return cls._session

    @classmethod
    def get_page_info(cls, page_id=1, province_name='北京', province_code=110000,
                      city_name='北京市', city_code=110100):
        """获取单页数据；失败返回 False（与其它采集类保持一致）。"""
        headers = {
            'content-type': 'application/json',
            'user-agent': cls.USER_AGENT,
        }
        payload = {
            "search": {
                "page": page_id,
                "page_size": cls.DEFAULT_PAGE_SIZE,
                "district": [f"000000.{province_code}.{city_code}"],
            },
            "recom": {
                "update_time": True,
                "company_nature": True,
                "hot_job": True,
            },
        }
        last_error = None
        session = cls.session()
        for attempt in range(1, cls.RETRY_TIMES + 1):
            if cls._should_stop():
                return False
            try:
                response = session.post(cls.API, data=json.dumps(payload),
                                        headers=headers, timeout=cls.REQUEST_TIMEOUT)
                response.raise_for_status()
                return (response.json().get('data') or {}).get('list') or []
            except (requests.RequestException, ValueError) as e:
                last_error = e
                if attempt < cls.RETRY_TIMES:
                    wait = cls.RETRY_BACKOFF * attempt
                    logger.info(f'【{cls.web_name}】{province_name}-{city_name} 第{page_id}页'
                                f'失败，{wait:.1f}s 后重试（{attempt}/{cls.RETRY_TIMES}）：{e}')
                    # 重试等待同样可被停止/暂停打断
                    if not cls._sleep(wait):
                        return False
        logger.error(f'{province_name}-{city_name} 第{page_id}页{cls.web_name}数据采集失败：{last_error}')
        return False


    @staticmethod
    def format_salary(row):
        """格式化薪资。

        国聘部分岗位 min_wage / max_wage 都是 0（表示面议/未公开），
        直接拼成「0~0 元/月」会让数据看起来像异常，这里统一返回「面议」。
        """
        try:
            low = float(row.get('min_wage') or 0)
            high = float(row.get('max_wage') or 0)
        except (TypeError, ValueError):
            low = high = 0

        if low <= 0 and high <= 0:
            return '面议'

        def _fmt(v):
            v = float(v)
            return str(int(v)) if v == int(v) else str(v)

        unit = (row.get('wage_unit_cn') or '').strip()
        return ('%s~%s %s' % (_fmt(low), _fmt(high), unit)).strip()

    @classmethod
    def parser_page_info(cls, province_name, city_name, page_info, crawl_date=None):
        """解析单页数据；crawl_date 复用一个采集日期，避免逐行取系统时间。"""
        crawl_date = crawl_date or datetime.now().strftime('%Y-%m-%d')
        rows = []
        for row in page_info:
            company = row.get('company_info') or {}
            districts = row.get('district_list') or []
            first_district = districts[0] if districts else {}
            rows.append([
                crawl_date,
                cls.source_code,
                province_name,
                city_name,
                row.get('job_name') or '',
                str(row.get('job_id') or ''),        # 岗位编号（国聘 job_id）
                row.get('company_name') or '',
                company.get('nature_cn') or '',
                company.get('scale_cn') or '',
                company.get('industry_cn') or '',
                row.get('recruitment_type_cn') or '',
                row.get('nature_cn') or '',
                row.get('category_cn') or '',
                cls.format_salary(row),
                str(row['amount']) if (row.get('amount') or 0) > 0 else '若干',
                row.get('education_cn') or '',
                row.get('experience_cn') or '',
                ', '.join(row.get('major_cn') or []),
                first_district.get('area_cn') or '',
                first_district.get('address') or '',
                row.get('end_time') or '',
                row.get('contents') or '',
            ])
        return rows


    @classmethod
    def get_single_city(cls, wb, ws, data_file, province_name='北京',
            province_code=110000, city_name='北京市', city_code=110100,
            yesterday_data=None, write=True, pause_event=None, is_running=None,
            on_page=None, on_data=None):
        """采集单个城市，write=False时仅返回数据不写入。

        pause_event: threading.Event，暂停时 wait() 阻塞；is_running: 返回布尔，False 停止。
        on_page(page_id, page_added, city_total, elapsed): 每页结束回调，用于界面显示进度与耗时。
        on_data(row): 每采集到一条新数据即刻回调，避免整城市采完才一次性刷新界面。
        """
        all_rows = []
        crawl_date = datetime.now().strftime('%Y-%m-%d')
        started = time.time()
        # 去重集合：整行(不含采集日期)作键
        seen = cls.init_seen(yesterday_data)
        page_fails = 0                      # 连续失败页数
        for page_id in range(1, cls.DEFAULT_PAGES + 1):
            # 暂停时阻塞；点停止立刻返回 False
            if not cls._wait():
                break
            page_started = time.time()
            page_info = cls.get_page_info(page_id=page_id, province_name=province_name,
                                          province_code=province_code,
                                          city_name=city_name, city_code=city_code)
            if isinstance(page_info, bool):
                # 单页已重试仍失败：累计连续失败，超过上限就放弃该城市
                page_fails += 1
                logger.warning(f'【{cls.web_name}】{province_name}-{city_name} 第{page_id}页'
                               f'获取失败（连续 {page_fails}/{cls.MAX_PAGE_FAILS}）')
                if page_fails >= cls.MAX_PAGE_FAILS:
                    logger.error(f'【{cls.web_name}】{province_name}-{city_name} '
                                 f'连续 {page_fails} 页失败，跳过该城市')
                    break
                if not cls._sleep(cls.RETRY_BACKOFF * page_fails):
                    break
                continue
            page_fails = 0                  # 成功一页即重置
            if not page_info:
                logger.info(f'【{cls.web_name}】{province_name}-{city_name} 第{page_id}页'
                            f'采集0条（已到末页），本城市累计{len(all_rows)}条，'
                            f'用时{time.time() - started:.1f}s')
                break

            parsed = cls.parser_page_info(province_name=province_name, city_name=city_name,
                                          page_info=page_info, crawl_date=crawl_date)
            count = cls._append_rows(parsed, all_rows, seen, ws, write, on_data)
            # 写盘节流：避免每页都整本重写导致界面卡顿
            if write and count:
                cls._save(wb, data_file)

            elapsed = time.time() - started
            logger.info(f'【{cls.web_name}】{province_name}-{city_name} 第{page_id}页 '
                        f'新增{count}条，本城市累计{len(all_rows)}条，'
                        f'本页{time.time() - page_started:.1f}s，累计{elapsed:.1f}s')
            if on_page is not None:
                on_page(page_id, count, len(all_rows), elapsed)
            if len(parsed) < cls.DEFAULT_PAGE_SIZE:
                break
        if all_rows:
            logger.info(f'【{cls.web_name}】{province_name}-{city_name} 采集结束，'
                        f'共{len(all_rows)}条，总用时{time.time() - started:.1f}s')
        return all_rows

    @classmethod
    def run(cls, data_file='国聘数据.xlsx', pause_event=None, is_running=None,
            update_duplicate=None,
            on_progress=None, on_page=None, on_data=None, on_complete=None,
            on_error=None):
        """采集入口：逐城市分页采集 -> 写入 xlsx。

        on_progress(done, total, city_label)：城市级进度（进入城市时回调）
        on_page(page_id, page_added, city_total, elapsed)：页级进度，含耗时
        on_data(row)：每条新数据即刻回调，界面可实时刷新
        on_complete(msg)：结束回调（区分正常完成 / 用户停止）
        on_error(msg)：单个城市采集异常时回调
        """
        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)
        province_info = cls.area_codes.get('provinces') or {}
        citys_info = cls.area_codes.get('cities') or {}
        total_cities = sum(len(c) for c in citys_info.values())

        cls._begin_run(pause_event, is_running,
                            update_duplicate=update_duplicate)
        done_cities = 0
        stopped = False
        failed = []
        all_rows = []
        try:
            for province_code, city_info in citys_info.items():
                province_name = province_info.get(province_code, '')
                for city_name, city_code in city_info.items():
                    if not cls._wait():
                        logger.info(f'【{cls.web_name}】用户终止采集')
                        stopped = True
                        break
                    city_label = f'{province_name}-{city_name}'
                    if on_progress is not None:
                        on_progress(done_cities, total_cities, city_label)
                    # 单个城市采集
                    logger.info(f'开始采集【{cls.web_name}{city_label}】'
                                f'[{province_code}.{city_code}] '
                                f'（第 {done_cities + 1}/{total_cities} 个城市）')
                    try:
                        city_rows = cls.get_single_city(
                            wb, ws, data_file, province_name, province_code,
                            city_name, city_code, yesterday_data,
                            pause_event=pause_event, is_running=is_running,
                            on_page=on_page, on_data=on_data)
                        all_rows.extend(city_rows or [])
                    except Exception as e:
                        failed.append(city_label)
                        logger.error(f'【{cls.web_name}】{city_label} 采集异常：{e}')
                        if on_error:
                            on_error(f'{city_label}: {e}')
                    done_cities += 1
                    if cls._should_stop():
                        logger.info(f'【{cls.web_name}】用户终止采集')
                        stopped = True
                        break
                    if cls.DEFAULT_DELAY:
                        if not cls._sleep(cls.DEFAULT_DELAY):
                            stopped = True
                            break
                if stopped:
                    break
        finally:
            # 无论正常结束还是中途停止，都把内存里的数据落盘
            cls._save(wb, data_file, force=True)

        if failed:
            logger.info(f'【{cls.web_name}】失败城市 {len(failed)} 个：{"、".join(failed[:10])}')
        if on_complete is not None:
            on_complete(cls._finish_message(len(all_rows), stopped, len(failed)))
        return all_rows
