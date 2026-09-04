"""更新超级管理员名称"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db
from app.models import User

app = create_app()
with app.app_context():
    admin1 = User.query.filter_by(username='admin').first()
    if admin1:
        admin1.real_name = '超级管理员1'
        print(f"已更新 admin -> 超级管理员1")
    
    admin2 = User.query.filter_by(username='superadmin').first()
    if admin2:
        admin2.real_name = '超级管理员2'
        print(f"已更新 superadmin -> 超级管理员2")
    
    db.session.commit()
    print("完成")