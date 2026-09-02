from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from ..models import db, User, OperationLog
from ..permissions import init_csrf
from . import auth_bp


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('student.my_pushes'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    csrf_token = init_csrf()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('用户名或密码错误', 'danger')
            return render_template('auth/login.html', csrf_token=csrf_token)

        if not user.is_active:
            flash('账号已被禁用', 'danger')
            return render_template('auth/login.html', csrf_token=csrf_token)

        login_user(user, remember=bool(remember))

        # 记录登录日志
        log = OperationLog(
            user_id=user.id,
            action='login',
            target_type='user',
            target_id=user.id,
            details=f'用户 {username} 登录系统',
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()

        next_page = request.args.get('next')
        if user.is_admin():
            return redirect(next_page or url_for('admin.dashboard'))
        return redirect(next_page or url_for('student.my_pushes'))

    return render_template('auth/login.html', csrf_token=csrf_token)


@auth_bp.route('/logout')
@login_required
def logout():
    # 记录登出日志
    log = OperationLog(
        user_id=current_user.id,
        action='logout',
        target_type='user',
        target_id=current_user.id,
        details=f'用户 {current_user.username} 登出系统',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

    logout_user()
    flash('已安全退出', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    csrf_token = init_csrf()

    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(old_password):
            flash('原密码错误', 'danger')
            return render_template('auth/change_password.html', csrf_token=csrf_token)

        if new_password != confirm_password:
            flash('两次输入的密码不一致', 'danger')
            return render_template('auth/change_password.html', csrf_token=csrf_token)

        if len(new_password) < 6:
            flash('密码长度不能少于6位', 'danger')
            return render_template('auth/change_password.html', csrf_token=csrf_token)

        current_user.set_password(new_password)
        db.session.commit()

        log = OperationLog(
            user_id=current_user.id,
            action='change_password',
            target_type='user',
            target_id=current_user.id,
            details='用户修改了密码',
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()

        flash('密码修改成功', 'success')
        return redirect(url_for('auth.index'))

    return render_template('auth/change_password.html', csrf_token=csrf_token)
