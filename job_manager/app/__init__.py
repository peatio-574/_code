from flask import Flask
from flask_login import LoginManager
import os
from .config import config
from .models import db, User, Campus, Role
from .permissions import get_user_permissions, can_access_menu as _can_access_menu

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from .permissions import init_csrf
        csrf = init_csrf()
        if current_user.is_authenticated:
            return {
                'csrf_token': csrf,
                'user_permissions': get_user_permissions(current_user),
                'can_access_menu': lambda menu: _can_access_menu(current_user, menu)
            }
        return {'csrf_token': csrf, 'user_permissions': [], 'can_access_menu': lambda menu: False}

    from .auth import auth_bp
    from .admin import admin_bp
    from .student import student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(student_bp, url_prefix='/student')

    with app.app_context():
        db.create_all()
        _create_defaults()

    # 确保上传目录存在
    upload_dir = app.config.get('UPLOAD_FOLDER')
    if upload_dir:
        os.makedirs(upload_dir, exist_ok=True)

    return app


def _create_defaults():
    # 默认数据初始化：表里已有则跳过（含软删的复活），无则创建，保证幂等不报错。

    # 默认校区
    campus = Campus.query.filter_by(name='默认校区').first()
    if campus:
        campus.is_deleted = False
        campus.is_active = True
    else:
        db.session.add(Campus(name='默认校区'))

    # 默认角色
    default_roles = ['校长', '老师', '教务主管', '招生主任']
    for role_name in default_roles:
        role = Role.query.filter_by(name=role_name).first()
        if role:
            role.is_deleted = False
            role.is_active = True
        else:
            db.session.add(Role(name=role_name))

    # 2个超管账号
    for uname, rname in [('admin1', '超级管理员1'), ('admin2', '超级管理员2')]:
        user = User.query.filter_by(username=uname).first()
        if user:
            # 已有则跳过，仅复活，不改密码/姓名
            user.is_deleted = False
        else:
            admin = User(username=uname, user_type='super_admin', real_name=rname)
            admin.set_password('admin123')
            db.session.add(admin)

    db.session.commit()
