import sys, io, random, openpyxl
sys.stdout.reconfigure(encoding='utf-8')

wb = openpyxl.Workbook()
ws = wb.active
ws.title = '学员导入模板'
ws.append(['身份证号(18位)', '姓名', '手机号', '学历(大专/本科/硕士/博士)', '专业', 
           '性别(男/女)', '政治面貌', '生源地', '意向城市', '第一意向岗位', 
           '第二意向岗位', '第三意向岗位', '证书', '备注', '毕业时间(YYYY-MM-DD)', '密码(默认123456)'])

surnames = ['张', '李', '王', '刘', '陈', '杨', '赵', '黄', '周', '吴', '徐', '孙', '马', '胡', '朱', '郭', '何', '林', '高', '罗',
            '郑', '梁', '谢', '宋', '唐', '许', '韩', '冯', '邓', '曹']
given = ['伟', '强', '磊', '军', '洋', '勇', '峰', '杰', '涛', '明', '超', '刚', '平', '辉', '建', '文', '宇', '晨', '昊', '然',
         '娜', '敏', '静', '丽', '娟', '艳', '芳', '婷', '雪', '琳', '梅', '霞', '颖', '慧', '媛', '欣', '怡', '倩', '莹', '洁',
         '博', '辰', '睿', '泽', '轩', '烁', '瑞', '琪', '淑', '萍', '蓉', '莉', '燕', '婷', '薇', '菲', '芮', '峄', '其', '铭']
majors = ['计算机科学', '软件工程', '电子信息', '机械制造', '市场营销', '会计学', '土木工程', '护理学', '汉语言文学', '英语']
cities = ['成都', '北京', '上海', '广州', '重庆', '深圳', '天津', '武汉', '西安', '大连']
educations = ['大专', '本科', '硕士', '博士']
politics = ['中共党员', '共青团员', '群众']
certificates = ['计算机二级', '英语四级', '会计证', '教师资格证', '无']
jobs = ['前端开发', '后端开发', '数据分析', '产品经理', 'UI设计', '测试工程师', '运营专员']

print('唯一姓名组合数:', len(surnames) * len(given))

random.seed(42)
used_names = set()
seen_id = set()

def gen_id_card():
    area = str(random.randint(110000, 659999))
    year = random.randint(1995, 2004)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    birth = f'{year:04d}{month:02d}{day:02d}'
    seq = f'{random.randint(0, 999):03d}'
    return area + birth + seq + random.choice('0123456789X')

for i in range(1, 1001):
    for _ in range(500):
        name = random.choice(surnames) + random.choice(given)
        if name not in used_names:
            used_names.add(name)
            break
    else:
        raise SystemExit('无法生成足够唯一姓名，需要扩大名字库')
    for _ in range(2000):
        id_card = gen_id_card()
        if id_card not in seen_id:
            seen_id.add(id_card)
            break
    phone = '1' + ''.join(str(random.randint(0,9)) for _ in range(10))
    grad = f'20{random.randint(25, 27)}-06-30'
    ws.append([id_card, name, phone, random.choice(educations), random.choice(majors),
               random.choice(['男', '女']), random.choice(politics), random.choice(cities),
               random.choice(cities), random.choice(jobs), random.choice(jobs),
               random.choice(jobs), random.choice(certificates), '', grad, '123456'])

wb.save('students_import.xlsx')
print('学员模板已生成: students_import.xlsx, 共 1000 行, 唯一姓名:', len(used_names))
