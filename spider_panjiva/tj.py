# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from spider_panjiva.login import tj_login, Playwright_, logger, file, ws, wb, panjiva_login
import time
from ReadFile import ReadData
from panjiva import get_company_detail


def get_company_info(company_name):
    """获取探迹公司数据"""
    info = {'status': '', 'tel': '', 'peple': '', 'addr': '', 'lock': '否', 'add_crm': '否', 'permission': '是'}
    try:
        Playwright_.goto('https://logistics.tungee.com/search-enterprise/result?key=&page=1')
        Playwright_.input('(//input[@placeholder="请输入关键词，多个关键词用空格隔开"])[1]', company_name, enter=True)
        time.sleep(3)

        list_count = Playwright_.get_count('//tbody/tr')
        if list_count == 0:
            logger.info(f'【{company_name}】未找到探迹数据')
            return  info

        ele = '(//tbody/tr)[1]'

        companyname = Playwright_.get_text(f'{ele}//h3/a')

        if companyname != company_name:
            return info

        status = Playwright_.get_text(f'{ele}//div[contains(@class, "M8")]')
        info['status'] = status
        if status == '注销':
            logger.info(f'【{company_name}】已注销')
            return info

        permission_ele = f'{ele}//i[@class="anticon anticon-info-circle"]'
        if Playwright_.get_count(permission_ele):
            logger.info(f'【{company_name}】权限不足')
            info['permission'] = '否'
            return info

        action_ele = f'{ele}//button/span'
        if Playwright_.get_count(action_ele):
            text = Playwright_.get_text(action_ele)
            if text == '立即解锁':
                info['lock'] = '是'
                Playwright_.click(action_ele)
                time.sleep(2)
            Playwright_.click(action_ele)
            info['add_crm'] = '是'
            time.sleep(1)
            Playwright_.click('(//div[@class="ant-drawer-body"]//button[@class="ant-btn ant-btn-primary"])[last()]')


        company_url = Playwright_.get_attribute(f'{ele}//h3/a', 'href')
        company_url = 'https://logistics.tungee.com' + company_url
        Playwright_.goto(company_url)
        time.sleep(3)


        Playwright_.click('//i[text()="联系方式"]')
        time.sleep(2)
        hot_ele = '//div[contains(text(),"Hot联系方式")]'
        if Playwright_.get_count(hot_ele):
            Playwright_.click(hot_ele)

        tel_ele = '(//tbody/tr)[1]/td[2]/div/span[1]'
        tel = Playwright_.get_text(tel_ele) if Playwright_.get_count(tel_ele) else ''
        info['tel'] = tel

        peple = Playwright_.get_text('//span[text()="企业法人"]/../a[1]')
        info['peple'] = peple

        addr = Playwright_.get_text('//span[text()="企业地址："]/../span[2]')
        info['addr'] = addr
    except Exception as e:
        logger.error(f'【{company_name}】探迹数据获取异常：{e}')
    return info



def get_all():
    data = ReadData.read_xlsx_col(file)
    companys = data['公司中文名']
    urls = data['link']

    panjiva_login()
    tj_login()

    tmp_ele = '//span[text()="拓客 · 国际物流版"]'
    if Playwright_.get_count(tmp_ele):
        Playwright_.click(tmp_ele)

    for row_id, company in enumerate(companys, start=2):
        if company == '':
            continue
        info = get_company_info(company)
        if info['permission'] == '是':
            info_ = get_company_detail(company, urls[row_id-2])
            for k, v in info_.items():
                info[k] = v
        ws.cell(row=row_id, column=5, value=info['status'])
        ws.cell(row=row_id, column=6, value=info['permission'])
        ws.cell(row=row_id, column=7, value=info['peple'])
        ws.cell(row=row_id, column=8, value=info['addr'])
        ws.cell(row=row_id, column=9, value=info['tel'])
        ws.cell(row=row_id, column=10, value=info['lock'])
        ws.cell(row=row_id, column=11, value=info['add_crm'])
        if info['permission'] == '是':
            ws.cell(row=row_id, column=12, value=info['product'])
            ws.cell(row=row_id, column=13, value=info['compare'])
        wb.save(file)
        logger.info(f'第{row_id}行{company}数据爬取完成：{info}')

if __name__ == '__main__':
    get_all()


