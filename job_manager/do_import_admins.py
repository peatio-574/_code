import sys, io
sys.stdout.reconfigure(encoding='utf-8')
from app import create_app

app = create_app()

with app.test_client() as client:
    # 1. GET 登录页获取 session 中的 CSRF
    r = client.get('/login')
    assert r.status_code == 200, f'login page failed: {r.status_code}'
    with client.session_transaction() as s:
        csrf = s.get('csrf_token')
    print('CSRF from login:', csrf)

    # 2. 登录 superadmin
    r = client.post('/login', data={
        'username': 'superadmin',
        'password': 'admin123'
    }, follow_redirects=True)
    assert r.status_code == 200, f'login failed: {r.status_code}'
    print('login ok')

    # 3. GET 导入管理员页
    r = client.get('/admin/import_admins')
    assert r.status_code == 200, f'import_admins page failed: {r.status_code}'

    # 4. POST 上传管理员Excel
    with open('admins_import.xlsx', 'rb') as f:
        file_bytes = f.read()
    r = client.post('/admin/import_admins', data={
        'csrf_token': csrf,
        'file': (io.BytesIO(file_bytes), 'admins_import.xlsx')
    }, content_type='multipart/form-data', follow_redirects=True)
    print('import admins status:', r.status_code)
    body = r.get_data(as_text=True)
    if '成功导入 100 个管理员' in body:
        print('管理员导入成功: 100 个')
    else:
        # 从 flash 信息里找
        import re
        msgs = re.findall(r'成功导入[^<]*|导入失败[^<]*|未导入[^<]*|警告[^<]*', body)
        print('结果:', msgs[:10])
