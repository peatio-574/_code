import time
from flask import render_template, redirect, url_for, flash, request, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from ..models import db, User, OperationLog
from ..permissions import init_csrf
from . import auth_bp


# ==================== 登录失败限流（进程内） ====================
# 同一「IP+用户名」连续失败达到阈值后锁定一段时间，防止暴力破解。
# 注意：为进程内存储，多 worker 下各进程独立计数（仅作基础防护）。
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60
_login_failures = {}


def _login_locked(key):
    rec = _login_failures.get(key)
    if not rec:
        return False
    if rec[1] and rec[1] > time.time():
        return True
    if rec[1] and rec[1] <= time.time():
        _login_failures.pop(key, None)
    return False


def _record_login_failure(key):
    rec = _login_failures.get(key)
    if not rec or (rec[1] and rec[1] <= time.time()):
        rec = [0, 0]
    rec[0] += 1
    if rec[0] >= LOGIN_MAX_FAILURES:
        rec[1] = time.time() + LOGIN_LOCK_SECONDS
    _login_failures[key] = rec


def _clear_login_failure(key):
    _login_failures.pop(key, None)


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

        throttle_key = (request.remote_addr or '') + '|' + username
        if _login_locked(throttle_key):
            flash('登录失败次数过多，请 15 分钟后再试', 'danger')
            return render_template('auth/login.html', csrf_token=csrf_token)

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            _record_login_failure(throttle_key)
            flash('用户名或密码错误', 'danger')
            return render_template('auth/login.html', csrf_token=csrf_token)

        if not user.is_active:
            flash('账号已被禁用', 'danger')
            return render_template('auth/login.html', csrf_token=csrf_token)

        _clear_login_failure(throttle_key)
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
        if next_page and not (next_page.startswith('/') and not next_page.startswith('//')):
            next_page = None
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


@auth_bp.route('/profile', methods=['POST'])
@login_required
def update_profile():
    """更新当前登录账号的个人资料"""
    editable = ['real_name', 'email', 'gender']
    if current_user.user_type == 'student':
        editable += ['education', 'major', 'intention_city', 'political_status',
                     'first_intention', 'second_intention', 'third_intention',
                     'certificate', 'remark', 'origin_place']

    for field in editable:
        val = request.form.get(field)
        if val is not None:
            setattr(current_user, field, str(val).strip())

    # 手机号单独处理：学员的手机号即登录账号，需同步更新并查重
    phone_val = request.form.get('phone')
    if phone_val is not None:
        new_phone = str(phone_val).strip()
        if new_phone and new_phone != (current_user.phone or ''):
            exists = User.query.filter(
                User.username == new_phone,
                User.id != current_user.id,
                User.is_deleted == False).first()
            if exists:
                return jsonify({'success': False, 'message': '该手机号已被其他账号使用'})
            current_user.phone = new_phone
            if current_user.is_student():
                current_user.username = new_phone
        elif new_phone:
            current_user.phone = new_phone

    id_card = str(request.form.get('id_card', '')).strip()
    if current_user.user_type == 'student' and id_card:
        current_user.id_card = id_card
        gender, birth_date, age = current_user.parse_id_card(id_card)
        if gender:
            current_user.gender = gender
        if birth_date:
            current_user.birth_date = birth_date

    graduation_date = str(request.form.get('graduation_date', '')).strip()
    if current_user.user_type == 'student':
        try:
            current_user.graduation_date = datetime.strptime(graduation_date, '%Y-%m-%d').date() if graduation_date else None
        except ValueError:
            pass

    db.session.commit()

    log = OperationLog(
        user_id=current_user.id,
        action='edit_profile',
        target_type='user',
        target_id=current_user.id,
        details='用户更新了个人资料',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '资料保存成功'})
