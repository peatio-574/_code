# -*- coding: utf-8 -*-
"""生成测试证书数据

用法：
    python generate_data.py            # 清空证书表并生成 400 条
    python generate_data.py 1000       # 生成 1000 条
    python generate_data.py 400 --keep # 保留现有数据，追加生成
"""
import random
import sys
from datetime import date

from app import create_app
from app.models import db, Certificate

app = create_app('development')

SURNAMES = [
    ('王', 'Wang'), ('李', 'Li'), ('张', 'Zhang'), ('刘', 'Liu'), ('陈', 'Chen'),
    ('杨', 'Yang'), ('赵', 'Zhao'), ('黄', 'Huang'), ('周', 'Zhou'), ('吴', 'Wu'),
    ('徐', 'Xu'), ('孙', 'Sun'), ('马', 'Ma'), ('朱', 'Zhu'), ('胡', 'Hu'),
    ('郭', 'Guo'), ('何', 'He'), ('高', 'Gao'), ('林', 'Lin'), ('罗', 'Luo'),
]

GIVEN = [
    ('沐凡', 'Mu Fan'), ('伟', 'Wei'), ('芳', 'Fang'), ('娜', 'Na'), ('敏', 'Min'),
    ('静', 'Jing'), ('磊', 'Lei'), ('强', 'Qiang'), ('军', 'Jun'), ('洋', 'Yang'),
    ('勇', 'Yong'), ('艳', 'Yan'), ('杰', 'Jie'), ('娟', 'Juan'), ('涛', 'Tao'),
    ('明', 'Ming'), ('超', 'Chao'), ('秀英', 'Xiu Ying'), ('霞', 'Xia'), ('平', 'Ping'),
    ('刚', 'Gang'), ('桂英', 'Gui Ying'), ('浩', 'Hao'), ('雨欣', 'Yu Xin'),
    ('子轩', 'Zi Xuan'), ('梓涵', 'Zi Han'), ('宇轩', 'Yu Xuan'), ('欣怡', 'Xin Yi'),
]

MAJORS = ['漫画', '素描', '速写', '水彩画', '水粉画', '软笔书法', '硬笔书法', '人物', '山水', '花鸟']
ORG = '中国美术学院'
NATIONALITY = '中国'
ETHNICITY = '汉族'


def generate(count=400, keep=False):
    random.seed(42)
    with app.app_context():
        if not keep:
            Certificate.query.delete()
            db.session.commit()

        existing = {row[0] for row in db.session.query(Certificate.cert_no).all()}
        added = 0
        seq = 1
        while added < count:
            surname, s_pinyin = random.choice(SURNAMES)
            given, g_pinyin = random.choice(GIVEN)
            name = surname + given
            name_pinyin = '%s %s' % (s_pinyin, g_pinyin)

            major = random.choice(MAJORS)
            level = random.randint(1, 10)
            level_range = '1-9' if major == '漫画' else '1-10'

            birth_year = random.randint(2006, 2018)
            birth_month = random.randint(1, 12)
            birth_day = random.randint(1, 28)
            birth_date = '%04d-%02d' % (birth_year, birth_month)

            issue = date(random.randint(2024, 2026), random.randint(1, 12), random.randint(1, 28))

            cert_no = '0072034261%08d' % seq
            id_card = '6101%02d%04d%02d%02d%04d' % (
                random.randint(1, 30), birth_year, birth_month, birth_day, seq % 10000)
            seq += 1

            if cert_no in existing:
                continue

            db.session.add(Certificate(
                name=name,
                issue_date=issue.strftime('%Y-%m-%d'),
                major=major,
                level_range=level_range,
                level=str(level),
                org=ORG,
                id_card=id_card,
                nationality=NATIONALITY,
                ethnicity=ETHNICITY,
                birth_date=birth_date,
                name_pinyin=name_pinyin,
                cert_no=cert_no,
            ))
            existing.add(cert_no)
            added += 1

        db.session.commit()
        print('生成完成：本次新增 %d 条，当前证书总数 %d 条' % (added, Certificate.query.count()))


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    count = int(args[0]) if args else 400
    keep = '--keep' in sys.argv
    generate(count=count, keep=keep)
