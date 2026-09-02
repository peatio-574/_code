from flask import render_template, redirect, url_for, flash, request, jsonify, send_file, session
from flask_login import login_required, current_user
from ..models import db, User, Job, PushRecord, OperationLog
from ..permissions import (
    admin_required, permission_required, init_csrf,
    PERMISSION_MANAGE_JOBS, PERMISSION_MANAGE_STUDENTS, 
    PERMISSION_MANAGE_ACCOUNTS, PERMISSION_PUSH_JOBS,
    get_user_permissions, can_access_menu
)
from . import admin_bp
from datetime import datetime
import openpyxl
import io


def log_operation(action, target_type='', target_id=0, details=''):
    log = OperationLog(
        user_id=current_user.id, action=action, target_type=target_type,
        target_id=target_id, details=details, ip_address=request.remote_addr
    )
    db.session.add(log)


@admin_bp.before_request
def before_request():
    init_csrf()


def get_template_context():
    return {
        'csrf_token': session.get('csrf_token'),
        'user_permissions': get_user_permissions(current_user) if current_user.is_authenticated else [],
        'can_access_menu': lambda menu: can_access_menu(current_user, menu) if current_user.is_authenticated else False
    }


# ==================== 仪表盘 ====================
@admin_bp.route('/')
@admin_required
def dashboard():
    ctx = get_template_context()
    ctx['total_jobs'] = Job.query.filter_by(status='active').count()
    ctx['total_students'] = User.query.filter_by(user_type='student', is_active=True).count()
    ctx['total_pushes'] = PushRecord.query.count()
    ctx['recent_pushes'] = PushRecord.query.order_by(PushRecord.pushed_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html', **ctx)


# ==================== 岗位管理 ====================
@admin_bp.route('/jobs')
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def jobs_list():
    ctx = get_template_context()
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '')
    education = request.args.get('education', '')
    major = request.args.get('major', '')
    party_member = request.args.get('party_member', '')
    location = request.args.get('location', '')
    company_type = request.args.get('company_type', '')
    status = request.args.get('status', '')
    query = Job.query
    if keyword:
        query = query.filter(db.or_(Job.company_name.contains(keyword), Job.job_name.contains(keyword)))
    if education:
        query = query.filter(Job.education_req == education)
    if major:
        query = query.filter(Job.major_req.contains(major))
    if party_member == '1':
        query = query.filter(Job.party_member_req == True)
    if location:
        query = query.filter(Job.work_location.contains(location))
    if company_type:
        query = query.filter(Job.tags.contains(company_type))
    if status:
        query = query.filter(Job.status == status)
    pagination = query.order_by(Job.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    ctx.update(jobs=pagination.items, pagination=pagination, keyword=keyword, education=education,
               major=major, party_member=party_member, location=location, company_type=company_type, status=status)
    return render_template('admin/jobs_list.html', **ctx)


@admin_bp.route('/jobs/add', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def job_add():
    ctx = get_template_context()
    if request.method == 'POST':
        job = Job(
            company_name=request.form.get('company_name', ''), job_name=request.form.get('job_name', ''),
            education_req=request.form.get('education_req', ''), major_req=request.form.get('major_req', ''),
            certificate_req=request.form.get('certificate_req', ''),
            party_member_req=bool(request.form.get('party_member_req')),
            work_location=request.form.get('work_location', ''),
            recruit_count=int(request.form.get('recruit_count', 1)),
            deadline=datetime.strptime(request.form['deadline'], '%Y-%m-%d') if request.form.get('deadline') else None,
            job_detail=request.form.get('job_detail', ''), tags=request.form.get('tags', ''),
            created_by=current_user.id
        )
        db.session.add(job)
        log_operation('add_job', 'job', 0, f'新增岗位：{job.job_name}')
        db.session.commit()
        flash('岗位添加成功', 'success')
        return redirect(url_for('admin.jobs_list'))
    return render_template('admin/job_form.html', **ctx)


@admin_bp.route('/jobs/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def job_edit(id):
    ctx = get_template_context()
    job = Job.query.get_or_404(id)
    if request.method == 'POST':
        job.company_name = request.form.get('company_name', '')
        job.job_name = request.form.get('job_name', '')
        job.education_req = request.form.get('education_req', '')
        job.major_req = request.form.get('major_req', '')
        job.certificate_req = request.form.get('certificate_req', '')
        job.party_member_req = bool(request.form.get('party_member_req'))
        job.work_location = request.form.get('work_location', '')
        job.recruit_count = int(request.form.get('recruit_count', 1))
        job.deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%d') if request.form.get('deadline') else None
        job.job_detail = request.form.get('job_detail', '')
        job.tags = request.form.get('tags', '')
        log_operation('edit_job', 'job', job.id, f'编辑岗位：{job.job_name}')
        db.session.commit()
        flash('岗位更新成功', 'success')
        return redirect(url_for('admin.jobs_list'))
    ctx['job'] = job
    return render_template('admin/job_form.html', **ctx)


@admin_bp.route('/jobs/delete', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def job_delete():
    ids = request.form.getlist('job_ids')
    if ids:
        jobs = Job.query.filter(Job.id.in_(ids)).all()
        for job in jobs:
            log_operation('delete_job', 'job', job.id, f'删除岗位：{job.job_name}')
            PushRecord.query.filter_by(job_id=job.id).delete()
        Job.query.filter(Job.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f'成功删除 {len(jobs)} 个岗位', 'success')
    return redirect(url_for('admin.jobs_list'))


@admin_bp.route('/jobs/toggle_status', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def job_toggle_status():
    ids = request.form.getlist('job_ids')
    action = request.form.get('action', 'activate')
    if ids:
        new_status = 'active' if action == 'activate' else 'inactive'
        jobs = Job.query.filter(Job.id.in_(ids)).all()
        for job in jobs:
            job.status = new_status
            log_operation('toggle_job_status', 'job', job.id, f'{"上架" if new_status == "active" else "下架"}岗位：{job.job_name}')
        db.session.commit()
        flash(f'成功操作 {len(jobs)} 个岗位', 'success')
    return redirect(url_for('admin.jobs_list'))


@admin_bp.route('/jobs/import', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def job_import():
    ctx = get_template_context()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('请选择文件', 'danger')
            return render_template('admin/job_import.html', **ctx)
        if not file.filename.endswith(('.xlsx', '.xls')):
            flash('请上传Excel文件', 'danger')
            return render_template('admin/job_import.html', **ctx)
        try:
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            count = 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row[0]:
                    continue
                job = Job(
                    company_name=str(row[0] or ''), job_name=str(row[1] or ''),
                    education_req=str(row[2] or ''), major_req=str(row[3] or ''),
                    certificate_req=str(row[4] or ''),
                    party_member_req=str(row[5] or '').lower() in ('是', 'yes', 'true', '1'),
                    work_location=str(row[6] or ''), recruit_count=int(row[7] or 1),
                    deadline=datetime.strptime(str(row[8]), '%Y-%m-%d') if row[8] else None,
                    job_detail=str(row[9] or ''), tags=str(row[10] or ''), created_by=current_user.id
                )
                db.session.add(job)
                count += 1
            log_operation('import_jobs', 'job', 0, f'批量导入 {count} 个岗位')
            db.session.commit()
            flash(f'成功导入 {count} 个岗位', 'success')
            return redirect(url_for('admin.jobs_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'导入失败：{str(e)}', 'danger')
    return render_template('admin/job_import.html', **ctx)


@admin_bp.route('/jobs/template')
@admin_required
@permission_required(PERMISSION_MANAGE_JOBS)
def job_template():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '岗位导入模板'
    ws.append(['单位名称', '岗位名称', '学历要求', '专业要求', '证书要求', '党员要求(是/否)',
               '工作地点', '招录人数', '报名截止时间(YYYY-MM-DD)', '岗位详情', '岗位标签'])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='岗位导入模板.xlsx')


# ==================== 用户管理（学员+子账号统一） ====================
@admin_bp.route('/users')
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def users_list():
    ctx = get_template_context()
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '')
    user_type = request.args.get('user_type', '')
    query = User.query
    if user_type:
        query = query.filter_by(user_type=user_type)
    else:
        query = query.filter(User.user_type.in_(['student', 'admin']))
    if keyword:
        query = query.filter(db.or_(
            User.username.contains(keyword), User.real_name.contains(keyword),
            User.phone.contains(keyword)
        ))
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    ctx.update(users=pagination.items, pagination=pagination, keyword=keyword, user_type=user_type)
    return render_template('admin/users_list.html', **ctx)


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def user_add():
    ctx = get_template_context()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return render_template('admin/user_form.html', **ctx)
        password = request.form.get('password', '123456')
        user_type = request.form.get('user_type', 'student')
        user = User(
            username=username, user_type=user_type,
            real_name=request.form.get('real_name', ''),
            phone=request.form.get('phone', ''),
            email=request.form.get('email', ''),
            education=request.form.get('education', ''),
            major=request.form.get('major', ''),
            is_party_member=bool(request.form.get('is_party_member')),
            intention_city=request.form.get('intention_city', ''),
            certificate=request.form.get('certificate', ''),
            can_manage_jobs=bool(request.form.get('can_manage_jobs')),
            can_manage_students=bool(request.form.get('can_manage_students')),
            can_manage_accounts=bool(request.form.get('can_manage_accounts')),
            can_push_jobs=bool(request.form.get('can_push_jobs'))
        )
        user.set_password(password)
        db.session.add(user)
        log_operation('add_user', 'user', 0, f'新增用户：{username}（{user_type}）')
        db.session.commit()
        flash('用户添加成功', 'success')
        return redirect(url_for('admin.users_list'))
    return render_template('admin/user_form.html', **ctx)


@admin_bp.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def user_edit(id):
    ctx = get_template_context()
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.real_name = request.form.get('real_name', '')
        user.phone = request.form.get('phone', '')
        user.email = request.form.get('email', '')
        user.education = request.form.get('education', '')
        user.major = request.form.get('major', '')
        user.is_party_member = bool(request.form.get('is_party_member'))
        user.intention_city = request.form.get('intention_city', '')
        user.certificate = request.form.get('certificate', '')
        user.can_manage_jobs = bool(request.form.get('can_manage_jobs'))
        user.can_manage_students = bool(request.form.get('can_manage_students'))
        user.can_manage_accounts = bool(request.form.get('can_manage_accounts'))
        user.can_push_jobs = bool(request.form.get('can_push_jobs'))
        new_password = request.form.get('password', '')
        if new_password:
            user.set_password(new_password)
        log_operation('edit_user', 'user', user.id, f'编辑用户：{user.username}')
        db.session.commit()
        flash('用户信息更新成功', 'success')
        return redirect(url_for('admin.users_list'))
    ctx['user_obj'] = user
    return render_template('admin/user_form.html', **ctx)


@admin_bp.route('/users/delete', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def user_delete():
    ids = request.form.getlist('user_ids')
    if ids:
        # 不能删除自己
        if str(current_user.id) in ids:
            flash('不能删除自己的账号', 'danger')
            return redirect(url_for('admin.users_list'))
        users = User.query.filter(User.id.in_(ids)).all()
        for user in users:
            # 删除关联的推送记录
            PushRecord.query.filter_by(student_id=user.id).delete()
            PushRecord.query.filter_by(pushed_by=user.id).delete()
            log_operation('delete_user', 'user', user.id, f'删除用户：{user.username}')
        User.query.filter(User.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f'成功删除 {len(users)} 个用户', 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/toggle_status', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def user_toggle_status():
    id = request.form.get('user_id')
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('不能禁用自己的账号', 'danger')
        return redirect(url_for('admin.users_list'))
    user.is_active = not user.is_active
    status_text = '启用' if user.is_active else '禁用'
    log_operation('toggle_user_status', 'user', user.id, f'{status_text}用户：{user.username}')
    db.session.commit()
    flash(f'用户已{status_text}', 'success')
    return redirect(url_for('admin.users_list'))


# ==================== 推送管理 ====================
@admin_bp.route('/push')
@admin_required
@permission_required(PERMISSION_PUSH_JOBS)
def push_list():
    ctx = get_template_context()
    page = request.args.get('page', 1, type=int)
    pagination = PushRecord.query.order_by(PushRecord.pushed_at.desc()).paginate(page=page, per_page=20, error_out=False)
    ctx.update(pushes=pagination.items, pagination=pagination)
    return render_template('admin/push_list.html', **ctx)


@admin_bp.route('/push/do', methods=['POST'])
@admin_required
@permission_required(PERMISSION_PUSH_JOBS)
def push_do():
    job_ids = request.form.getlist('job_ids')
    student_ids = request.form.getlist('student_ids')
    if not job_ids or not student_ids:
        flash('请选择岗位和学员', 'danger')
        return redirect(url_for('admin.jobs_list'))
    count = 0
    for job_id in job_ids:
        for student_id in student_ids:
            existing = PushRecord.query.filter_by(job_id=int(job_id), student_id=int(student_id)).first()
            if not existing:
                push = PushRecord(job_id=int(job_id), student_id=int(student_id), pushed_by=current_user.id)
                db.session.add(push)
                count += 1
    log_operation('push_jobs', 'push', 0, f'推送 {len(job_ids)} 个岗位给 {len(student_ids)} 个学员')
    db.session.commit()
    flash(f'成功推送 {count} 条记录', 'success')
    return redirect(url_for('admin.push_list'))


# ==================== 操作日志 ====================
@admin_bp.route('/logs')
@admin_required
@permission_required(PERMISSION_MANAGE_ACCOUNTS)
def logs_list():
    ctx = get_template_context()
    page = request.args.get('page', 1, type=int)
    user_id = request.args.get('user_id', '', type=str)
    action = request.args.get('action', '')
    query = OperationLog.query
    if user_id:
        query = query.filter_by(user_id=int(user_id))
    if action:
        query = query.filter_by(action=action)
    pagination = query.order_by(OperationLog.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    ctx.update(logs=pagination.items, pagination=pagination, user_id=user_id, action=action)
    return render_template('admin/logs_list.html', **ctx)


# ==================== API ====================
@admin_bp.route('/students/list_json')
@admin_required
@permission_required(PERMISSION_PUSH_JOBS)
def students_list_json():
    students = User.query.filter_by(user_type='student', is_active=True).all()
    return jsonify([{'id': s.id, 'username': s.username, 'real_name': s.real_name} for s in students])
