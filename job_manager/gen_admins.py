import sys, io, random, openpyxl
sys.stdout.reconfigure(encoding='utf-8')

# 管理员导入模板列
wb = openpyxl.Workbook()
ws = wb.active
ws.title = '管理员导入模板'
ws.append(['姓名', '密码(默认123456)', '手机号', '校区名称', '角色(校长/老师等)', 
           '岗位推送权限(是/否)', '岗位查看权限(是/否)', '学员管理权限(是/否)'])

surnames = ['张', '李', '王', '刘', '陈', '杨', '赵', '黄', '周', '吴', '徐', '孙', '马', '胡', '朱', '郭']
given_male = ['伟', '强', '磊', '军', '洋', '勇', '峰', '杰', '涛', '明', '超', '刚', '平', '辉']
given_female = ['娜', '敏', '静', '丽', '娟', '艳', '芳', '婷', '雪', '琳', '梅', '霞', '颖', '霞']
roles = ['校长', '老师', '招生主任', '教务主管']
campuses = ['总校区', '东区分校', '西区分校']

random.seed(1)
used_phones = set()
def gen_name(i):
    s = random.choice(surnames)
    g = random.choice(given_male + given_female)
    return s + g

admins = []
for i in range(1, 101):
    name = gen_name(i)
    # 生成不重复的11位手机号 (1开头)
    while True:
        phone = '1' + ''.join(str(random.randint(0,9)) for _ in range(10))
        if phone not in used_phones:
            used_phones.add(phone)
            break
    campus = random.choice(campuses)
    role = random.choice(roles)
    can_push = random.choice(['是', '否'])
    can_view = random.choice(['是', '否'])
    can_manage = random.choice(['是', '否'])
    ws.append([name, '123456', phone, campus, role, can_push, can_view, can_manage])
    admins.append(name)

wb.save('admins_import.xlsx')
print('管理员模板已生成: admins_import.xlsx, 共', len(admins), '行')
