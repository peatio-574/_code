# coding='utf-8'
"""国聘岗位采集：通过 HTTP 接口同步抓取岗位数据，写入 xlsx。

公共常量与 xlsx 工具在 getJobs.py，此处只保留国聘相关逻辑。
"""
import json
import time
from datetime import datetime

import requests

from getJobs import BaseSpider
from Logger import logger


GUOPIN_PROVINCES = {
    "110000": "北京",
    "120000": "天津",
    "130000": "河北",
    "140000": "山西",
    "150000": "内蒙古",
    "210000": "辽宁",
    "220000": "吉林",
    "230000": "黑龙江",
    "310000": "上海",
    "320000": "江苏",
    "330000": "浙江",
    "340000": "安徽",
    "350000": "福建",
    "360000": "江西",
    "370000": "山东",
    "410000": "河南",
    "420000": "湖北",
    "430000": "湖南",
    "440000": "广东",
    "450000": "广西",
    "460000": "海南",
    "500000": "重庆",
    "510000": "四川",
    "520000": "贵州",
    "530000": "云南",
    "540000": "西藏",
    "610000": "陕西",
    "620000": "甘肃",
    "630000": "青海",
    "640000": "宁夏",
    "650000": "新疆",
    "710000": "中国台湾",
    "810000": "香港",
    "820000": "澳门"
}

GUOPIN_CITIES = {
    "110000": {
        "北京市": "110100"
    },
    "120000": {
        "天津市": "120100"
    },
    "130000": {
        "石家庄市": "130100",
        "唐山市": "130200",
        "秦皇岛市": "130300",
        "邯郸市": "130400",
        "邢台市": "130500",
        "保定市": "130600",
        "张家口市": "130700",
        "承德市": "130800",
        "沧州市": "130900",
        "廊坊市": "131000",
        "衡水市": "131100",
        "雄安新区": "131200"
    },
    "140000": {
        "太原市": "140100",
        "大同市": "140200",
        "阳泉市": "140300",
        "长治市": "140400",
        "晋城市": "140500",
        "朔州市": "140600",
        "晋中市": "140700",
        "运城市": "140800",
        "忻州市": "140900",
        "临汾市": "141000",
        "吕梁市": "141100"
    },
    "150000": {
        "呼和浩特市": "150100",
        "包头市": "150200",
        "乌海市": "150300",
        "赤峰市": "150400",
        "通辽市": "150500",
        "鄂尔多斯市": "150600",
        "呼伦贝尔市": "150700",
        "巴彦淖尔市": "150800",
        "乌兰察布市": "150900",
        "兴安盟": "152200",
        "锡林郭勒盟": "152500",
        "阿拉善盟": "152900"
    },
    "210000": {
        "沈阳市": "210100",
        "大连市": "210200",
        "鞍山市": "210300",
        "抚顺市": "210400",
        "本溪市": "210500",
        "丹东市": "210600",
        "锦州市": "210700",
        "营口市": "210800",
        "阜新市": "210900",
        "辽阳市": "211000",
        "盘锦市": "211100",
        "铁岭市": "211200",
        "朝阳市": "211300",
        "葫芦岛市": "211400"
    },
    "220000": {
        "长春市": "220100",
        "吉林市": "220200",
        "四平市": "220300",
        "辽源市": "220400",
        "通化市": "220500",
        "白山市": "220600",
        "松原市": "220700",
        "白城市": "220800",
        "延边朝鲜族自治州": "222400"
    },
    "230000": {
        "哈尔滨市": "230100",
        "齐齐哈尔市": "230200",
        "鸡西市": "230300",
        "鹤岗市": "230400",
        "双鸭山市": "230500",
        "大庆市": "230600",
        "伊春市": "230700",
        "佳木斯市": "230800",
        "七台河市": "230900",
        "牡丹江市": "231000",
        "黑河市": "231100",
        "绥化市": "231200",
        "大兴安岭地区": "232700"
    },
    "310000": {
        "上海市": "310100"
    },
    "320000": {
        "南京市": "320100",
        "无锡市": "320200",
        "徐州市": "320300",
        "常州市": "320400",
        "苏州市": "320500",
        "南通市": "320600",
        "连云港市": "320700",
        "淮安市": "320800",
        "盐城市": "320900",
        "扬州市": "321000",
        "镇江市": "321100",
        "泰州市": "321200",
        "宿迁市": "321300"
    },
    "330000": {
        "杭州市": "330100",
        "宁波市": "330200",
        "温州市": "330300",
        "嘉兴市": "330400",
        "湖州市": "330500",
        "绍兴市": "330600",
        "金华市": "330700",
        "衢州市": "330800",
        "舟山市": "330900",
        "台州市": "331000",
        "丽水市": "331100"
    },
    "340000": {
        "合肥市": "340100",
        "芜湖市": "340200",
        "蚌埠市": "340300",
        "淮南市": "340400",
        "马鞍山市": "340500",
        "淮北市": "340600",
        "铜陵市": "340700",
        "安庆市": "340800",
        "黄山市": "341000",
        "滁州市": "341100",
        "阜阳市": "341200",
        "宿州市": "341300",
        "六安市": "341500",
        "亳州市": "341600",
        "池州市": "341700",
        "宣城市": "341800"
    },
    "350000": {
        "福州市": "350100",
        "厦门市": "350200",
        "莆田市": "350300",
        "三明市": "350400",
        "泉州市": "350500",
        "漳州市": "350600",
        "南平市": "350700",
        "龙岩市": "350800",
        "宁德市": "350900"
    },
    "360000": {
        "南昌市": "360100",
        "景德镇市": "360200",
        "萍乡市": "360300",
        "九江市": "360400",
        "新余市": "360500",
        "鹰潭市": "360600",
        "赣州市": "360700",
        "吉安市": "360800",
        "宜春市": "360900",
        "抚州市": "361000",
        "上饶市": "361100"
    },
    "370000": {
        "济南市": "370100",
        "青岛市": "370200",
        "淄博市": "370300",
        "枣庄市": "370400",
        "东营市": "370500",
        "烟台市": "370600",
        "潍坊市": "370700",
        "济宁市": "370800",
        "泰安市": "370900",
        "威海市": "371000",
        "日照市": "371100",
        "临沂市": "371300",
        "德州市": "371400",
        "聊城市": "371500",
        "滨州市": "371600",
        "菏泽市": "371700"
    },
    "410000": {
        "郑州市": "410100",
        "开封市": "410200",
        "洛阳市": "410300",
        "平顶山市": "410400",
        "安阳市": "410500",
        "鹤壁市": "410600",
        "新乡市": "410700",
        "焦作市": "410800",
        "濮阳市": "410900",
        "许昌市": "411000",
        "漯河市": "411100",
        "三门峡市": "411200",
        "南阳市": "411300",
        "商丘市": "411400",
        "信阳市": "411500",
        "周口市": "411600",
        "驻马店市": "411700",
        "济源市": "419001"
    },
    "420000": {
        "武汉市": "420100",
        "黄石市": "420200",
        "十堰市": "420300",
        "宜昌市": "420500",
        "襄阳市": "420600",
        "鄂州市": "420700",
        "荆门市": "420800",
        "孝感市": "420900",
        "荆州市": "421000",
        "黄冈市": "421100",
        "咸宁市": "421200",
        "随州市": "421300",
        "恩施土家族苗族自治州": "422800",
        "仙桃市": "429004",
        "潜江市": "429005",
        "天门市": "429006",
        "神农架林区": "429021"
    },
    "430000": {
        "长沙市": "430100",
        "株洲市": "430200",
        "湘潭市": "430300",
        "衡阳市": "430400",
        "邵阳市": "430500",
        "岳阳市": "430600",
        "常德市": "430700",
        "张家界市": "430800",
        "益阳市": "430900",
        "郴州市": "431000",
        "永州市": "431100",
        "怀化市": "431200",
        "娄底市": "431300",
        "湘西土家族苗族自治州": "433100"
    },
    "440000": {
        "广州市": "440100",
        "韶关市": "440200",
        "深圳市": "440300",
        "珠海市": "440400",
        "汕头市": "440500",
        "佛山市": "440600",
        "江门市": "440700",
        "湛江市": "440800",
        "茂名市": "440900",
        "肇庆市": "441200",
        "惠州市": "441300",
        "梅州市": "441400",
        "汕尾市": "441500",
        "河源市": "441600",
        "阳江市": "441700",
        "清远市": "441800",
        "东莞市": "441900",
        "中山市": "442000",
        "潮州市": "445100",
        "揭阳市": "445200",
        "云浮市": "445300"
    },
    "450000": {
        "南宁市": "450100",
        "柳州市": "450200",
        "桂林市": "450300",
        "梧州市": "450400",
        "北海市": "450500",
        "防城港市": "450600",
        "钦州市": "450700",
        "贵港市": "450800",
        "玉林市": "450900",
        "百色市": "451000",
        "贺州市": "451100",
        "河池市": "451200",
        "来宾市": "451300",
        "崇左市": "451400"
    },
    "460000": {
        "海口市": "460100",
        "三亚市": "460200",
        "儋州市": "460400",
        "三沙市": "460300",
        "五指山市": "469001",
        "琼海市": "469002",
        "文昌市": "469005",
        "万宁市": "469006",
        "东方市": "469007",
        "定安县": "469021",
        "屯昌县": "469022",
        "澄迈县": "469023",
        "临高县": "469024",
        "白沙黎族自治县": "469025",
        "昌江黎族自治县": "469026",
        "乐东黎族自治县": "469027",
        "陵水黎族自治县": "469028",
        "保亭黎族苗族自治县": "469029",
        "琼中黎族苗族自治县": "469030"
    },
    "500000": {
        "重庆市": "500100"
    },
    "510000": {
        "成都市": "510100",
        "自贡市": "510300",
        "攀枝花市": "510400",
        "泸州市": "510500",
        "德阳市": "510600",
        "绵阳市": "510700",
        "广元市": "510800",
        "遂宁市": "510900",
        "内江市": "511000",
        "乐山市": "511100",
        "南充市": "511300",
        "眉山市": "511400",
        "宜宾市": "511500",
        "广安市": "511600",
        "达州市": "511700",
        "雅安市": "511800",
        "巴中市": "511900",
        "资阳市": "512000",
        "阿坝藏族羌族自治州": "513200",
        "甘孜藏族自治州": "513300",
        "凉山彝族自治州": "513400"
    },
    "520000": {
        "贵阳市": "520100",
        "六盘水市": "520200",
        "遵义市": "520300",
        "安顺市": "520400",
        "铜仁市": "520600",
        "毕节市": "520500",
        "黔西南布依族苗族自治州": "522300",
        "黔东南苗族侗族自治州": "522600",
        "黔南布依族苗族自治州": "522700"
    },
    "530000": {
        "昆明市": "530100",
        "曲靖市": "530300",
        "玉溪市": "530400",
        "保山市": "530500",
        "昭通市": "530600",
        "丽江市": "530700",
        "普洱市": "530800",
        "临沧市": "530900",
        "楚雄彝族自治州": "532300",
        "红河哈尼族彝族自治州": "532500",
        "文山壮族苗族自治州": "532600",
        "西双版纳傣族自治州": "532800",
        "大理白族自治州": "532900",
        "德宏傣族景颇族自治州": "533100",
        "怒江傈僳族自治州": "533300",
        "迪庆藏族自治州": "533400"
    },
    "540000": {
        "拉萨市": "540100",
        "昌都市": "540300",
        "山南市": "540500",
        "日喀则市": "540200",
        "那曲市": "540600",
        "阿里地区": "542500",
        "林芝市": "540400"
    },
    "610000": {
        "西安市": "610100",
        "铜川市": "610200",
        "宝鸡市": "610300",
        "咸阳市": "610400",
        "渭南市": "610500",
        "延安市": "610600",
        "汉中市": "610700",
        "榆林市": "610800",
        "安康市": "610900",
        "商洛市": "611000"
    },
    "620000": {
        "兰州市": "620100",
        "嘉峪关市": "620200",
        "金昌市": "620300",
        "白银市": "620400",
        "天水市": "620500",
        "武威市": "620600",
        "张掖市": "620700",
        "平凉市": "620800",
        "酒泉市": "620900",
        "庆阳市": "621000",
        "定西市": "621100",
        "陇南市": "621200",
        "临夏回族自治州": "622900",
        "甘南藏族自治州": "623000"
    },
    "630000": {
        "西宁市": "630100",
        "海东市": "630200",
        "海北藏族自治州": "632200",
        "黄南藏族自治州": "632300",
        "海南藏族自治州": "632500",
        "果洛藏族自治州": "632600",
        "玉树藏族自治州": "632700",
        "海西蒙古族藏族自治州": "632800"
    },
    "640000": {
        "银川市": "640100",
        "石嘴山市": "640200",
        "吴忠市": "640300",
        "固原市": "640400",
        "中卫市": "640500"
    },
    "650000": {
        "乌鲁木齐市": "650100",
        "克拉玛依市": "650200",
        "吐鲁番市": "650400",
        "哈密市": "650500",
        "昌吉回族自治州": "652300",
        "博尔塔拉蒙古自治州": "652700",
        "巴音郭楞蒙古自治州": "652800",
        "阿克苏地区": "652900",
        "克孜勒苏柯尔克孜自治州": "653000",
        "喀什地区": "653100",
        "和田地区": "653200",
        "伊犁哈萨克自治州": "654000",
        "塔城地区": "654200",
        "阿勒泰地区": "654300",
        "石河子市": "659001",
        "阿拉尔市": "659002",
        "图木舒克市": "659003",
        "五家渠市": "659004",
        "铁门关市": "659006",
        "双河市": "659007",
        "北屯市": "659005",
        "可克达拉市": "659008",
        "昆玉市": "659009",
        "胡杨河市": "659010",
        "新星市": "659011",
        "白杨市": "659012"
    },
    "710000": {
        "中国台湾": "710100"
    },
    "810000": {
        "香港": "810100"
    },
    "820000": {
        "澳门": "820100"
    }
}

# ==================== 国聘省市码（内嵌） ====================
# 原为外部文件 data.json（国聘接口的省市编码），现已内嵌为 Python 常量，
# 运行时不依赖任何外部数据文件。prov/city 均为 国聘接口使用的编码值。
GUOPIN_AREA = {"provinces": GUOPIN_PROVINCES, "cities": GUOPIN_CITIES}

# ==================== 国聘采集 ====================
class GuoPin(BaseSpider):
    """国聘采集类：通过 HTTP 接口同步抓取岗位数据，写入 xlsx。"""

    web_name = '国聘'
    # 区域码（已内嵌，不再依赖 data.json）
    area_codes = GUOPIN_AREA

    # 接口 / 抓取参数
    API = 'https://gp-api.iguopin.com/api/jobs/v1/recom-job'
    USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')
    DEFAULT_PAGE_SIZE = 20        # 与接口 page_size 一致
    DEFAULT_PAGES = 20            # 单城市最大页数
    DEFAULT_DELAY = 0.0           # 城市之间额外等待（秒）
    REQUEST_TIMEOUT = 15          # 单次请求超时（秒）
    RETRY_TIMES = 3               # 单页最大尝试次数
    RETRY_BACKOFF = 2.0           # 重试退避基数（秒）
    SAVE_INTERVAL = 10            # 两次写盘的最小间隔（秒）

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
        for attempt in range(1, cls.RETRY_TIMES + 1):
            if cls._should_stop():
                return False
            try:
                response = requests.post(cls.API, data=json.dumps(payload),
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
                cls.web_name,
                province_name,
                city_name,
                row.get('job_name') or '',
                row.get('company_name') or '',
                company.get('nature_cn') or '',
                company.get('scale_cn') or '',
                company.get('industry_cn') or '',
                row.get('recruitment_type_cn') or '',
                row.get('nature_cn') or '',
                row.get('category_cn') or '',
                f"{row.get('min_wage') or 0}~{row.get('max_wage') or 0} "
                f"{row.get('wage_unit_cn') or ''}".strip(),
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
        seen = set(tuple(r) for r in (yesterday_data or []))
        for page_id in range(1, cls.DEFAULT_PAGES + 1):
            # 暂停时阻塞；点停止立刻返回 False
            if not cls._wait():
                break
            page_started = time.time()
            page_info = cls.get_page_info(page_id=page_id, province_name=province_name,
                                          province_code=province_code,
                                          city_name=city_name, city_code=city_code)
            if isinstance(page_info, bool):
                # 失败已记录日志；连续失败由 run 的页失败计数控制
                continue
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

        cls._begin_run(pause_event, is_running)
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
