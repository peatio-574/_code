# -*- coding: utf-8 -*-
"""中国美术学院社会美术水平考级 - 报名管理系统"""
import logging
import os
from datetime import datetime

from flask import Flask, redirect, request, url_for
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
    app = Flask(__name__, static_url_path=config_map[config_name].STATIC_URL_PATH)
    app.config.from_object(config_map[config_name])

    # 接口返回 JSON 时直接输出中文，而不是 \uXXXX 转义
    try:
        app.json.ensure_ascii = False
    except AttributeError:
        app.config['JSON_AS_ASCII'] = False

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(app.config.get('SIGNUP_UPLOAD_DIR', os.path.join(DATA_DIR, 'uploads', 'signup')), exist_ok=True)
    setup_logging(app)

    db.init_app(app)
    login_manager.init_app(app)

    from .public import public_bp
    from .admin import admin_bp
    prefix = app.config['ROUTE_PREFIX']
    app.register_blueprint(public_bp, url_prefix=prefix)
    app.register_blueprint(admin_bp, url_prefix=app.config['ADMIN_ROUTE_PREFIX'])

    @app.route('/')
    @app.route(prefix)
    @app.route(prefix + '/')
    def _root():
        return redirect(url_for('public.signup'))

    # 兼容旧写法：/new/manager* -> /new/manage*（301 保留方法语义之外的行为）
    admin_prefix = app.config['ADMIN_ROUTE_PREFIX']
    legacy_prefix = prefix + '/manager'
    if legacy_prefix != admin_prefix:
        @app.route(legacy_prefix + '/', defaults={'_rest': ''})
        @app.route(legacy_prefix + '/<path:_rest>')
        def _legacy_admin(_rest=''):
            target = admin_prefix + ('/' + _rest if _rest else '')
            qs = request.query_string.decode('utf-8', 'replace')
            return redirect(target + ('?' + qs if qs else ''), code=301)

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
        if request.path.startswith(app.static_url_path + '/'):
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
        _ensure_columns()
        _ensure_default_accounts(app)

    return app


def _ensure_columns():
    """幂等补充新增字段（db.create_all 不会为已存在的表加列）。"""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        if 'registration' in tables:
            cols = [c['name'] for c in insp.get_columns('registration')]
            stmts = []
            if 'institution_id' not in cols:
                stmts.append('ALTER TABLE registration ADD COLUMN institution_id INT NULL')
            if 'institution' not in cols:
                stmts.append('ALTER TABLE registration ADD COLUMN institution VARCHAR(100) NULL')
            if stmts:
                with db.engine.begin() as conn:
                    for stmt in stmts:
                        conn.execute(text(stmt))
        if 'admin' in tables:
            cols = [c['name'] for c in insp.get_columns('admin')]
            stmts = []
            if 'role' not in cols:
                stmts.append("ALTER TABLE admin ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'")
            if 'password_plain' not in cols:
                stmts.append("ALTER TABLE admin ADD COLUMN password_plain VARCHAR(100) DEFAULT ''")
            if 'institution_id' not in cols:
                stmts.append("ALTER TABLE admin ADD COLUMN institution_id INT NULL")
            if stmts:
                with db.engine.begin() as conn:
                    for stmt in stmts:
                        conn.execute(text(stmt))
        if 'institution' in tables:
            cols = [c['name'] for c in insp.get_columns('institution')]
            if 'expires_at' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE institution ADD COLUMN expires_at DATETIME NULL"))
    except Exception as exc:
        print('[WARN] 补充字段失败：%s' % exc)


def _ensure_default_accounts(app):
    """幂等确保默认账号存在：主管理员 + 受限账号 user。"""
    admin = Admin.query.filter_by(username=app.config['ADMIN_USERNAME']).first()
    if not admin:
        admin = Admin(username=app.config['ADMIN_USERNAME'], role='admin')
        admin.set_password(app.config['ADMIN_PASSWORD'])
        db.session.add(admin)
    elif not admin.role:
        admin.role = 'admin'
    # 历史账号若未记录明文，且仍是配置里的默认密码，则补记明文
    if not admin.password_plain and admin.verify_password(app.config['ADMIN_PASSWORD']):
        admin.password_plain = app.config['ADMIN_PASSWORD']
    # 受限账号：报名管理 + 修改密码
    limited = Admin.query.filter_by(username='user').first()
    if not limited:
        limited = Admin(username='user', role='user')
        limited.set_password('user1234')
        db.session.add(limited)
    elif not limited.role:
        limited.role = 'user'
    if not limited.password_plain and limited.verify_password('user1234'):
        limited.password_plain = 'user1234'
    db.session.commit()


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
