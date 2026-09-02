from flask import Blueprint, redirect, url_for, flash, session
from flask_login import current_user

admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')


@admin_bp.before_request
def ensure_admin():
    """确保只有管理员可以访问所有admin路由"""
    # 公开路由列表（不需要登录检查的路由）
    public_endpoints = []
    
    # 如果不是管理员，重定向到登录页
    if not current_user.is_authenticated:
        flash('请先登录', 'warning')
        return redirect(url_for('auth.login'))
    
    if not current_user.is_admin():
        flash('无权访问管理后台', 'danger')
        return redirect(url_for('auth.login'))
    
    if not current_user.is_active:
        flash('账号已被禁用', 'danger')
        return redirect(url_for('auth.login'))


from . import routes
