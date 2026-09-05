from flask import Flask
from flask_login import LoginManager
import os
from .config import config
from .models import db, User, Campus, Role

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
    # 创建默认校区
    if not Campus.query.filter_by(name='默认校区', is_deleted=False).first():
        campus = Campus(name='默认校区')
        db.session.add(campus)

    # 创建默认角色
    default_roles = ['校长', '老师', '教务主管', '招生主任']
    for role_name in default_roles:
        if not Role.query.filter_by(name=role_name, is_deleted=False).first():
            role = Role(name=role_name)
            db.session.add(role)

    # 创建2个超管账号
    if not User.query.filter_by(username='admin1').first():
        admin = User(username='admin1', user_type='super_admin', real_name='超级管理员1')
        admin.set_password('admin123')
        db.session.add(admin)

    if not User.query.filter_by(username='admin2').first():
        admin2 = User(username='admin2', user_type='super_admin', real_name='超级管理员2')
        admin2.set_password('admin123')
        db.session.add(admin2)

    db.session.commit()
