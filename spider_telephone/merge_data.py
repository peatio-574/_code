# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
from Logger import logger
from Config import get_config_value

def merge_data():
    # 定义源文件列表
    source_files = [
        get_config_value('login', 'file1'),
        get_config_value('login', 'file2'),
        get_config_value('login', 'file3'),
        get_config_value('login', 'file4'),
        get_config_value('login', 'file5'),
        get_config_value('login', 'file6'),
        get_config_value('login', 'file7'),
        get_config_value('login', 'file8'),
        get_config_value('login', 'file9'),
    ]
    # 输出文件（移除末尾的逗号）
    output_file = 'd:/_code/spider_telephone/最终数据.xlsx'

    # 检查文件是否存在
    existing_files = []
    for file in source_files:
        if Path(file).exists():
            existing_files.append(file)
        else:
            logger.warning(f"⚠️ 文件不存在: {file}")

    if not existing_files:
        logger.error("没有找到任何源文件")
        return

    logger.info(f"找到 {len(existing_files)} 个源文件")

    # 读取并合并所有文件
    dfs = []
    total_rows = 0

    for file in existing_files:
        try:
            df = pd.read_excel(file)
            row_count = len(df)
            total_rows += row_count
            dfs.append(df)
            logger.info(f"✅ 读取 {file}: {row_count} 条数据, 表头: {list(df.columns)}")
        except Exception as e:
            logger.error(f"❌ 读取 {file} 失败: {e}")

    if not dfs:
        logger.error("没有成功读取任何文件")
        return

    # 合并所有DataFrame
    merged_df = pd.concat(dfs, ignore_index=True)

    # 保存合并后的文件
    merged_df.to_excel(output_file, index=False)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"✅ 合并完成！")
    logger.info(f"输出文件: {output_file}")
    logger.info(f"总数据量: {total_rows} 条")
    logger.info(f"表头: {list(merged_df.columns)}")
    logger.info(f"{'=' * 60}")

if __name__ == '__main__':
    merge_data()