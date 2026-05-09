# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from Config import get_config_value
from Logger import logger
import pandas as pd


def deal_data():
    source_file = get_config_value('login', 'file')
    dirname = Path(source_file).parent

    if not Path(source_file).exists():
        logger.error(f"文件不存在: {source_file}")
        return

    # 读取原始数据
    df = pd.read_excel(source_file)
    total_rows = len(df)
    logger.info(f"从 {source_file} 读取到 {total_rows} 条数据")
    logger.info(f"表头: {list(df.columns)}")

    # 计算每个文件的数据量
    chunk_size = total_rows // 5
    remainder = total_rows % 5

    # 分割数据
    for i in range(5):
        # 计算起始和结束索引
        start_idx = i * chunk_size + min(i, remainder)
        end_idx = (i + 1) * chunk_size + min(i + 1, remainder)

        # 提取数据块（包含表头）
        chunk_df = df.iloc[start_idx:end_idx]

        # 生成新文件名
        output_file = f'{dirname}/电话号码判断{i + 1}.xlsx'

        # 保存文件
        chunk_df.to_excel(output_file, index=False)

        logger.info(f"✅ 文件 {output_file} 已保存，共 {len(chunk_df)} 条数据 (行 {start_idx + 2} - {end_idx + 1})")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"数据分割完成！共生成 5 个文件")
    logger.info(f"总数据量: {total_rows} 条")
    logger.info(f"平均每个文件: {chunk_size} 条")
    if remainder:
        logger.info(f"前 {remainder} 个文件多 1 条数据")
    logger.info(f"{'=' * 60}")

if __name__ == '__main__':
    deal_data()
