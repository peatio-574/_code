import logging
import sys
from flask import Flask, request, jsonify
from flask_login import LoginManager
import os
from . import config as config_module
from .models import db, User, Campus, Role
from .permissions import get_user_permissions, can_access_menu as _can_access_menu, validate_csrf

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config_module.config[config_name])

    setup_logging(app)
    setup_error_handlers(app)

    db.init_app(app)
    login_manager.init_app(app)

    @app.before_request
    def csrf_protect():
        # 全局 CSRF 校验（仅对不安全方法生效）
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return validate_csrf()

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
        _add_missing_columns()
        _create_defaults()

    # 确保上传目录存在
    upload_dir = app.config.get('UPLOAD_FOLDER')
    if upload_dir:
        os.makedirs(upload_dir, exist_ok=True)

    return app


def setup_logging(app):
    """中文日志：输出到项目 logs/app.log（持久化，路径与之前一致）+ 标准输出（journald 采集）。

    - 日志**级别保留英文**（INFO/WARNING/ERROR，便于检索），消息内容使用中文；
    - 格式含毫秒时间、模块、行号、函数名，便于定位。
    注意：gunicorn 会通过 --access-logfile/--error-logfile 自行写 logs/access.log、logs/error.log，
    因此这里只接管应用 logger（root / Flask / werkzeug），不干预 gunicorn 日志。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    app_log = os.path.join(log_dir, 'app.log')

    fmt = logging.Formatter(
        '%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s:%(lineno)d] %(funcName)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    file_handler = logging.FileHandler(app_log, encoding='utf-8')
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(fmt)
    stdout_handler.setLevel(logging.INFO)

    # 强制重建 root：先清空可能由 gunicorn/默认安装的 handler，避免格式残留与重复
    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stdout_handler)
    root_logger.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
    app.logger.propagate = True

    # 接管 werkzeug（开发模式），统一为同一格式
    for name in ('werkzeug',):
        lg = logging.getLogger(name)
        for h in lg.handlers[:]:
            lg.removeHandler(h)
        lg.addHandler(file_handler)
        lg.addHandler(stdout_handler)
        lg.setLevel(logging.INFO)
        lg.propagate = False

    root_logger.info('【日志】中文日志已初始化：文件 %s（持久化）+ 标准输出（journald）', app_log)


def setup_error_handlers(app):
    @app.errorhandler(413)
    def handle_request_too_large(_e):
        limit = app.config.get('MAX_CONTENT_LENGTH') or (16 * 1024 * 1024)
        mb = int(limit // (1024 * 1024))
        app.logger.warning('【上传】单次上传超过 %dMB，请求被拒绝', mb)
        return jsonify({'success': False,
                        'message': f'上传文件过大（超过 {mb}MB 上限），请压缩或拆分后再上传'}), 413

    @app.errorhandler(404)
    def handle_not_found(_e):
        return jsonify({'success': False, 'message': '接口不存在（404）'}), 404

    @app.errorhandler(500)
    def handle_server_error(_e):
        app.logger.error('【错误】服务器内部错误（500），请查看日志定位问题')
        return jsonify({'success': False,
                        'message': '服务器内部错误，请稍后重试或联系管理员（已记录日志）'}), 500


def _add_missing_columns():
    """幂等迁移：为已存在的表补充新增字段（AI 权限、附件），避免老库重建丢数据。"""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(db.engine)
        existing = [c['name'] for c in insp.get_columns('users')]
        if 'can_ai_recognition' not in existing:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE users ADD COLUMN can_ai_recognition BOOLEAN DEFAULT 0'))
    except Exception:
        db.session.rollback()

    try:
        insp = inspect(db.engine)
        existing = [c['name'] for c in insp.get_columns('resume_analysis_logs')]
        if 'file_path' not in existing:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE resume_analysis_logs ADD COLUMN file_path VARCHAR(500) DEFAULT ""'))
                conn.execute(text('ALTER TABLE resume_analysis_logs ADD COLUMN file_name VARCHAR(255) DEFAULT ""'))
                conn.execute(text('ALTER TABLE resume_analysis_logs ADD COLUMN file_size INT DEFAULT 0'))
        if 'strengths' not in existing:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE resume_analysis_logs ADD COLUMN strengths TEXT NULL'))
                conn.execute(text('ALTER TABLE resume_analysis_logs ADD COLUMN suggestions TEXT NULL'))
        # 回填历史记录 detail（跨库安全，避免 MySQL 专用 CONCAT 在 SQLite 上失败）
        from .models import ResumeAnalysisLog
        history = ResumeAnalysisLog.query.filter(
            db.or_(ResumeAnalysisLog.detail.is_(None), ResumeAnalysisLog.detail == '')).all()
        for row in history:
            row.detail = f'AI识别完成，评分{row.score}分'
        db.session.commit()
    except Exception as e:
        print('[migrate] resume_analysis_logs 迁移失败:', e)
        db.session.rollback()


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
