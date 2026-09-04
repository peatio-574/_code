from flask import Flask
from flask_login import LoginManager
from .config import config
from .models import db, User, Campus

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

    return app


def _create_defaults():
    # 创建默认校区
    default_campuses = ['总校区', '东区分校', '西区分校']
    for name in default_campuses:
        if not Campus.query.filter_by(name=name).first():
            db.session.add(Campus(name=name))

    # 创建2个超管账号
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', user_type='super_admin', real_name='超级管理员1')
        admin.set_password('admin123')
        db.session.add(admin)

    if not User.query.filter_by(username='superadmin').first():
        admin2 = User(username='superadmin', user_type='super_admin', real_name='超级管理员2')
        admin2.set_password('admin123')
        db.session.add(admin2)

    db.session.commit()
