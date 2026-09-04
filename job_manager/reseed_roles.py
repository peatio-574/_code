"""删除所有旧角色并重新创建"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db
from app.models import Role

app = create_app()
with app.app_context():
    # 先把所有角色的name改成临时名称，避免唯一约束冲突
    all_roles = Role.query.all()
    for i, role in enumerate(all_roles):
        role.name = f'_old_role_{role.id}_{i}'
    db.session.commit()
    
    # 然后标记为已删除
    Role.query.update({'is_deleted': True})
    db.session.commit()
    print("已清理所有旧角色")
    
    # 重新创建角色
    roles = [
        ('校长', True),
        ('老师', True),
        ('教务主管', True),
        ('招生主任', True),
    ]
    for name, is_active in roles:
        role = Role(name=name, is_active=is_active, is_deleted=False)
        db.session.add(role)
    db.session.commit()
    print(f"已创建 {len(roles)} 个新角色：校长、老师、教务主管、招生主任")