# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import os
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill

sys.path.append(str(Path(__file__).parent.parent))

from PlayWright import Playwright_, logger


def extract_jd_data(input_file, output_file):
    """
    读取xlsx所有sheet页，提取商品标准名称、京东零售价金额、链接三个字段
    并保存至新的xlsx，保持sheet名称一致
    """
    try:
        # 读取Excel文件的所有sheet名称
        excel_file = pd.ExcelFile(input_file)
        sheet_names = excel_file.sheet_names

        logger.info(f'共找到 {len(sheet_names)} 个sheet页: {sheet_names}')

        # 创建ExcelWriter用于写入新文件
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:

            for sheet_name in sheet_names:
                logger.info(f'正在处理sheet: {sheet_name}')

                # 读取当前sheet
                df = pd.read_excel(input_file, sheet_name=sheet_name)

                # 查找目标列（支持模糊匹配）
                target_columns = []
                for col in df.columns:
                    col_str = str(col).strip()
                    if '商品标准名称' in col_str or '商品名称' in col_str:
                        target_columns.append(('商品标准名称', col))
                    elif '京东零售价金额' in col_str:
                        target_columns.append(('京东零售价金额', col))
                    elif '链接' in col_str or 'url' in col_str.lower():
                        target_columns.append(('链接', col))

                # 检查是否包含所有必需字段
                if len(target_columns) < 3:
                    logger.warning(f'Sheet "{sheet_name}" 缺少必要字段，跳过此sheet')
                    # 如果第一个sheet没有这三个字段，直接跳过
                    if sheet_name == sheet_names[0]:
                        logger.info(f'第一个sheet "{sheet_name}" 缺少字段，已跳过')
                        continue
                    else:
                        continue

                # 构建新的DataFrame，只保留需要的列
                new_columns = [tc[1] for tc in target_columns]
                new_df = df[new_columns].copy()

                # 重命名列
                column_mapping = {tc[1]: tc[0] for tc in target_columns}
                new_df.rename(columns=column_mapping, inplace=True)

                # 去除空值行（可选）
                new_df.dropna(how='all', inplace=True)

                # 写入新Excel文件
                new_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # 设置表头样式
                ws = writer.sheets[sheet_name]
                header_font = Font(bold=True, color='FFFFFF', size=11)
                header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
                header_alignment = Alignment(horizontal='center', vertical='center')

                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment

                # 自动调整列宽
                for column in ws.columns:
                    max_length = 0
                    col_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    ws.column_dimensions[col_letter].width = min(max_length + 2, 50)

                logger.info(f'Sheet "{sheet_name}" 处理完成，共 {len(new_df)} 行数据')

        logger.info(f'数据提取完成，已保存到: {output_file}')
        return True

    except Exception as e:
        logger.error(f'数据处理失败: {e}')
        import traceback
        logger.error(traceback.format_exc())
        return False


def login():
    """京东登录"""
    logger.info('开始登录京东....')
    url = 'https://www.jd.com/'
    ele = '//li[@id="ttbar-login-2024"]/div[1]'
    key = 'login.jd_cookie'
    Playwright_.login(url, ele, key)
    logger.info('京东登录成功')

def search():



if __name__ == '__main__':
    # 配置输入输出文件路径
    # input_file = r'D:\software\wechat_file\xwechat_files\wxid_tye1h8rj4god29_27e0\msg\file\2026-05\(已瘦身)链动蔚来全品类商品明细2026版-ljy.xlsx'  # 替换为你的输入文件路径
    # output_file = 'd:/_code/spider_jd/标题.xlsx'  # 替换为你的输出文件路径
    #
    # extract_jd_data(input_file, output_file)
    pass