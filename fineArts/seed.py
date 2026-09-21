# -*- coding: utf-8 -*-
"""写入示例证书数据（可选，便于本地演示）

用法： python seed.py
"""
from app import create_app
from app.models import db, Certificate

app = create_app('development')

SAMPLE = {
    'name': '王沐凡',
    'issue_date': '2026-06-01',
    'major': '漫画',
    'level_range': '1-9',
    'level': '2',
    'org': '中国美术学院',
    'id_card': '610125201806120077',
    'nationality': '中国',
    'ethnicity': '汉族',
    'birth_date': '2018-06',
    'name_pinyin': 'Wang Mu Fan',
    'cert_no': '007203426102006880',
}

if __name__ == '__main__':
    with app.app_context():
        exists = Certificate.query.filter_by(cert_no=SAMPLE['cert_no']).first()
        if exists:
            print('示例数据已存在，跳过。')
        else:
            db.session.add(Certificate(**SAMPLE))
            db.session.commit()
            print('示例数据写入成功：%s %s' % (SAMPLE['name'], SAMPLE['cert_no']))
