# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from spider_panjiva.login import qcc_login, logger, Playwright_, file, wb, ws
import time
from ReadFile import ReadData



def qcc_search(company):
    """获取企查查单条数据"""
    try:
        Playwright_.input('(//input)[1]', company, enter=True)
        time.sleep(5)

        result_count = Playwright_.get_count('//table/tr')
        result_count = min(result_count, 5)
        for i in range(1, result_count+1):
            ele = f'(//table/tr)[{i}]'

            # 验证公司存续状态
            status_ele = f'{ele}//span[contains(@class,"nstatus")]'
            status= Playwright_.get_text(status_ele)

            if status == '注销':
                continue

            company_en_ele = f'{ele}//span[@class="sf"][1]/span'
            company_en = Playwright_.get_text(company_en_ele) if Playwright_.get_count(company_en_ele) else ''
            if company in company_en:
                company_name_ele = f'{ele}//span[@class="copy-title"]/a/span'
                company_name = Playwright_.get_text(company_name_ele)
                return company_name, status
    except Exception as e:
        logger.error(f'【{company}】企查查数据获取异常：{e}')
    return '', ''



def qcc_get_data():
    """获取企查查数据"""
    companys = ReadData.read_xlsx_col(file)['公司英文名']

    qcc_login()

    for row_id, company in enumerate(companys, start=2):
        if company == '':
            logger.info(f'第{row_id}行空行，跳过')
            continue

        company_name, status = qcc_search(company)

        if company_name != '':
            ws.cell(row=row_id, column=3, value=company_name)
            ws.cell(row=row_id, column=4, value=status)
            wb.save(file)
            logger.info(f'第{row_id}行成功查到符合条件的公司名称：{company}：{company_name}')
        else:
            logger.info(f'第{row_id}行未查到符合条件的公司名称：{company}')
    logger.info('企查查数据获取完成！！！')

if __name__ == '__main__':
    # qcc_get_data()
    qcc_login()
    info = qcc_search('Zhongpin Intelligent Machinery Co.. Ltd.')
    print(info)