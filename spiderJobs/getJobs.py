# coding='utf-8'
"""招聘岗位数据采集系统
========================
本脚本同时支持【国聘】和【智联招聘】两个网站的岗位数据采集，并提供可视化界面。

模块结构：
  - 顶层常量：两个网站统一的表格列 XLSX_HEADERS、国聘省市码（已内嵌，不再依赖 data.json）。
  - GuoPin   ：国聘采集类（基于 requests 请求接口，同步采集）。
  - ZhiPin   ：智联招聘采集类（基于 Playwright 浏览器登录态，异步采集）。
  - GUI 类   ：BaseSpiderGUI（通用界面基类）、GuoPinGUI、SpiderGUI（多站点选择界面）。

统一输出字段：采集日期、来源、省份、城市、职位名称……职位描述（见 XLSX_HEADERS）。
"""
import asyncio
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from html import unescape as html_unescape

import requests

# 日志目录：当前运行路径下的 ./logs（如需自定义可设置环境变量 LOG_DIR）
os.environ.setdefault('LOG_DIR', os.path.join(os.getcwd(), 'logs'))

from Logger import logger
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

import tkinter as tk
from tkinter import ttk, simpledialog


# ==================== Playwright 浏览器路径（打包友好） ====================
# 打包成 exe 时使用随包内置的 Chromium：构建与运行时都设 PLAYWRIGHT_BROWSERS_PATH=0，
# 浏览器位于 playwright 包内，会被 PyInstaller 一并打进 exe，目标机无需另装 Chrome。
# 如需强制使用系统 Chrome，可设置环境变量 PLAYWRIGHT_CHANNEL=chrome。
if getattr(sys, 'frozen', False):
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '0')


# ==================== 统一输出表格列 ====================
# 两个站点共用的表头，导出 xlsx / 界面展示都以此为准。
XLSX_HEADERS = [
    '采集日期', '来源', '省份', '城市',
    "职位名称", "公司名称", "公司性质", "公司规模", "公司行业",
    "招聘类型", "职位性质", "职位类别", "薪资范围", "招聘人数",
    "学历要求", "经验要求", "专业要求", "工作地点", "详细地址",
    "报名截止", "职位描述"
]

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


def _read_xlsx_rows(file):
    """用openpyxl按行读取xlsx，返回 [[col1,col2,...], ...]"""
    if not os.path.exists(file):
        return []
    wb = load_workbook(file, read_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        # 把单元格统一转成字符串，空值为空串，便于后续处理
        row = [str(c) if c is not None else '' for c in row]
        rows.append(row)
    wb.close()
    return rows


# ==================== 国聘采集 ====================
class GuoPin(object):
    """国聘采集类：通过 HTTP 接口同步抓取岗位数据，写入 xlsx。"""
    # 网站名称
    web_name = '国聘'
    # 区域码（已内嵌，不再依赖 data.json）
    area_codes = GUOPIN_AREA


    @classmethod
    def load_yesterday_data(cls, data_file):
        """读取昨天数据"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        all_data = _read_xlsx_rows(data_file)
        yesterday_data = []
        for row in all_data:
            date_val = str(row[0]).split(' ')[0]
            if date_val not in (yesterday, today):
                continue
            yesterday_data.append(row[1:])
        return yesterday_data


    @classmethod
    def set_column_style(cls, data_file):
        """设置表头格式"""
        xlsx_headers = XLSX_HEADERS

        wb = load_workbook(filename=data_file) if os.path.exists(data_file) else Workbook()
        ws = wb.active
        ws.title = "职位数据"

        ws.freeze_panes = 'A2'
        HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")

        THIN_BORDER = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        for col, header in enumerate(xlsx_headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = THIN_BORDER
        wb.save(data_file)
        return wb, ws


    @classmethod
    def get_page_info(cls, page_id=1, province_name='北京', province_code=110000,
                      city_name='北京市', city_code=110100):
        """获取单页数据"""
        try:
            url = 'https://gp-api.iguopin.com/api/jobs/v1/recom-job'

            headers = {
                'content-type': 'application/json',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'
            }

            params = {
                "search": {
                    "page": page_id,
                    "page_size": 20,
                    "district": [
                        f"000000.{province_code}.{city_code}"
                    ]
                },
                "recom": {
                    "update_time": True,
                    "company_nature": True,
                    "hot_job": True
                }
            }
            response = requests.post(url, data=json.dumps(params), headers=headers).json()
            return response['data']['list']
        except Exception as e:
            logger.error(f'{province_name}-{city_name} 第{page_id}页{cls.web_name}数据采集失败：{e}')
            return False


    @classmethod
    def parser_page_info(cls, province_name, city_name, page_info):
        """解析单页数据"""
        rows = []
        for row in page_info:
            job_name = row['job_name']
            company_name = row['company_name']
            row_info = [
                datetime.now().strftime('%Y-%m-%d'),
                cls.web_name,
                province_name,
                city_name,
                job_name,
                company_name,
                row['company_info']['nature_cn'] or '',
                row['company_info']['scale_cn'] or '',
                row['company_info'].get('industry_cn') or '',
                row['recruitment_type_cn'] or '',
                row['nature_cn'] or '',
                row['category_cn'] or '',
                f"{row['min_wage']}~{row['max_wage']} {row['wage_unit_cn']}",
                str(row['amount']) if row['amount'] > 0 else '若干',
                row['education_cn'] or '',
                row['experience_cn'] or '',
                ', '.join(row.get('major_cn', []) or []),
                row['district_list'][0]['area_cn'] if row.get('district_list') else '',
                row['district_list'][0].get('address') or '' if row.get('district_list') else '',
                row['end_time'] or '',
                row['contents'] or ''
            ]
            rows.append(row_info)
        return rows


    @classmethod
    def get_single_city(cls, wb, ws, data_file, province_name='北京',
            province_code=110000, city_name='北京市', city_code=110100,
            yesterday_data=None, write=True, pause_event=None, is_running=None, stop=None):
        """采集单个城市，write=False时仅返回数据不写入。
        pause_event: threading.Event，暂停时 wait() 阻塞；is_running: 返回布尔，False 停止。"""
        all_rows = []
        page_count = 20  # 每页数量，与API page_size一致
        pages = 20  # 最大页数
        # 去重集合：整行(不含采集日期)作键；采集到一条就加入，避免本次分页重叠重复
        seen = set(tuple(r) for r in (yesterday_data or []))
        for page_id in range(1, pages + 1):
            if pause_event is not None:
                pause_event.wait()          # 暂停时在这里阻塞
            if is_running is not None and not is_running():
                break
            if stop and stop():
                break
            page_info = cls.get_page_info(page_id=page_id, province_name=province_name, province_code=province_code,
                                          city_name=city_name, city_code=city_code)
            if isinstance(page_info, bool):
                continue
            elif not page_info:
                logger.info(f'【{cls.web_name}】{province_name} - {city_name} 第{page_id}页共采集0条数据')
                break

            parsed = cls.parser_page_info(province_name=province_name, city_name=city_name, page_info=page_info)
            count = 0
            for row_info in parsed:
                key = tuple(row_info[1:])
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                all_rows.append(row_info)
                if write:
                    ws.append(row_info)
            if write:
                wb.save(data_file)

            logger.info(f'【{cls.web_name}】{province_name}-{city_name} 第{page_id}页共采集{count}条有效数据')
            if len(parsed) < page_count:
                break
        return all_rows

    @classmethod
    def run(cls, data_file='国聘数据.xlsx'):
        # 设置xlsx样式
        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)
        # 省份数据
        province_info = cls.area_codes.get('provinces')
        # 城市数据
        citys_info = cls.area_codes.get('cities')

        for province_code, city_info in citys_info.items():
            # 遍历省份
            province_name = province_info.get(province_code)
            for city_name, city_code in city_info.items():
                # 遍历城市
                # if province_name != '辽宁' or city_name != '大连市':
                #     continue
                args = [wb, ws, data_file, province_name, province_code, city_name, city_code, yesterday_data]
                # 单个城市采集
                logger.info(f'开始采集【{cls.web_name}{province_name}-{city_name}】[{province_code}.{city_code}]')
                cls.get_single_city(*args)


class ZhiPin(object):
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

    # 四川 21 市 + 重庆（省份, 城市）
    SC_CITIES = [("四川", n) for n in [
        "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁",
        "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安",
        "巴中", "资阳", "阿坝", "甘孜", "凉山"]]
    CITY_ID = {"成都": 801, "自贡": 802, "攀枝花": 803, "泸州": 804, "德阳": 805,
               "绵阳": 806, "广元": 807, "遂宁": 808, "内江": 809, "乐山": 810,
               "南充": 811, "眉山": 812, "宜宾": 813, "广安": 814, "达州": 815,
               "雅安": 816, "巴中": 817, "资阳": 818, "阿坝": 819, "甘孜": 820,
               "凉山": 821, "重庆": 551}
    CITY_FULL = {n: n + "市" for n in CITY_ID}
    CITY_FULL.update({"阿坝": "阿坝藏族羌族自治州", "甘孜": "甘孜藏族自治州",
                      "凉山": "凉山彝族自治州", "重庆": "重庆市"})

    # 页面 / 抓取参数（越大越容易触发风控，可按需调整）
    DEFAULT_PAGE_SIZE = 20            # 每页条数（与接口 pageSize 一致）
    DEFAULT_PAGES = 100000            # 安全上限；实际循环靠“空页/末页”自动结束，即有多少爬多少
    DEFAULT_DELAY = 0.8               # 每页间隔秒数

    # Chrome 登录态目录（兼顾源码运行与打包后的 exe）
    # 打包后 __file__ 位于临时解压目录(_MEIPASS)，不可用；改为以 exe 所在目录为基准，
    # 这样 zp_profile 就放在 exe 旁边，登录态可跨次运行持久化。
    if getattr(sys, 'frozen', False):
        _base = os.path.dirname(sys.executable)
    else:
        _base = os.path.dirname(os.path.abspath(__file__))
    _profile_candidates = [
        os.path.join(_base, "zp_profile"),
        os.path.join(_base, "..", "jobspider", "zp_profile"),
    ]
    PROFILE_DEFAULT = next((p for p in _profile_candidates if os.path.isdir(p)),
                           _profile_candidates[0])

    # 类级浏览器/事件循环状态（懒加载，供同步方法复用）
    _loop = None
    _thread = None
    _pw = None
    _context = None
    _page = None

    # ==================== 与 GuoPin 一致的公共方法 ====================

    @classmethod
    def load_yesterday_data(cls, data_file):
        """读取昨天/今天已入库的数据，用于去重。"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        all_data = _read_xlsx_rows(data_file)
        yesterday_data = []
        for row in all_data:
            date_val = str(row[0]).split(' ')[0]
            if date_val not in (yesterday, today):
                continue
            yesterday_data.append(row[1:])
        return yesterday_data

    @classmethod
    def set_column_style(cls, data_file):
        """设置表头样式（与 GuoPin 一致）。"""
        xlsx_headers = XLSX_HEADERS

        wb = load_workbook(filename=data_file) if os.path.exists(data_file) else Workbook()
        ws = wb.active
        ws.title = "职位数据"
        ws.freeze_panes = 'A2'

        HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
        THIN_BORDER = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        for col, header in enumerate(xlsx_headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = THIN_BORDER
        wb.save(data_file)
        return wb, ws

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

    @staticmethod
    def item_to_row(it, prov, city):
        """把接口返回的单条岗位数据整理成字段字典（不含采集日期/省份）。"""
        jd = it.get("jobDetailData") or {}
        pb = ((jd.get("position") or {}).get("base")) or {}
        dt = ((jd.get("position") or {}).get("date")) or {}
        de = ((jd.get("position") or {}).get("desc")) or {}
        jt = ((jd.get("position") or {}).get("jobType")) or {}
        city_full = ZhiPin.CITY_FULL[city]
        district = it.get("cityDistrict") or ""
        work_place = ("%s-%s" % (it.get("workCity") or city, district)) if district \
            else (it.get("workCity") or city)
        edu = it.get("education") or pb.get("education") or "不限"
        exp = it.get("workingExp") or pb.get("positionWorkingExp") or "不限"
        salary = it.get("salaryReal") or pb.get("salaryReal") or ""
        m = re.match(r"\s*(\d+)\s*[-~至]\s*(\d+)", str(salary))
        if m:
            salary_text = "%s~%s 元/月" % (int(m.group(1)), int(m.group(2)))
        else:
            salary_text = it.get("salary60") or pb.get("salary") or "0~0 元/月"
        work_type = it.get("workType") or pb.get("workType") or ""
        if work_type == "兼职":
            nature = "兼职"
        elif (it.get("internshipMonths") or 0) > 0 or "实习" in work_type:
            nature = "实习"
        else:
            nature = "不限"
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
            "公司名称": it.get("companyName") or "",
            "公司性质": it.get("propertyName") or it.get("property") or "不限",
            "公司规模": it.get("companySize") or "不限",
            "公司行业": it.get("industryName") or "不限",
            "招聘类型": "不限",
            "职位性质": nature,
            "职位类别": cat,
            "薪资范围": salary_text,
            "招聘人数": recruit_text,
            "学历要求": edu,
            "经验要求": exp,
            "专业要求": "不限",
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
        try:
            j = cls._submit(cls._fetch_positions_async(city_name, page_id), timeout=60)
            if j is None:
                return None
            return (j.get("data") or {}).get("list") or []
        except Exception as e:
            logger.error('【%s】第%d页请求异常：%s' % (city_name, page_id, e))
            return None

    # ==================== 解析 ====================

    @classmethod
    def parser_page_info(cls, province_name, city_name, page_info):
        """把单页岗位列表解析为 xlsx 行；返回 [[采集日期,省份,城市,...], ...]。"""
        order = ["城市", "职位名称", "公司名称", "公司性质", "公司规模", "公司行业",
                 "招聘类型", "职位性质", "职位类别", "薪资范围", "招聘人数",
                 "学历要求", "经验要求", "专业要求", "工作地点", "详细地址",
                 "报名截止", "职位描述"]
        rows = []
        crawl_date = datetime.now().strftime('%Y-%m-%d')
        for it in (page_info or []):
            d = cls.item_to_row(it, province_name, city_name)
            rows.append([crawl_date, cls.web_name, province_name] + [d.get(k, '') for k in order])
        return rows

    # ==================== 城市范围 ====================

    @classmethod
    def target_cities(cls, scope='all'):
        if scope == "cq":
            return [("重庆", "重庆")]
        if scope == "sc":
            return list(cls.SC_CITIES)
        if scope == "all":
            return list(cls.SC_CITIES) + [("重庆", "重庆")]
        prov_of = {n: p for p, n in cls.SC_CITIES}
        prov_of["重庆"] = "重庆"
        return [(prov_of[n], n) for n in
                [x.strip() for x in str(scope).split(",") if x.strip()] if n in prov_of]

    # ==================== 单城市采集 ====================

    @classmethod
    def get_single_city(cls, wb=None, ws=None, data_file=None, province_name='四川',
                        city_name='成都', yesterday_data=None, write=True,
                        stop=None, pause_event=None, is_running=None, on_data=None):
        """采集单个城市，write=False 时仅返回数据不写入。返回本城市新增行。
        pause_event: threading.Event，暂停时 wait() 阻塞；is_running: 返回布尔，False 停止。
        on_data(row): 每采集到一条新数据立即回调，用于 GUI 实时刷新。"""
        all_rows = []
        page_count = cls.DEFAULT_PAGE_SIZE
        pages = cls.DEFAULT_PAGES
        # 去重集合：整行(不含采集日期)作键；采集到一条就加入，避免本次分页重叠重复
        seen = set(tuple(r) for r in (yesterday_data or []))
        for page_id in range(1, pages + 1):
            if pause_event is not None:
                pause_event.wait()          # 暂停时在这里阻塞
            if is_running is not None and not is_running():
                logger.info('【智联招聘】用户终止采集')
                break
            if stop and stop():
                logger.info('【智联招聘】用户终止采集')
                break
            page_list = cls.get_page_info(page_id=page_id, province_name=province_name,
                                          city_name=city_name)
            if page_list is None:
                logger.info('【智联招聘】%s-%s 第%d页请求失败，暂停5s重试'
                            % (province_name, city_name, page_id))
                time.sleep(5)
                page_list = cls.get_page_info(page_id=page_id, province_name=province_name,
                                              city_name=city_name)
                if page_list is None:
                    break
            if not page_list:
                break

            parsed = cls.parser_page_info(province_name, city_name, page_list)
            count = 0
            for row_info in parsed:
                key = tuple(row_info[1:])
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                all_rows.append(row_info)
                if write and ws is not None:
                    ws.append(row_info)
                if on_data is not None:
                    on_data(row_info)
            if write and wb is not None and data_file is not None:
                wb.save(data_file)
            logger.info('【智联招聘】%s-%s 第%d页 采集%d条有效数据'
                        % (province_name, city_name, page_id, count))
            if len(parsed) < page_count:
                break
            time.sleep(cls.DEFAULT_DELAY)
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

    @classmethod
    async def _launch_async(cls, profile):
        if cls._page is not None:
            return cls._page
        cls._pw = await async_playwright().start()
        # 默认使用 Playwright 自带的 Chromium（随包打包，无需系统 Chrome）；
        # 如需强制系统 Chrome，设置环境变量 PLAYWRIGHT_CHANNEL=chrome。
        launch_kwargs = dict(headless=False, locale="zh-CN",
                             viewport={"width": 1360, "height": 900})
        channel = (os.environ.get('PLAYWRIGHT_CHANNEL') or '').strip()
        if channel:
            launch_kwargs['channel'] = channel
        logger.info('【智联招聘】启动浏览器（channel=%s）' % (channel or 'bundled-chromium'))
        cls._context = await cls._pw.chromium.launch_persistent_context(profile, **launch_kwargs)
        cls._page = cls._context.pages[0] if cls._context.pages else await cls._context.new_page()
        return cls._page

    @classmethod
    def launch(cls, profile=None):
        profile = profile or cls.PROFILE_DEFAULT
        logger.info('【智联招聘】启动 Chrome（登录态目录：%s）' % profile)
        return cls._submit(cls._launch_async(profile), timeout=120)

    @classmethod
    async def _close_async(cls):
        try:
            if cls._context is not None:
                await cls._context.close()
        except Exception:
            pass
        if cls._pw is not None:
            try:
                await cls._pw.stop()
            except Exception:
                pass
        cls._page = cls._context = cls._pw = None

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
        else:
            logger.info('[登录] 警告：未能确认登录成功。请检查浏览器窗口，可能需要重新获取验证码。')
        await cls._page.wait_for_timeout(3000)
        return confirmed

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
    def run(cls, data_file='智联数据.xlsx', phone='', force=False, scope='all',
            profile=None, delay=None, max_pages=None, ask=input,
            pause_event=None, is_running=None,
            on_progress=None, on_data=None, on_city_done=None,
            on_complete=None, on_error=None):
        """采集入口：登录 -> 逐城市采集 -> 增量写入 xlsx。
        pause_event: threading.Event（暂停时阻塞）；is_running: lambda 返回布尔，False 停止。
        on_progress(current, total, city) / on_data(row) / on_city_done(city)
        on_complete(msg) / on_error(msg)；供 GUI 展示进度与数据。"""
        profile = profile or cls.PROFILE_DEFAULT
        if delay is not None:
            cls.DEFAULT_DELAY = delay
        if max_pages is not None:
            cls.DEFAULT_PAGES = max_pages

        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)

        try:
            cls.launch(profile)
            if not cls.login(phone=phone, force=force, ask=ask):
                logger.error('【智联招聘】登录未确认成功，停止采集。')
                if on_complete:
                    on_complete('登录未确认成功，已停止')
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
            for prov, city in cities:
                if pause_event is not None:
                    pause_event.wait()
                if is_running is not None and not is_running():
                    logger.info('【智联招聘】用户终止采集')
                    stopped = True
                    break
                logger.info('开始采集【智联招聘%s-%s】' % (prov, city))
                try:
                    rows = cls.get_single_city(wb, ws, data_file, prov, city,
                                               yesterday_data, write=True,
                                               pause_event=pause_event,
                                               is_running=is_running,
                                               on_data=on_data)
                    if on_progress:
                        on_progress(prov, city, len(rows))
                    if on_city_done:
                        on_city_done(city)
                except Exception as e:
                    logger.error('【智联招聘】%s-%s 采集异常：%s' % (prov, city, e))
                    if on_error:
                        on_error('%s-%s: %s' % (prov, city, e))
                time.sleep(cls.DEFAULT_DELAY)
            if on_complete:
                on_complete('智联招聘采集已停止' if stopped else '智联招聘采集完成')
        finally:
            cls.close()


# ==================== 可视化界面 ====================
class BaseSpiderGUI:
    """爬虫可视化基类（通用界面，供子类复用以实现具体爬虫）。
    提供：开始/暂停/停止、进度条、数据表格、分页、每秒定时刷新表格。
    子类只需实现 spider_task()；采集中通过 on_data()/on_progress() 回调刷新界面。"""

    def __init__(self, title='数据采集系统', spider_name='', parent=None):
        # 主窗口；parent 为空则自身新建窗口，否则嵌入到 parent(容器Frame)中复用
        if parent is None:
            self.root = tk.Tk()
            self.root.title(title)
            self.root.geometry('960x640')
            self.root.minsize(800, 500)
            self._owns_root = True
            self.container = self.root
        else:
            self.root = parent.winfo_toplevel()
            self._owns_root = False
            self.container = parent

        self.spider_name = spider_name
        # 运行状态控制
        self.is_running = False
        self.is_paused = False
        self.pause_event = threading.Event()   # 置位=运行，清空=暂停（爬虫在循环里 wait 该事件）
        self.pause_event.set()
        self.spider_thread = None             # 后台采集线程

        # 统计信息
        self.total_count = 0
        self.today_count = 0
        self.error_count = 0
        self.current_city = ''
        self.start_time = None

        # 表格数据（内存中全量数据 + 分页）
        self.all_rows = []
        self.page_size = 100
        self.current_page = 0
        self._refresh_pending = False         # 是否有待刷新的数据
        self._refresh_timer_id = None         # 定时刷新任务 ID

        self._build_ui()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        self._build_header()
        self._build_control_panel()
        self._build_table()
        self._build_pagination()
        self._build_status_bar()

    def _build_header(self):
        header = tk.Frame(self.container, bg='#2c3e50', height=50)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text=f'📊 {self.spider_name}数据采集',
                 bg='#2c3e50', fg='white', font=('微软雅黑', 14, 'bold')).pack(side='left', padx=15)
        self.lbl_time = tk.Label(header, text='', bg='#2c3e50', fg='#ecf0f1', font=('微软雅黑', 9))
        self.lbl_time.pack(side='right', padx=15)
        self._update_clock()

    def _build_control_panel(self):
        frame = tk.LabelFrame(self.container, text=' 控制面板 ', font=('微软雅黑', 10, 'bold'), padx=10, pady=8)
        frame.pack(fill='x', padx=10, pady=(10, 5))

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill='x')

        self.btn_start = tk.Button(btn_frame, text='▶ 开始采集', width=12, bg='#27ae60', fg='white',
                                   font=('微软雅黑', 10, 'bold'), command=self._on_start)
        self.btn_start.pack(side='left', padx=(0, 8))

        self.btn_pause = tk.Button(btn_frame, text='⏸ 暂停', width=10, bg='#f39c12', fg='white',
                                   font=('微软雅黑', 10, 'bold'), command=self._on_pause, state='disabled')
        self.btn_pause.pack(side='left', padx=(0, 8))

        self.btn_stop = tk.Button(btn_frame, text='⏹ 停止', width=10, bg='#e74c3c', fg='white',
                                  font=('微软雅黑', 10, 'bold'), command=self._on_stop, state='disabled')
        self.btn_stop.pack(side='left')

        self.btn_refresh = tk.Button(btn_frame, text='🔄 刷新列表', width=12, bg='#8e44ad', fg='white',
                                     font=('微软雅黑', 10, 'bold'), command=self._on_refresh)
        self.btn_refresh.pack(side='left', padx=(8, 0))

        progress_frame = tk.Frame(frame)
        progress_frame.pack(fill='x', pady=(8, 0))

        self.progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=(0, 10))

        self.lbl_progress = tk.Label(progress_frame, text='0%', font=('微软雅黑', 9), width=6)
        self.lbl_progress.pack(side='right')

        status_frame = tk.Frame(frame)
        status_frame.pack(fill='x', pady=(5, 0))

        self.lbl_status = tk.Label(status_frame, text='就绪', font=('微软雅黑', 9), fg='#7f8c8d', anchor='w')
        self.lbl_status.pack(side='left', fill='x', expand=True)

        self.lbl_stats = tk.Label(status_frame, text='', font=('微软雅黑', 9), fg='#2c3e50')
        self.lbl_stats.pack(side='right')

    def _build_table(self):
        table_frame = tk.Frame(self.container)
        table_frame.pack(fill='both', expand=True, padx=10, pady=(5, 5))

        columns = ('id', 'date', 'source', 'province', 'city', 'job_name', 'company_name', 'nature', 'scale',
                   'industry', 'recruit_type', 'job_type', 'category', 'salary',
                   'amount', 'education', 'experience', 'major', 'location',
                   'address', 'deadline', 'description')
        headings = ('ID', '采集日期', '来源', '省份', '城市', '职位名称', '公司名称', '公司性质', '公司规模',
                    '公司行业', '招聘类型', '职位性质', '职位类别', '薪资范围',
                    '招聘人数', '学历要求', '经验要求', '专业要求', '工作地点',
                    '详细地址', '报名截止', '职位描述')

        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=18)
        self.tree.heading('#0', text='')
        self.tree.column('#0', width=0, stretch=False)

        widths = [50, 80, 60, 60, 70, 160, 200, 60, 80, 140, 70, 50, 100, 110,
                  50, 60, 60, 180, 90, 180, 130, 250]
        for col, heading, w in zip(columns, headings, widths):
            self.tree.heading(col, text=heading, anchor='w')
            self.tree.column(col, width=w, minwidth=40, anchor='w')

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind('<MouseWheel>', lambda e: self.tree.yview_scroll(int(-1 * (e.delta / 120)), 'units'))

    def _build_pagination(self):
        frame = tk.Frame(self.container)
        frame.pack(fill='x', padx=10, pady=(0, 5))

        self.btn_prev = tk.Button(frame, text='< 上一页', width=10, state='disabled',
                                  command=self._on_prev_page)
        self.btn_prev.pack(side='left')

        self.lbl_page = tk.Label(frame, text='第 0/0 页  共 0 条', font=('微软雅黑', 9))
        self.lbl_page.pack(side='left', expand=True)

        self.btn_next = tk.Button(frame, text='下一页 >', width=10, state='disabled',
                                  command=self._on_next_page)
        self.btn_next.pack(side='right')

    def _on_prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_table()

    def _on_next_page(self):
        max_page = (len(self.all_rows) - 1) // self.page_size
        if self.current_page < max_page:
            self.current_page += 1
            self._refresh_table()

    def _do_refresh(self):
        """刷新数据表格并清除“待刷新”标记。"""
        self._refresh_pending = False
        self._refresh_table()

    def _schedule_refresh_timer(self):
        """启动每秒一次的表格刷新定时器（避免多次重复创建）。"""
        if self._refresh_timer_id is not None:
            self.root.after_cancel(self._refresh_timer_id)
        self._refresh_timer_id = self.root.after(1000, self._on_periodic_tick)

    def _on_periodic_tick(self):
        """每秒回调：有新数据就刷新表格；运行中则继续排程下一次刷新。"""
        if self._refresh_pending:
            self._do_refresh()
        if self.is_running:
            self._refresh_timer_id = self.root.after(1000, self._on_periodic_tick)
        else:
            self._refresh_timer_id = None

    def _refresh_table(self):
        """按当前分页刷新表格内容（清空重绘当前页）。"""
        self.tree.delete(*self.tree.get_children())
        start = self.current_page * self.page_size
        end = start + self.page_size
        page_data = self.all_rows[start:end]
        for i, row in enumerate(page_data, start=start + 1):
            values = (str(i),) + tuple(str(v) if v is not None else '' for v in row)
            self.tree.insert('', 'end', values=values)
        total_pages = max(1, (len(self.all_rows) - 1) // self.page_size + 1)
        self.lbl_page.config(text=f'第 {self.current_page + 1}/{total_pages} 页  共 {len(self.all_rows)} 条')
        self.btn_prev.config(state='normal' if self.current_page > 0 else 'disabled')
        self.btn_next.config(state='normal' if self.current_page < total_pages - 1 else 'disabled')

    def _build_status_bar(self):
        bar = tk.Frame(self.container, bg='#ecf0f1', height=24)
        bar.pack(fill='x', side='bottom')
        bar.pack_propagate(False)
        self.lbl_bottom = tk.Label(bar, text='就绪', bg='#ecf0f1', fg='#7f8c8d',
                                   font=('微软雅黑', 8), anchor='w')
        self.lbl_bottom.pack(side='left', padx=10)

    # ==================== 时钟 ====================

    def _update_clock(self):
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        self.lbl_time.config(text=now)
        self.root.after(1000, self._update_clock)

    # ==================== 按钮事件 ====================

    def _on_start(self):
        if self.is_running and not self.is_paused:
            return
        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            self.btn_pause.config(text='⏸ 暂停', bg='#f39c12')
            self._set_status('继续采集中...')
            return

        self.is_running = True
        self.is_paused = False
        self.total_count = 0
        self.today_count = 0
        self.error_count = 0
        self.start_time = time.time()

        # 切换平台/重新抓取时清空上一批数据
        self.all_rows = []
        self.current_page = 0
        self._refresh_table()
        self.tree.delete(*self.tree.get_children())

        self.btn_start.config(state='disabled')
        self.btn_pause.config(state='normal')
        self.btn_stop.config(state='normal')

        self._set_status('正在准备 %s 采集...' % self.spider_name)
        self._schedule_refresh_timer()
        self.spider_thread = threading.Thread(target=self.spider_task, daemon=True)
        self.spider_thread.start()

    def _on_pause(self):
        if not self.is_running:
            return
        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            self.btn_pause.config(text='⏸ 暂停', bg='#f39c12')
            self._set_status('继续采集中...')
        else:
            self.is_paused = True
            self.pause_event.clear()
            self.btn_pause.config(text='▶ 继续', bg='#3498db')
            self._set_status('已暂停')

    def _on_stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.is_paused = False
        self.pause_event.set()
        if self._refresh_timer_id is not None:
            self.root.after_cancel(self._refresh_timer_id)
            self._refresh_timer_id = None
        self.btn_start.config(state='normal')
        self.btn_pause.config(state='disabled', text='⏸ 暂停', bg='#f39c12')
        self.btn_stop.config(state='disabled')
        self._set_status('已停止')
        self._do_refresh()

    # ==================== 爬虫回调 ====================

    def on_progress(self, current, total, city=''):
        # 跨线程更新控件：必须通过 root.after 调度回主线程，避免 Tkinter 线程安全问题
        def _update():
            self.total_count = current
            pct = int(current / total * 100) if total > 0 else 0
            self.progress['value'] = pct
            self.lbl_progress.config(text=f'{pct}%')
            self.current_city = city
            elapsed = time.time() - self.start_time if self.start_time else 0
            self.lbl_stats.config(text=f'已采集: {self.today_count} | 错误: {self.error_count} | 耗时: {elapsed:.0f}s')
            self._set_status(f'正在采集: {city} ({current}/{total})')
            self.lbl_bottom.config(text=f'当前: {city} | 进度: {current}/{total}')
        self.root.after(0, _update)

    def on_complete(self, msg='采集完成'):
        self.is_running = False
        self.is_paused = False
        if self._refresh_timer_id is not None:
            self.root.after_cancel(self._refresh_timer_id)
            self._refresh_timer_id = None
        self.root.after(0, lambda: self.btn_start.config(state='normal'))
        self.root.after(0, lambda: self.btn_pause.config(state='disabled', text='⏸ 暂停', bg='#f39c12'))
        self.root.after(0, lambda: self.btn_stop.config(state='disabled'))
        self.root.after(0, lambda: self._set_status(msg))
        self.root.after(0, lambda: self.progress.config(value=100))
        self.root.after(0, lambda: self.lbl_progress.config(text='100%'))
        self.root.after(0, self._do_refresh)

    def on_error(self, msg):
        self.error_count += 1
        self.root.after(0, lambda: self._set_status(f'错误: {msg}'))

    def on_data(self, row):
        self.today_count += 1
        self.all_rows.append(row)
        if not self._refresh_pending:
            self._refresh_pending = True
            self.root.after(200, self._do_refresh)

    def check_pause(self):
        self.pause_event.wait()

    def _insert_row(self, row):
        row_id = len(self.tree.get_children()) + 1
        values = (str(row_id),) + tuple(str(v) if v is not None else '' for v in row)
        self.tree.insert('', 'end', values=values)
        self.tree.yview_moveto(1.0)

    def _set_status(self, text):
        self.lbl_status.config(text=text)

    def default_data_file(self):
        """当前爬虫使用的数据文件（子类可覆盖）。"""
        return None

    def _on_refresh(self):
        """手动刷新：从数据文件重新读取并刷新表格。"""
        f = self.default_data_file() or \
            simpledialog.askstring('刷新列表', '输入数据文件路径（取消则退出）:', parent=self.root)
        if not f:
            return
        if not os.path.exists(f):
            self._set_status('文件不存在: %s' % f)
            return
        try:
            rows = _read_xlsx_rows(f)
            header = XLSX_HEADERS
            data = []
            for r in rows:
                # 跳过表头行与空行
                if not r or (len(r) > 0 and str(r[0]) == str(header[0])):
                    continue
                data.append(tuple(r))
            self.all_rows = data
            self.current_page = 0
            self._refresh_table()
            self.lbl_bottom.config(text='已刷新 %s，共 %d 条' % (os.path.basename(f), len(data)))
            self._set_status('刷新完成，共 %d 条' % len(data))
        except Exception as e:
            self._set_status('刷新失败: %s' % e)

    def spider_task(self):
        raise NotImplementedError('子类必须实现 spider_task 方法')

    def run(self):
        if self._owns_root:
            self.root.mainloop()


class GuoPinGUI(BaseSpiderGUI):
    """国聘采集可视化界面"""

    def __init__(self):
        super().__init__(title='国聘数据采集系统', spider_name='国聘')

    def spider_task(self, data_file='国聘数据.xlsx'):
        spider = GuoPin()
        province_info = spider.area_codes.get('provinces')
        citys_info = spider.area_codes.get('cities')

        total_cities = sum(len(c) for c in citys_info.values())
        done_cities = 0

        wb, ws = spider.set_column_style(data_file)
        yesterday_data = spider.load_yesterday_data(data_file)

        for province_code, city_info in citys_info.items():
            if not self.is_running:
                break

            province_name = province_info.get(province_code, '')

            for city_name, city_code in city_info.items():
                if not self.is_running:
                    break

                self.check_pause()
                city_label = f'{province_name}-{city_name}'
                self.on_progress(done_cities, total_cities, city_label)

                try:
                    rows = spider.get_single_city(
                        wb, ws, data_file,
                        province_name, province_code,
                        city_name, city_code,
                        yesterday_data, write=True,
                        pause_event=self.pause_event,
                        is_running=lambda: self.is_running,
                        stop=lambda: not self.is_running,
                    )
                    for row in rows:
                        self.on_data(row)
                    done_cities += 1
                except Exception as e:
                    self.on_error(f'{city_label}: {e}')
                    done_cities += 1

        self.on_complete('国聘采集完成')


class ZhilianPanel(BaseSpiderGUI):
    """智联招聘采集面板（独立页签）。"""

    def __init__(self, master):
        container = tk.Frame(master)
        super().__init__(title='', spider_name='智联招聘', parent=container)

    def default_data_file(self):
        return '智联数据.xlsx'

    # 线程安全弹窗输入（智联登录手机号/验证码）
    def _ask(self, prompt):
        res = {}
        evt = threading.Event()

        def _dialog():
            res['v'] = simpledialog.askstring('智联登录', prompt, parent=self.root)
            evt.set()

        self.root.after(0, _dialog)
        evt.wait()
        return (res.get('v') or '').strip()

    def spider_task(self, data_file=None):
        self._run_zhilian(data_file or self.default_data_file())

    def _run_zhilian(self, data_file='智联数据.xlsx'):
        def _on_progress(prov, city, added):
            # 线程安全：控件更新通过 root.after 回到主线程执行
            def _u():
                self._set_status('正在采集: %s-%s (新增 %d)' % (prov, city, added))
                self.lbl_bottom.config(text='当前: %s-%s | 新增: %d' % (prov, city, added))
            self.root.after(0, _u)

        try:
            ZhiPin.run(data_file,
                       ask=self._ask,
                       pause_event=self.pause_event,
                       is_running=lambda: self.is_running,
                       on_progress=_on_progress,
                       on_data=self.on_data,
                       on_complete=self.on_complete,
                       on_error=self.on_error)
        except Exception as e:
            logger.error('智联招聘采集异常：%s' % e)
            self.on_error('智联招聘: %s' % e)
            self.on_complete('智联招聘异常结束')


class GuopinPanel(BaseSpiderGUI):
    """国聘采集面板（独立页签）。"""

    def __init__(self, master):
        container = tk.Frame(master)
        super().__init__(title='', spider_name='国聘', parent=container)

    def default_data_file(self):
        return '国聘数据.xlsx'

    def spider_task(self, data_file=None):
        data_file = data_file or self.default_data_file()
        spider = GuoPin()
        province_info = spider.area_codes.get('provinces')
        citys_info = spider.area_codes.get('cities')

        total_cities = sum(len(c) for c in citys_info.values())
        done_cities = 0

        wb, ws = spider.set_column_style(data_file)
        yesterday_data = spider.load_yesterday_data(data_file)

        for province_code, city_info in citys_info.items():
            if not self.is_running:
                break

            province_name = province_info.get(province_code, '')

            for city_name, city_code in city_info.items():
                if not self.is_running:
                    break

                self.check_pause()
                city_label = f'{province_name}-{city_name}'
                self.on_progress(done_cities, total_cities, city_label)

                try:
                    rows = spider.get_single_city(
                        wb, ws, data_file,
                        province_name, province_code,
                        city_name, city_code,
                        yesterday_data, write=True,
                        pause_event=self.pause_event,
                        is_running=lambda: self.is_running,
                        stop=lambda: not self.is_running,
                    )
                    for row in rows:
                        self.on_data(row)
                    done_cities += 1
                except Exception as e:
                    self.on_error(f'{city_label}: {e}')
                    done_cities += 1

        self.on_complete('国聘采集完成')


class SpiderGUI:
    """主窗口：两个页签（智联招聘 / 国聘），各自独立开始采集、各自独立数据展示。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('数据采集系统')
        self.root.geometry('1080x700')
        self.root.minsize(900, 560)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=8, pady=8)

        self.tab_zhi = ZhilianPanel(self.root)
        self.tab_gp = GuopinPanel(self.root)
        self.notebook.add(self.tab_zhi.container, text=' 智联招聘 ')
        self.notebook.add(self.tab_gp.container, text=' 国聘 ')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    SpiderGUI().run()
