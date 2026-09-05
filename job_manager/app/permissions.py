from functools import wraps
from flask import flash, redirect, url_for, session, jsonify, request
from flask_login import current_user
import secrets


# ==================== 权限常量 ====================
PERMISSION_MANAGE_STUDENTS = 'can_manage_students'
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
        return [PERMISSION_MANAGE_STUDENTS, PERMISSION_PUSH_JOBS]
    permissions = []
    if getattr(user, 'can_manage_students', False):
        permissions.append(PERMISSION_MANAGE_STUDENTS)
    if getattr(user, 'can_push_jobs', False):
        permissions.append(PERMISSION_PUSH_JOBS)
    return permissions


def can_access_menu(user, menu):
    menu_permissions = {
        'dashboard': True,
        'jobs': True,
        'students': PERMISSION_MANAGE_STUDENTS,
        'push': PERMISSION_PUSH_JOBS,
        'accounts': True,
        'logs': True,
    }
    required_permission = menu_permissions.get(menu)
    if required_permission is None:
        return False
    if required_permission is True:
        return True
    return has_permission(user, required_permission)


# ==================== 校区权限校验 ====================
def get_campus_filter():
    """获取当前用户的校区过滤条件，超管返回None表示不过滤"""
    if current_user.is_super_admin():
        return None
    return current_user.campus_id


def validate_campus_access(campus_id):
    """校验用户是否有权访问指定校区数据，返回(True, None)或(False, 错误响应)"""
    if current_user.is_super_admin():
        return True, None
    if campus_id != current_user.campus_id:
        msg = '无权访问其他校区数据'
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return False, jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return False, redirect(url_for('admin.dashboard'))
    return True, None


def validate_object_campus(obj):
    """校验用户是否有权操作指定对象（根据对象的campus_id），返回(True, None)或(False, 错误响应)"""
    if current_user.is_super_admin():
        return True, None
    obj_campus_id = getattr(obj, 'campus_id', None)
    if obj_campus_id != current_user.campus_id:
        msg = '无权操作其他校区数据'
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return False, jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return False, redirect(url_for('admin.dashboard'))
    return True, None
