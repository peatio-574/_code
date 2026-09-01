# coding='utf-8'
import json
import requests
from Logger import logger
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
import time
import os
from ReadFile import ReadData


def parse_area_codes(file_path):
    """解析国聘省份codes"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    result = {"provinces": {}, "cities": {}}
    china = data['data'][0]
    for province in china.get('children', []):
        result["provinces"][province['value']] = province['label']
        result["cities"][province['value']] = {}
        for city in province.get('children', []):
            result["cities"][province['value']][city['name']] = city['value']
    return result


class GuoPin(object):
    # 网站名称
    web_name = '国聘'
    # 区域json
    area_codes = parse_area_codes('data.json')


    @classmethod
    def load_yesterday_data(cls, data_file):
        """读取昨天数据"""
        yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
        all_data = ReadData.read_xlsx_row(data_file, row_type='list')
        yesterday_data = []
        for row in all_data:
            if str(row[0]) != str(yesterday):
                break
            yesterday_data.append(row[1:])
        return yesterday_data


    @classmethod
    def set_column_style(cls, data_file):
        """设置表头格式"""
        xlsx_headers = [
            '采集日期', '省份', '城市',
            "职位名称", "公司名称", "公司性质", "公司规模", "公司行业",
            "招聘类型", "职位性质", "职位类别", "薪资范围", "招聘人数",
            "学历要求", "经验要求", "专业要求", "工作地点", "详细地址",
            "报名截止", "职位描述"
        ]

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
                    "page_size": 40,
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
        print(page_info)
        for row in page_info:
            job_name = row['job_name']
            company_name = row['company_name']
            row_info = [
                str(time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))),
                province_name,
                city_name,
                job_name,
                company_name,
                row['company_info']['nature_cn'],
                row['company_info']['scale_cn'],
                row['company_info'].get('industry_cn'),
                row['recruitment_type_cn'],
                row['nature_cn'],
                row['category_cn'],
                f"{row['min_wage']}~{row['max_wage']} {row['wage_unit_cn']}",
                row['amount'] if row['amount'] > 0 else '若干',
                row['education_cn'],
                row['experience_cn'],
                ', '.join(row.get('major_cn', [])),
                row['district_list'][0]['area_cn'] if row.get('district_list') else '',
                row['district_list'][0].get('address', '') if row.get('district_list') else '',
                row['end_time'],
                row['contents']
            ]
            rows.append(row_info)
        return rows


    @classmethod
    def get_single_city(cls, wb, ws, data_file, province_name='北京',
            province_code=110000, city_name='北京市', city_code=110100, yesterday_data=None):
        """采集单个城市"""
        page_count = 20  # 每页数量
        pages = 20  # 页数
        for page_id in range(1, pages + 1):
            page_info = cls.get_page_info(page_id=page_id, province_name=province_name, province_code=province_code,
                                          city_name=city_name, city_code=city_code)
            if isinstance(page_info, bool):   # 请求异常，继续
                continue
            elif not page_info:  # 数据量为0，暂停循环
                logger.info(f'【{cls.web_name}】{province_name} - {city_name} 第{page_id}页共采集0条数据')
                break

            # 解析数据
            page_info = cls.parser_page_info(province_name=province_name, city_name=city_name, page_info=page_info)
            count = 0
            for row_info in page_info:
                if row_info[1:] in yesterday_data:
                    continue
                count += 1
                ws.append(row_info)
            wb.save(data_file)

            logger.info(f'【{cls.web_name}】{province_name}-{city_name} 第{page_id}页共采集{count}条有效数据')
            if len(page_info) <= page_count:  # 最后一页，暂停
                break


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
                if province_name != '辽宁' or city_name != '大连市':
                    continue
                args = [wb, ws, data_file, province_name, province_code, city_name, city_code, yesterday_data]
                # 单个城市采集
                logger.info(f'开始采集【{cls.web_name}{province_name}-{city_name}】[{province_code}.{city_code}]')
                cls.get_single_city(*args)


if __name__ == '__main__':
    GuoPin.run()
    # data = parse_area_codes('data.json')
    # print(data)