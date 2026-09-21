# -*- coding: utf-8 -*-
"""中国美术学院社会美术水平考级 - 证书查询系统"""
import logging
import os
from datetime import datetime

from flask import Flask, request, url_for
from flask_login import LoginManager

from .config import config as config_map, DATA_DIR, ensure_mysql_database
from .models import db, Admin

login_manager = LoginManager()
login_manager.login_view = 'admin.login'
login_manager.login_message = '请先登录'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Admin, int(user_id))


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config_map[config_name])

    # 接口返回 JSON 时直接输出中文，而不是 \uXXXX 转义
    try:
        app.json.ensure_ascii = False
    except AttributeError:
        app.config['JSON_AS_ASCII'] = False

    os.makedirs(DATA_DIR, exist_ok=True)
    setup_logging(app)

    db.init_app(app)
    login_manager.init_app(app)

    from .public import public_bp
    from .admin import admin_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_globals():
        def asset(filename, external=False):
            """静态资源 URL，附带文件修改时间作为版本号，避免浏览器缓存旧文件"""
            path = os.path.join(app.static_folder, filename.replace('/', os.sep))
            try:
                version = int(os.path.getmtime(path))
            except OSError:
                version = 0
            return url_for('static', filename=filename, v=version, _external=external)

        return {
            'SITE_TITLE': app.config['SITE_TITLE'],
            'SITE_SUBTITLE': app.config['SITE_SUBTITLE'],
            'OFFICIAL_SITE': app.config['OFFICIAL_SITE'],
            'HOME_URL': app.config['HOME_URL'],
            'now': datetime.now(),
            'asset': asset,
        }

    @app.template_filter('dt')
    def fmt_dt(value):
        return value.strftime('%Y-%m-%d %H:%M:%S') if value else ''

    @app.after_request
    def cache_static(response):
        # 静态资源带版本号(?v=文件修改时间)，可长期缓存：
        # 文件一旦改动，URL 的版本号随之改变，浏览器会自动拉取新文件
        if request.path.startswith('/static/'):
            response.cache_control.no_cache = None
            response.cache_control.public = True
            response.cache_control.max_age = 31536000  # 1 年
            response.cache_control.immutable = True
        return response

    # 确保 MySQL 数据库存在
    try:
        ensure_mysql_database()
    except Exception as exc:
        print('[WARN] 无法创建数据库（请确认 MySQL 已启动）：%s' % exc)

    with app.app_context():
        db.create_all()
        if not Admin.query.first():
            admin = Admin(username=app.config['ADMIN_USERNAME'])
            admin.set_password(app.config['ADMIN_PASSWORD'])
            db.session.add(admin)
            db.session.commit()

    return app


def setup_logging(app):
    """日志输出到项目根目录 logs/app.log（幂等，不重复添加 handler）"""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(root_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        handler = logging.FileHandler(os.path.join(log_dir, 'app.log'), encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
        handler.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
