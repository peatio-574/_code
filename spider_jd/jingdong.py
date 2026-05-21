# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from ReadFile import ReadData
import openpyxl
from Logger import logger
from PlayWright import Playwright_, get_config_value
import time
import random
import shutil


file = get_config_value('login', 'file')
wb = openpyxl.load_workbook(file)
ws = wb['Sheet1']
exist_data = ReadData.read_xlsx_col(file)['唯一编号']
exist_count = len(exist_data)
row_id = exist_count +1


def login():
    """京东登录"""
    logger.info('开始登录京东....')
    url = 'https://www.jd.com/'
    ele = '//li[@id="ttbar-login-2024"]/div[1]'
    key = 'login.jd_cookie'
    Playwright_.login(url, ele, key)
    logger.info('京东登录成功')


def get_title(product_id):
    """获取产品标题"""
    try:
        url = f'https://item.jd.com/{product_id}.html'
        Playwright_.goto(url)
        time.sleep(3)
        title = Playwright_.get_text('//span[@class="sku-title-name"]')
        return title
    except Exception as e:
        logger.error(f'获取产品标题失败：{e}')
        return False


def get_info(product_id, title, valid_count):
    global wb, ws, row_id
    global exist_count


    flag = 0  # 标记是否有新数据

    # 获取评论数量
    comment_count_ele = '//div[@data-testid="virtuoso-item-list"]/div'
    comment_count = Playwright_.get_count(comment_count_ele)

    comment_count = min(comment_count, 6)  # 每次最多爬取5条数据
    for comement_ in range(1, comment_count):
        # 评论ID：product_id + data_index + data_item_index + data_known_size
        comment_id_ele = f'({comment_count_ele})[{comement_}]'
        known_size = Playwright_.get_attribute(comment_id_ele, 'data-known-size')

        # 评论人名
        comment_name_ele = f'{comment_id_ele}//span[@class="jdc-pc-rate-card-nick"]'
        comment_name = Playwright_.get_text(comment_name_ele)

        # 唯一编号
        comment_id = product_id + '-' + comment_name + '-' + known_size
        if comment_id in exist_data:
            logger.info(f'已爬取过该条数据，唯一编号：{comment_id}')
            continue

        # 商品型号
        product_type_ele = f'{comment_id_ele}//span[@class="info"]'
        product_type_count = Playwright_.get_count(product_type_ele)
        product_type = Playwright_.get_text(product_type_ele) if product_type_count > 0 else ''

        # 评论时间
        comment_time_ele = f'{comment_id_ele}//span[@class="date list"]'
        comment_time = Playwright_.get_text(comment_time_ele)

        # 评论内容
        comment_text_ele = f'{comment_id_ele}//span[@class="jdc-pc-rate-card-main-desc"]'
        comment_text = Playwright_.get_text(comment_text_ele)

        # 写入数据
        row_id += 1
        ws.cell(row=row_id, column=1, value=product_id)
        ws.cell(row=row_id, column=2, value=comment_id)
        ws.cell(row=row_id, column=3, value=title)
        ws.cell(row=row_id, column=4, value=comment_time)
        ws.cell(row=row_id, column=5, value=comment_name)
        ws.cell(row=row_id, column=6, value=product_type)
        ws.cell(row=row_id, column=7, value=comment_text)
        wb.save(file)

        valid_count += 1
        exist_count += 1
        logger.info(f'第{valid_count}条有效数据，已保存第 {row_id} 行，合计条数：{exist_count}，唯一编号：{comment_id}')

        flag = 1
        exist_data.append(comment_id)
    return valid_count, flag
        
        
def spider_product(product_id, title):
    global exist_data

    try:
        # 滚动页面，查看评价
        Playwright_.page.keyboard.press('PageDown')
        time.sleep(2)
        logger.info('点击查看更多')
        Playwright_.click('//div[@class="applause-rate golden"]')
        time.sleep(5)

        roll_time = 0 # 滚动次数
        limit_roll_time = 6
        valid_count = 0  # 获取的有效数据数量

        invalid_roll_time = 0  # 无效滚动次数
        while True:
            # # 爬取数据足够就退出，获取连续6次未获取到新数据就退出
            # if exist_count == 1000:
            #     logger.info('已爬取所有评论')
            #     return True

            # 获取评论
            valid_count, flag = get_info(product_id, title, valid_count)
            # 滚动页面
            down_size = random.randint(900, 1500)
            Playwright_.page.mouse.wheel(0, down_size)  # 向下滚动
            roll_time += 1

            invalid_roll_time = 0 if flag == 1 else invalid_roll_time + 1

            if invalid_roll_time == limit_roll_time:  # 滚动次数达到6次，判断是否有新数据
                logger.info(f'已连续滚动{limit_roll_time}次未获取到新数据，退出当前产品评论爬取')
                return True

            # 睡眠 有新数据睡眠20-30s，无新数据睡眠5-20s
            sleep_sec = random.randint(5, 20) if flag == 0 else random.randint(20, 30)
            logger.info(f'已滚动{roll_time}次，睡眠{sleep_sec}秒，当前无效滚动次数：{invalid_roll_time}')
            time.sleep(sleep_sec)
    except Exception as e:
        logger.error(f'爬取产品{product_id}的评论异常：{e}')
        return False


def main():
    global exist_count
    while True:
        time.sleep(3)
        product_id = input('\n请输入产品ID:')
        logger.info(f'开始爬取产品：{product_id}数据，当前初始数据数量：{exist_count}')
        login()
        title = get_title(product_id)
        if not title:
            logger.error(f'获取产品{product_id}的标题失败')
            continue
        status = spider_product(product_id, title)
        if status:
            copy(product_id)


def copy(product_id):
    """将第一个xlsx文件的数据追加写入到第二个xlsx文件中"""
    global wb, ws, file
    try:

        # 目标文件（可以修改为其他路径）
        target_file = 'd:/_code/spider_jd/京东评论最终数据.xlsx'

        logger.info(f'产品编号：{product_id}，开始复制【{file}】数据到【{target_file}】中......')

        # 获取源文件的所有数据行（从第2行开始，假设第1行是表头）
        source_rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if any(cell is not None for cell in row):  # 跳过空行
                source_rows.append(row)

        if not source_rows:
            logger.warning('源文件没有数据可复制')
            return False

        # 加载或创建目标文件
        try:
            target_wb = openpyxl.load_workbook(target_file)
            target_ws = target_wb.active
        except FileNotFoundError:
            # 如果目标文件不存在，创建新文件并复制表头
            target_wb = openpyxl.Workbook()
            target_ws = target_wb.active

            # 复制表头
            header_row = []
            for cell in ws[1]:
                header_row.append(cell.value)
            target_ws.append(header_row)

        # 获取目标文件当前的行数
        target_last_row = target_ws.max_row

        # 追加数据
        appended_count = 0
        for row_data in source_rows:
            target_ws.append(row_data)
            appended_count += 1

        # 保存目标文件
        target_wb.save(target_file)
        logger.info(f'数据复制完成！共追加 {appended_count} 行数据，初始行数：{target_last_row}，当前总行数：{target_ws.max_row}')

        temlate = 'd:/_code/spider_jd/京东评论模板.xlsx'
        shutil.copy2(temlate, file)
        logger.info(f'【{file}】已初始化数据')

        return True

    except Exception as e:
        logger.error(f'数据复制失败：{e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    main()



