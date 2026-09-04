import re

path = 'app/admin/routes.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

# 替换页面重定向为对应的 page 视图
replacements = [
    ("url_for('admin.jobs_list')", "url_for('admin.jobs_page')"),
    ("url_for('admin.users_list')", "url_for('admin.users_page')"),
]

for old, new in replacements:
    count = content.count(old)
    content = content.replace(old, new)
    print(f'{old} -> {new}: {count} replacements')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
