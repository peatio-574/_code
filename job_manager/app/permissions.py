from functools import wraps
from flask import flash, redirect, url_for, session
from flask_login import current_user
import secrets


# ==================== 权限常量 ====================
PERMISSION_MANAGE_JOBS = 'can_manage_jobs'
PERMISSION_MANAGE_STUDENTS = 'can_manage_students'
PERMISSION_MANAGE_ACCOUNTS = 'can_manage_accounts'
PERMISSION_PUSH_JOBS = 'can_push_jobs'


# ==================== 角色检查装饰器 ====================
def super_admin_required(f):
    """必须是超级管理员"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin():
            flash('无权访问，仅超级管理员可操作', 'danger')
            return redirect(url_for('auth.login'))
        if not current_user.is_active:
            flash('账号已被禁用', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """必须是管理员（包括超级管理员）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('无权访问，仅管理员可操作', 'danger')
            return redirect(url_for('auth.login'))
        if not current_user.is_active:
            flash('账号已被禁用', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    """必须是学员"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student():
            flash('无权访问，仅学员账号可操作', 'danger')
            return redirect(url_for('auth.login'))
        if not current_user.is_active:
            flash('账号已被禁用', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def permission_required(permission):
    """检查特定权限"""
    def decorator(f):
        @wraps(f)
        @admin_required
        def decorated_function(*args, **kwargs):
            if current_user.is_super_admin():
                return f(*args, **kwargs)
            if not getattr(current_user, permission, False):
                flash('您没有此操作的权限', 'danger')
                return redirect(url_for('admin.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== CSRF ====================
def init_csrf():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


# ==================== 权限检查函数 ====================
def has_permission(user, permission):
    if user.is_super_admin():
        return True
    return getattr(user, permission, False)


def get_user_permissions(user):
    if user.is_super_admin():
        return [PERMISSION_MANAGE_JOBS, PERMISSION_MANAGE_STUDENTS, 
                PERMISSION_MANAGE_ACCOUNTS, PERMISSION_PUSH_JOBS]
    permissions = []
    if getattr(user, 'can_manage_jobs', False):
        permissions.append(PERMISSION_MANAGE_JOBS)
    if getattr(user, 'can_manage_students', False):
        permissions.append(PERMISSION_MANAGE_STUDENTS)
    if getattr(user, 'can_manage_accounts', False):
        permissions.append(PERMISSION_MANAGE_ACCOUNTS)
    if getattr(user, 'can_push_jobs', False):
        permissions.append(PERMISSION_PUSH_JOBS)
    return permissions


def can_access_menu(user, menu):
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
