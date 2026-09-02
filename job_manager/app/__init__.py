from flask import Flask
from flask_login import LoginManager
from .config import config
from .models import db, User

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

    # 注册蓝图
    from .auth import auth_bp
    from .admin import admin_bp
    from .student import student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(student_bp, url_prefix='/student')

    # 创建数据库表
    with app.app_context():
        db.create_all()
        # 创建默认管理员账号
        _create_default_admin()

    return app


def _create_default_admin():
    from .models import User
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            user_type='admin',
            real_name='超级管理员',
            can_manage_jobs=True,
            can_manage_students=True,
            can_manage_accounts=True,
            can_push_jobs=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
