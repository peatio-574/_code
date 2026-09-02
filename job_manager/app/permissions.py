from functools import wraps
from flask import flash, redirect, url_for, abort, request, session
from flask_login import current_user, login_required
import secrets


# ==================== 权限常量 ====================
PERMISSION_MANAGE_JOBS = 'can_manage_jobs'
PERMISSION_MANAGE_STUDENTS = 'can_manage_students'
PERMISSION_MANAGE_ACCOUNTS = 'can_manage_accounts'
PERMISSION_PUSH_JOBS = 'can_push_jobs'


# ==================== 基础装饰器 ====================
def admin_required(f):
    """必须是管理员登录"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            flash('无权访问，仅管理员可操作', 'danger')
            return redirect(url_for('auth.login'))
        if not current_user.is_active:
            flash('账号已被禁用', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    """必须是学员登录"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_student():
            flash('无权访问，仅学员账号可操作', 'danger')
            return redirect(url_for('auth.login'))
        if not current_user.is_active:
            flash('账号已被禁用', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def permission_required(permission):
    """检查特定权限（用于管理员子账号）"""
    def decorator(f):
        @wraps(f)
        @admin_required
        def decorated_function(*args, **kwargs):
            # 超级管理员（admin）拥有所有权限
            if current_user.username == 'admin':
                return f(*args, **kwargs)
            if not getattr(current_user, permission, False):
                flash('您没有此操作的权限，请联系管理员', 'danger')
                return redirect(url_for('admin.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== CSRF保护 ====================
def init_csrf():
    """初始化CSRF令牌"""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


def check_csrf():
    """检查CSRF令牌（跳过GET请求和JSON请求）"""
    if request.method == 'POST':
        # 跳过API请求
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if token != session.get('csrf_token'):
            abort(403)


# ==================== 权限检查函数 ====================
def has_permission(user, permission):
    """检查用户是否有某权限"""
    if user.username == 'admin':
        return True
    return getattr(user, permission, False)


def get_user_permissions(user):
    """获取用户所有权限列表"""
    if user.username == 'admin':
        return [PERMISSION_MANAGE_JOBS, PERMISSION_MANAGE_STUDENTS, 
                PERMISSION_MANAGE_ACCOUNTS, PERMISSION_PUSH_JOBS]
    permissions = []
    if user.can_manage_jobs:
        permissions.append(PERMISSION_MANAGE_JOBS)
    if user.can_manage_students:
        permissions.append(PERMISSION_MANAGE_STUDENTS)
    if user.can_manage_accounts:
        permissions.append(PERMISSION_MANAGE_ACCOUNTS)
    if user.can_push_jobs:
        permissions.append(PERMISSION_PUSH_JOBS)
    return permissions


def can_access_menu(user, menu):
    """检查用户是否可以访问某个菜单"""
    menu_permissions = {
        'dashboard': True,
        'jobs': PERMISSION_MANAGE_JOBS,
        'students': PERMISSION_MANAGE_STUDENTS,
        'push': PERMISSION_PUSH_JOBS,
        'accounts': PERMISSION_MANAGE_ACCOUNTS,
        'logs': PERMISSION_MANAGE_ACCOUNTS,
    }
    required_permission = menu_permissions.get(menu)
    if required_permission is None:
        return False
    if required_permission is True:
        return True
    return has_permission(user, required_permission)
