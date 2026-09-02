from flask import Blueprint, redirect, url_for, flash
from flask_login import current_user

student_bp = Blueprint('student', __name__, template_folder='../templates/student')


@student_bp.before_request
def ensure_student():
    """确保只有学员可以访问所有student路由"""
    # 如果不是学员，重定向
    if not current_user.is_authenticated:
        flash('请先登录', 'warning')
        return redirect(url_for('auth.login'))
    
    if not current_user.is_student():
        flash('无权访问学员端', 'danger')
        return redirect(url_for('auth.login'))
    
    if not current_user.is_active:
        flash('账号已被禁用', 'danger')
        return redirect(url_for('auth.login'))


from . import routes
