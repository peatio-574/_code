from flask import render_template, redirect, url_for, flash, request, jsonify, send_file, session
from flask_login import login_required, current_user
from sqlalchemy.orm import aliased
from ..models import db, User, Job, PushRecord, OperationLog, Campus, Role, ResumeAnalysisLog
from ..utils.ai_service import analyze_resume, extract_resume_text, extract_candidate_name, screen_jobs
from ..permissions import (
    super_admin_required, admin_required, permission_required, init_csrf,
    PERMISSION_MANAGE_STUDENTS, PERMISSION_PUSH_JOBS, PERMISSION_AI_RECOGNITION,
    get_user_permissions, can_access_menu,
    get_campus_filter, validate_object_campus
)
from . import admin_bp
from datetime import datetime
import openpyxl
import io


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_strptime(date_str, fmt='%Y-%m-%d %H:%M:%S'):
    try:
        return datetime.strptime(date_str, fmt) if date_str else None
    except (ValueError, TypeError):
        return None


def is_valid_phone(phone):
    """校验手机号：11位，1开头，纯数字"""
    phone = (phone or '').strip()
    import re
    if len(phone) != 11:
        return False
    if not phone.isdigit():
        return False
    if not phone.startswith('1'):
        return False
    return True


def log_operation(action, target_type='', target_id=0, details=''):
    log = OperationLog(
        user_id=current_user.id, action=action,
        target_type=target_type, target_id=target_id, details=details,
        ip_address=request.remote_addr
    )
    db.session.add(log)


def _is_ajax():
    """判断是否为 AJAX 请求"""
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.args.get('ajax') == '1')


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
    from datetime import datetime, date
    
    campus_filter = get_campus_filter()
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    if campus_filter is None:
        # 超管：未过期岗位数、学生总数、推送记录
        from sqlalchemy import or_
        ctx['total_jobs'] = Job.query.filter(
            Job.is_deleted == False, Job.status == 'active',
            or_(Job.deadline == None, Job.deadline >= datetime.now())
        ).count()
        ctx['total_students'] = User.query.filter_by(user_type='student', is_active=True, is_deleted=False).count()
        ctx['total_pushes'] = PushRecord.query.filter_by(is_deleted=False).count()
        ctx['today_pushes'] = PushRecord.query.filter(PushRecord.is_deleted == False, PushRecord.pushed_at >= today_start).count()
        ctx['recent_pushes'] = PushRecord.query.filter_by(is_deleted=False).order_by(PushRecord.pushed_at.desc()).limit(10).all()
    else:
        # 管理员：未过期岗位数、学生总数、推送记录、当日推送
        from sqlalchemy import or_
        ctx['total_jobs'] = Job.query.filter(
            Job.is_deleted == False, Job.status == 'active',
            or_(Job.deadline == None, Job.deadline >= datetime.now())
        ).count()
        ctx['total_students'] = User.query.filter_by(user_type='student', is_active=True, is_deleted=False, campus_id=campus_filter).count()
        ctx['total_pushes'] = PushRecord.query.filter_by(is_deleted=False).join(User, PushRecord.student_id == User.id).filter(User.campus_id == campus_filter).count()
        ctx['today_pushes'] = PushRecord.query.filter(PushRecord.is_deleted == False, PushRecord.pushed_at >= today_start).join(User, PushRecord.student_id == User.id).filter(User.campus_id == campus_filter).count()
        ctx['recent_pushes'] = PushRecord.query.filter_by(is_deleted=False).join(User, PushRecord.student_id == User.id).filter(User.campus_id == campus_filter).order_by(PushRecord.pushed_at.desc()).limit(10).all()
    
    return render_template('admin/dashboard.html', **ctx)


# ==================== 校区管理（超管） ====================
@admin_bp.route('/campuses/page')
@admin_required
@super_admin_required
def campuses_page():
    """校区管理页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    return render_template('admin/campuses_list.html', **ctx)


@admin_bp.route('/campuses')
@admin_required
@super_admin_required
def campuses_list():
    """校区管理数据接口：返回JSON数据，前端负责渲染（支持搜索+分页）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    keyword = request.args.get('keyword', '')
    
    if per_page not in [20, 50, 100]:
        per_page = 20
    
    query = Campus.query.filter_by(is_deleted=False)
    if keyword:
        query = query.filter(Campus.name.contains(keyword))
    
    pagination = query.order_by(Campus.name.asc()).paginate(page=page, per_page=per_page, error_out=False)
    
    data = []
    for campus in pagination.items:
        admin_count = User.query.filter_by(campus_id=campus.id, user_type='admin', is_deleted=False).count()
        student_count = User.query.filter_by(campus_id=campus.id, user_type='student', is_deleted=False).count()
        data.append({
            'id': campus.id,
            'name': campus.name,
            'address': campus.address,
            'manager': campus.manager,
            'contact': campus.contact,
            'admin_count': admin_count,
            'student_count': student_count,
            'is_active': campus.is_active,
            'created_at': campus.created_at.strftime('%Y-%m-%d %H:%M') if campus.created_at else '-',
            'updated_at': campus.updated_at.strftime('%Y-%m-%d %H:%M') if campus.updated_at else '-'
        })
    
    return jsonify({
        'success': True,
        'campuses': data,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


@admin_bp.route('/campuses/add', methods=['POST'])
@admin_required
@super_admin_required
def campus_add():
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    manager = request.form.get('manager', '').strip()
    contact = request.form.get('contact', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '校区名称不能为空'})
    if Campus.query.filter_by(name=name, is_deleted=False).first():
        return jsonify({'success': False, 'message': '校区名称已存在'})
    campus = Campus(name=name, address=address, manager=manager, contact=contact)
    db.session.add(campus)
    log_operation('add_campus', 'campus', 0, f'新增校区：{name}')
    db.session.commit()
    return jsonify({'success': True, 'message': '校区添加成功'})


@admin_bp.route('/campuses/toggle-status', methods=['POST'])
@admin_required
@super_admin_required
def campus_toggle_status():
    campus_id = request.form.get('campus_id')
    campus = Campus.query.get_or_404(campus_id)
    campus.is_active = not campus.is_active
    status_text = '启用' if campus.is_active else '禁用'
    
    # 校区禁用时，禁用该校区下所有管理员和学员；校区启用时，启用该校区下所有管理员和学员
    users = User.query.filter_by(campus_id=campus.id, is_deleted=False).all()
    for user in users:
        user.is_active = campus.is_active
    
    log_operation('toggle_campus_status', 'campus', campus.id, f'校区{status_text}：{campus.name}，影响 {len(users)} 个用户')
    db.session.commit()
    return jsonify({'success': True, 'message': f'校区已{status_text}，{status_text} {len(users)} 个用户'})


@admin_bp.route('/campuses/delete', methods=['POST'])
@admin_required
@super_admin_required
def campus_delete():
    campus_ids = request.form.getlist('campus_ids')
    if campus_ids:
        # 批量删除
        for cid in campus_ids:
            campus = Campus.query.get(cid)
            if campus:
                campus.is_deleted = True
                log_operation('delete_campus', 'campus', campus.id, f'删除校区：{campus.name}')
    else:
        # 单个删除（兼容旧逻辑）
        campus_id = request.form.get('campus_id')
        campus = Campus.query.get_or_404(campus_id)
        campus.is_deleted = True
        log_operation('delete_campus', 'campus', campus.id, f'删除校区：{campus.name}')
    db.session.commit()
    return jsonify({'success': True, 'message': '校区删除成功'})


@admin_bp.route('/campuses/edit', methods=['POST'])
@admin_required
@super_admin_required
def campus_edit():
    campus_id = request.form.get('campus_id')
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    manager = request.form.get('manager', '').strip()
    contact = request.form.get('contact', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '校区名称不能为空'})
    
    campus = Campus.query.get_or_404(campus_id)
    existing = Campus.query.filter(Campus.name == name, Campus.id != campus_id, Campus.is_deleted==False).first()
    if existing:
        return jsonify({'success': False, 'message': '校区名称已存在'})
    
    old_name = campus.name
    campus.name = name
    campus.address = address
    campus.manager = manager
    campus.contact = contact
    log_operation('edit_campus', 'campus', campus.id, f'编辑校区：{old_name} → {name}')
    db.session.commit()
    return jsonify({'success': True, 'message': '校区更新成功'})


# ==================== 角色管理（超管） ====================
@admin_bp.route('/roles/page')
@admin_required
@super_admin_required
def roles_page():
    """角色管理页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    return render_template('admin/roles_list.html', **ctx)


@admin_bp.route('/roles')
@admin_required
@super_admin_required
def roles_list():
    """角色管理数据接口：返回JSON数据，前端负责渲染（支持搜索+分页）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    keyword = request.args.get('keyword', '')
    
    if per_page not in [20, 50, 100]:
        per_page = 20
    
    query = Role.query.filter_by(is_deleted=False)
    if keyword:
        query = query.filter(Role.name.contains(keyword))
    
    pagination = query.order_by(Role.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    data = []
    for role in pagination.items:
        user_count = User.query.filter_by(role=role.name, is_deleted=False).count()
        data.append({
            'id': role.id,
            'name': role.name,
            'user_count': user_count,
            'is_active': role.is_active,
            'created_at': role.created_at.strftime('%Y-%m-%d %H:%M') if role.created_at else '-',
            'updated_at': role.updated_at.strftime('%Y-%m-%d %H:%M') if role.updated_at else '-'
        })
    
    return jsonify({
        'success': True,
        'roles': data,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


@admin_bp.route('/roles/add', methods=['POST'])
@admin_required
@super_admin_required
def role_add():
    name = request.form.get('name', '').strip()
    is_active = request.form.get('is_active') == '1'
    if not name:
        return jsonify({'success': False, 'message': '角色名称不能为空'})
    if Role.query.filter_by(name=name, is_deleted=False).first():
        return jsonify({'success': False, 'message': '角色名称已存在'})
    role = Role(name=name, is_active=is_active)
    db.session.add(role)
    log_operation('add_role', 'role', 0, f'新增角色：{name}')
    db.session.commit()
    return jsonify({'success': True, 'message': '角色添加成功'})


@admin_bp.route('/roles/delete', methods=['POST'])
@admin_required
@super_admin_required
def role_delete():
    role_id = request.form.get('role_id')
    role = Role.query.get_or_404(role_id)
    role.is_deleted = True
    log_operation('delete_role', 'role', role.id, f'删除角色：{role.name}')
    db.session.commit()
    return jsonify({'success': True, 'message': '角色删除成功'})


@admin_bp.route('/roles/toggle-status', methods=['POST'])
@admin_required
@super_admin_required
def role_toggle_status():
    role_id = request.form.get('role_id')
    role = Role.query.get_or_404(role_id)
    role.is_active = not role.is_active
    status_text = '启用' if role.is_active else '禁用'
    log_operation('toggle_role_status', 'role', role.id, f'角色{status_text}：{role.name}')
    db.session.commit()
    return jsonify({'success': True, 'message': f'角色已{status_text}'})


@admin_bp.route('/roles/edit', methods=['POST'])
@admin_required
@super_admin_required
def role_edit():
    role_id = request.form.get('role_id')
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '角色名称不能为空'})
    
    role = Role.query.get_or_404(role_id)
    existing = Role.query.filter(Role.name == name, Role.id != role_id, Role.is_deleted==False).first()
    if existing:
        return jsonify({'success': False, 'message': '角色名称已存在'})
    
    old_name = role.name
    role.name = name
    role.is_active = request.form.get('is_active') == '1'
    log_operation('edit_role', 'role', role.id, f'编辑角色：{old_name} → {name}')
    db.session.commit()
    return jsonify({'success': True, 'message': '角色更新成功'})


# ==================== 岗位管理 ====================
@admin_bp.route('/jobs/page')
@admin_required
def jobs_page():
    """岗位管理页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    return render_template('admin/jobs_list.html', **ctx)


@admin_bp.route('/jobs')
@admin_required
def jobs_list():
    """岗位管理数据接口：返回JSON数据，前端负责渲染"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    keyword = request.args.get('keyword', '')
    province = request.args.get('province', '')
    city = request.args.get('city', '')
    education = request.args.get('education', '')
    company_type = request.args.get('company_type', '')
    recruit_type = request.args.get('recruit_type', '')
    status_filter = request.args.get('status_filter', 'active')
    
    if per_page not in [20, 50, 100]:
        per_page = 20
    
    query = Job.query.filter_by(is_deleted=False)
    if keyword:
        query = query.filter(db.or_(Job.company_name.contains(keyword), Job.job_name.contains(keyword)))
    if province:
        query = query.filter(db.or_(Job.province == province, Job.province.like(province + '%')))
    if city:
        query = query.filter(db.or_(Job.city == city, Job.city.like(city + '%')))
    if education:
        if education == '不限':
            query = query.filter(db.or_(Job.education_req == '', Job.education_req == None, Job.education_req == '不限'))
        else:
            query = query.filter(Job.education_req == education)
    if company_type:
        query = query.filter(Job.company_type == company_type)
    if recruit_type:
        query = query.filter(Job.recruit_type.contains(recruit_type))
    if status_filter == 'active':
        query = query.filter(db.or_(Job.deadline == None, Job.deadline >= datetime.now()))
    elif status_filter == 'expired':
        query = query.filter(Job.deadline != None, Job.deadline < datetime.now())
    
    pagination = query.order_by(Job.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    jobs = []
    for job in pagination.items:
        jobs.append({
            'id': job.id,
            'job_name': job.job_name,
            'company_name': job.company_name,
            'company_type': job.company_type,
            'recruit_type': job.recruit_type or '',
            'source': job.source or '',
            'salary_range': job.salary_range,
            'education_req': job.education_req,
            'location': f"{job.province}-{job.city}",
            'recruit_count': job.recruit_count,
            'deadline': job.deadline.strftime('%Y-%m-%d %H:%M') if job.deadline else None,
            'is_expired': job.is_expired(),
            'is_xiaozhao': '校园' in (job.recruit_type or ''),
            'updated_at': job.updated_at.strftime('%Y-%m-%d %H:%M') if job.updated_at else '-'
        })
    
    return jsonify({
        'success': True,
        'jobs': jobs,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


# ==================== AI 简历识别 ====================
@admin_bp.route('/ai/analyze', methods=['POST'])
@permission_required(PERMISSION_AI_RECOGNITION)
def ai_analyze():
    """上传简历 -> 文档解析/转换 -> AI 分析 -> 打分/建议/筛选条件"""
    file = request.files.get('resume')
    if file is None or not file.filename:
        return jsonify({'success': False, 'message': '请先选择要上传的简历文件'})

    filename = file.filename
    data = file.read()
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else '').lower()
    if ext not in ('xlsx', 'xls', 'pdf', 'docx', 'txt', 'doc'):
        return jsonify({'success': False, 'message': f'不支持的文件格式 .{ext}，'
                        '请上传 xlsx / pdf / word（docx）或 txt 简历'})

    try:
        text = extract_resume_text(filename, data)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

    if not text or not text.strip():
        return jsonify({'success': False, 'message': '未能从文件中解析出文本内容，请检查文件是否正常'})

    result = analyze_resume(text)

    result['success'] = True
    result['filename'] = filename
    result['char_count'] = len(text)
    log_operation('AI_ANALYZE', 'resume', 0, f'AI简历识别：{filename}')

    # 记录每次识别信息：岗位、时间、识别人、候选人、AI打分、筛选条件
    scr = result.get('screening') or {}
    candidate = result.get('candidate_name') or extract_candidate_name(text)

    # 保存简历附件到服务器
    import uuid
    import os
    from flask import current_app
    safe_ext = ext if ext else 'bin'
    stored_name = f"{uuid.uuid4().hex}.{safe_ext}"
    upload_dir = current_app.config.get('UPLOAD_FOLDER')
    stored_path = os.path.join(upload_dir, stored_name) if upload_dir else ''
    try:
        with open(stored_path, 'wb') as f:
            if isinstance(data, str):
                f.write(data.encode('utf-8'))
            else:
                f.write(data)
    except Exception:
        stored_path = ''

    detail = '；'.join(filter(None, [
        ('意向/技能：' + scr.get('keyword', '') if scr.get('keyword') else ''),
        ('城市：' + scr.get('city', '') if scr.get('city') else ''),
        ('学历：' + scr.get('education', '') if scr.get('education') else ''),
        ('年龄：' + scr.get('age', '') if scr.get('age') else ''),
        ('经验：' + scr.get('experience', '') if scr.get('experience') else ''),
        ('专业：' + scr.get('major', '') if scr.get('major') else ''),
        (scr.get('remark', '') if scr.get('remark') else ''),
    ]))
    strengths = result.get('strengths') or []
    suggestions = result.get('suggestions') or []
    if not detail:
        parts = [('优势：' + '；'.join(strengths)) if strengths else '']
        if suggestions:
            parts.append('建议：' + '；'.join(suggestions))
        detail = '；'.join(filter(None, parts)) or ('AI识别完成，评分' + str(result.get('score', 0)) + '分')

    record = ResumeAnalysisLog(
        user_id=current_user.id,
        user_name=(current_user.real_name or current_user.username),
        job=scr.get('keyword') or '',
        candidate_name=candidate,
        score=result.get('score', 0),
        level=result.get('level', ''),
        detail=detail,
        strengths='\n'.join(strengths),
        suggestions='\n'.join(suggestions),
        file_path=stored_path,
        file_name=filename,
        file_size=len(data) if data else 0,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(result)


@admin_bp.route('/ai/screen', methods=['POST'])
@permission_required(PERMISSION_AI_RECOGNITION)
def ai_screen():
    """基于简历分析出的筛选条件，进行岗位筛选，返回匹配度排序列表"""
    payload = request.get_json(silent=True) or {}
    screening = payload.get('screening') or {}
    if not any((screening.get('keyword'), screening.get('province'),
                screening.get('city'), screening.get('education'))):
        return jsonify({'success': False, 'message': '缺少有效的筛选条件'})
    jobs = screen_jobs(screening)
    return jsonify({'success': True, 'jobs': jobs, 'screening': screening})


# ==================== AI 简历识别记录（仅超管可见） ====================
@admin_bp.route('/ai/records/page')
@admin_required
@super_admin_required
def ai_records_page():
    """AI 简历识别记录页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    return render_template('admin/ai_records.html', **ctx)


@admin_bp.route('/ai/records')
@admin_required
@super_admin_required
def ai_records():
    """AI 简历识别记录数据接口：返回JSON数据，前端负责渲染"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    operator = request.args.get('operator', '').strip()
    keyword = request.args.get('keyword', '').strip()

    if per_page not in [20, 50, 100]:
        per_page = 20

    query = ResumeAnalysisLog.query
    if operator:
        query = query.filter(db.or_(ResumeAnalysisLog.user_name.contains(operator)))
    if keyword:
        query = query.filter(db.or_(
            ResumeAnalysisLog.candidate_name.contains(keyword),
            ResumeAnalysisLog.job.contains(keyword),
        ))

    pagination = query.order_by(ResumeAnalysisLog.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    records = []
    for r in pagination.items:
        records.append({
            'id': r.id,
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '-',
            'user_name': r.user_name or (r.user.real_name if r.user else '') or '-',
            'job': r.job or '-',
            'candidate_name': r.candidate_name or '-',
            'score': r.score,
            'level': r.level or '-',
            'detail': r.detail or '',
            'strengths': r.strengths or '',
            'suggestions': r.suggestions or '',
            'file_name': r.file_name or '',
            'file_size': r.file_size or 0,
        })

    return jsonify({
        'success': True,
        'records': records,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


@admin_bp.route('/ai/record/<int:record_id>/download')
@admin_required
@super_admin_required
def ai_record_download(record_id):
    """下载 AI 分析记录的简历附件"""
    import os
    from flask import current_app, send_from_directory
    record = ResumeAnalysisLog.query.get(record_id)
    if not record or not record.file_path:
        return jsonify({'success': False, 'message': '该记录没有可下载的简历附件'}), 404
    if not os.path.exists(record.file_path):
        return jsonify({'success': False, 'message': '简历附件文件不存在或已被移除'}), 404
    return send_from_directory(
        os.path.dirname(record.file_path) or current_app.config.get('UPLOAD_FOLDER'),
        os.path.basename(record.file_path),
        as_attachment=True,
        download_name=record.file_name or os.path.basename(record.file_path),
    )


@admin_bp.route('/ai/record/<int:record_id>/resume/delete', methods=['POST'])
@admin_required
@super_admin_required
def ai_record_resume_delete(record_id):
    """删除 AI 识别记录的简历附件"""
    import os
    record = ResumeAnalysisLog.query.get(record_id)
    if not record:
        return jsonify({'success': False, 'message': '记录不存在'}), 404
    if not record.file_path:
        return jsonify({'success': False, 'message': '该记录没有简历附件'})
    removed = False
    try:
        if os.path.exists(record.file_path):
            os.remove(record.file_path)
            removed = True
    except Exception:
        removed = False
    record.file_path = ''
    record.file_name = ''
    record.file_size = 0
    db.session.commit()
    return jsonify({
        'success': True,
        'message': '已删除简历附件' if removed else '已清除简历附件记录（物理文件删除失败）'
    })


@admin_bp.route('/jobs/add', methods=['GET', 'POST'])
@admin_required
def job_add():
    ctx = get_template_context()
    if request.method == 'POST':
        source = request.form.get('source', '').strip()
        if not source:
            if _is_ajax():
                return jsonify({'success': False, 'message': '来源不能为空'})
            flash('来源不能为空', 'danger')
            return render_template('admin/job_form.html', **ctx)
        job = Job(
            province=request.form.get('province', ''),
            city=request.form.get('city', ''),
            job_name=request.form.get('job_name', ''),
            company_name=request.form.get('company_name', ''),
            company_type=request.form.get('company_type', ''),
            company_size=request.form.get('company_size', ''),
            company_industry=request.form.get('company_industry', ''),
            recruit_type=request.form.get('recruit_type', ''),
            job_nature=request.form.get('job_nature', ''),
            job_category=request.form.get('job_category', ''),
            source=source,
            salary_range=request.form.get('salary_range', '').replace(' ', ''),
            recruit_count=safe_int(request.form.get('recruit_count', 1), 1),
            education_req=request.form.get('education_req', ''),
            experience_req=request.form.get('experience_req', ''),
            major_req=request.form.get('major_req', ''),
            work_location=request.form.get('work_location', ''),
            address=request.form.get('address', ''),
            deadline=safe_strptime(request.form.get('deadline')),
            job_detail=request.form.get('job_detail', ''),
            created_by=current_user.id
        )
        db.session.add(job)
        log_operation('add_job', 'job', 0, f'新增岗位：{job.job_name}')
        db.session.commit()
        message = '岗位添加成功'
        if _is_ajax():
            return jsonify({'success': True, 'message': message})
        flash(message, 'success')
        return redirect(url_for('admin.jobs_page'))
    return render_template('admin/job_form.html', **ctx)


@admin_bp.route('/jobs/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def job_edit(id):
    ctx = get_template_context()
    job = Job.query.filter_by(id=id, is_deleted=False).first_or_404()
    if request.method == 'POST':
        source = request.form.get('source', '').strip()
        if not source:
            if _is_ajax():
                return jsonify({'success': False, 'message': '来源不能为空'})
            flash('来源不能为空', 'danger')
            return render_template('admin/job_form.html', **ctx)
        job.province = request.form.get('province', '')
        job.city = request.form.get('city', '')
        job.job_name = request.form.get('job_name', '')
        job.company_name = request.form.get('company_name', '')
        job.company_type = request.form.get('company_type', '')
        job.company_size = request.form.get('company_size', '')
        job.company_industry = request.form.get('company_industry', '')
        job.recruit_type = request.form.get('recruit_type', '')
        job.job_nature = request.form.get('job_nature', '')
        job.job_category = request.form.get('job_category', '')
        job.source = request.form.get('source', '')
        job.salary_range = request.form.get('salary_range', '').replace(' ', '').strip()
        job.recruit_count = safe_int(request.form.get('recruit_count', 1), 1)
        job.education_req = request.form.get('education_req', '')
        job.experience_req = request.form.get('experience_req', '')
        job.major_req = request.form.get('major_req', '')
        job.work_location = request.form.get('work_location', '')
        job.address = request.form.get('address', '')
        job.deadline = safe_strptime(request.form.get('deadline'))
        job.job_detail = request.form.get('job_detail', '')
        log_operation('edit_job', 'job', job.id, f'编辑岗位：{job.job_name}')
        db.session.commit()
        message = '岗位更新成功'
        if _is_ajax():
            return jsonify({'success': True, 'message': message})
        flash(message, 'success')
        return redirect(url_for('admin.jobs_page'))
    ctx['job_id'] = id
    return render_template('admin/job_form.html', **ctx)


@admin_bp.route('/jobs/<int:id>/data')
@admin_required
def job_data(id):
    """岗位编辑页数据接口：返回JSON数据，前端负责填充表单"""
    job = Job.query.filter_by(id=id, is_deleted=False).first_or_404()
    return jsonify({
        'province': job.province,
        'city': job.city,
        'job_name': job.job_name,
        'company_name': job.company_name,
        'company_type': job.company_type,
        'company_size': job.company_size,
        'company_industry': job.company_industry,
        'recruit_type': job.recruit_type or '',
        'job_nature': job.job_nature,
        'job_category': job.job_category,
        'source': job.source,
        'salary_range': job.salary_range,
        'recruit_count': job.recruit_count,
        'education_req': job.education_req,
        'experience_req': job.experience_req,
        'major_req': job.major_req,
        'work_location': job.work_location,
        'address': job.address,
        'deadline': job.deadline.strftime('%Y-%m-%d %H:%M:%S') if job.deadline else '',
        'job_detail': job.job_detail
    })


@admin_bp.route('/jobs/delete', methods=['POST'])
@admin_required
def job_delete():
    ids = request.form.getlist('job_ids')
    if not ids:
        msg = '请选择要删除的岗位'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'warning')
        return redirect(url_for('admin.jobs_page'))
    jobs = Job.query.filter(Job.id.in_(ids), Job.is_deleted==False).all()
    if not jobs:
        msg = '未找到要删除的岗位'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'warning')
        return redirect(url_for('admin.jobs_page'))
    for job in jobs:
        job.is_deleted = True
        log_operation('delete_job', 'job', job.id, f'删除岗位：{job.job_name}')
    db.session.commit()
    msg = f'成功删除 {len(jobs)} 个岗位'
    if _is_ajax():
        return jsonify({'success': True, 'message': msg})
    flash(msg, 'success')
    return redirect(url_for('admin.jobs_page'))


@admin_bp.route('/jobs/toggle_status', methods=['POST'])
@admin_required
@super_admin_required
def job_toggle_status():
    ids = request.form.getlist('job_ids')
    action = request.form.get('action', 'activate')
    if not ids:
        msg = '请选择要操作的岗位'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'warning')
        return redirect(url_for('admin.jobs_page'))
    new_status = 'active' if action == 'activate' else 'inactive'
    jobs = Job.query.filter(Job.id.in_(ids), Job.is_deleted==False).all()
    if not jobs:
        msg = '未找到要操作的岗位'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'warning')
        return redirect(url_for('admin.jobs_page'))
    for job in jobs:
        job.status = new_status
    db.session.commit()
    msg = f'成功操作 {len(jobs)} 个岗位'
    if _is_ajax():
        return jsonify({'success': True, 'message': msg})
    flash(msg, 'success')
    return redirect(url_for('admin.jobs_page'))


@admin_bp.route('/jobs/import', methods=['GET', 'POST'])
@admin_required
@super_admin_required
def job_import():
    ctx = get_template_context()
    ajax = _is_ajax()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            msg = '请选择文件'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/job_import.html', **ctx)
        if not file.filename.endswith(('.xlsx', '.xls')):
            msg = '请上传Excel文件'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/job_import.html', **ctx)
        try:
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            row_count = max(1, ws.max_row - 1)

            # 读取表头行，建立「列名 -> 列索引」映射（兼容列顺序变化）
            header_cells = [str(c.value).strip() if c.value is not None else '' for c in ws[1]]
            colmap = {}
            for i, h in enumerate(header_cells):
                if h:
                    colmap.setdefault(h, i)

            def val(row, *names):
                for n in names:
                    if n in colmap and colmap[n] < len(row):
                        return row[colmap[n]]
                return ''

            count = 0
            errors = []
            for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                job_name_raw = val(row, '职位名称', '职位名称 ')
                if not job_name_raw:
                    continue
                try:
                    # ---------- 字段校验：不符合则报错并跳过该行 ----------
                    v_company = str(val(row, '公司名称') or '').strip()
                    v_job_name = str(job_name_raw or '').strip()
                    v_source = str(val(row, '来源') or '').strip()
                    v_salary = str(val(row, '薪资范围') or '').replace(' ', '').strip()
                    v_count = val(row, '招聘人数')
                    v_deadline = val(row, '报名截止(YYYY-MM-DD HH:MM:SS)', '报名截止', '截止时间')

                    if not v_job_name:
                        errors.append(f'第{idx}行：职位名称不能为空')
                        continue
                    if not v_company:
                        errors.append(f'第{idx}行：公司名称不能为空')
                        continue
                    if not v_source:
                        errors.append(f'第{idx}行：来源不能为空')
                        continue
                    if v_count and not str(v_count).isdigit():
                        errors.append(f'第{idx}行：招聘人数应为数字')
                        continue
                    if v_deadline and not safe_strptime(str(v_deadline), '%Y-%m-%d %H:%M:%S') and not safe_strptime(str(v_deadline), '%Y-%m-%d'):
                        errors.append(f'第{idx}行：截止时间格式不正确（应为 YYYY-MM-DD HH:MM:SS）')
                        continue

                    job = Job(
                        province=str(val(row, '省份') or ''),
                        city=str(val(row, '城市') or ''),
                        job_name=v_job_name,
                        company_name=v_company,
                        company_type=str(val(row, '公司性质') or ''),
                        company_size=str(val(row, '公司规模') or ''),
                        company_industry=str(val(row, '公司行业') or ''),
                        recruit_type=str(val(row, '招聘类型') or '社会招聘'),
                        job_nature=str(val(row, '职位性质') or ''),
                        job_category=str(val(row, '职位类别') or ''),
                        source=v_source,
                        salary_range=v_salary,
                        recruit_count=safe_int(v_count or '1', 1),
                        education_req=str(val(row, '学历要求') or ''),
                        experience_req=str(val(row, '经验要求') or ''),
                        major_req=str(val(row, '专业要求') or ''),
                        work_location=str(val(row, '工作地点') or ''),
                        address=str(val(row, '详细地址') or ''),
                        deadline=safe_strptime(str(v_deadline)) if v_deadline else None,
                        job_detail=str(val(row, '职位描述') or ''),
                        created_by=current_user.id
                    )
                    db.session.add(job)
                    count += 1
                except Exception as e:
                    errors.append(f'第{idx}行：{str(e)}')
            if count == 0:
                msg = '未导入任何岗位，请检查文件格式'
                if ajax:
                    return jsonify({'success': False, 'message': msg})
                flash(msg, 'warning')
                return render_template('admin/job_import.html', **ctx)
            log_operation('import_jobs', 'job', 0, f'批量导入 {count} 个岗位')
            db.session.commit()
            success_msg = f'成功导入 {count} 个岗位'
            if errors:
                success_msg += f'，{len(errors)} 行失败'
            if ajax:
                return jsonify({'success': True, 'message': success_msg, 'count': count, 'total_rows': row_count, 'errors': errors})
            flash(success_msg, 'success')
            if errors:
                flash('\n'.join(errors), 'warning')
            return redirect(url_for('admin.jobs_page'))
        except Exception as e:
            db.session.rollback()
            msg = f'导入失败：{str(e)}'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
    return render_template('admin/job_import.html', **ctx)


@admin_bp.route('/jobs/template')
@admin_required
@super_admin_required
def job_template():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '岗位导入模板'
    ws.append(['来源', '省份', '城市', '职位名称', '公司名称', '公司性质', '公司规模', '公司行业',
               '招聘类型', '职位性质', '职位类别', '薪资范围', '招聘人数', '学历要求',
               '经验要求', '专业要求', '工作地点', '详细地址', '报名截止(YYYY-MM-DD HH:MM:SS)', '职位描述'])
    ws.append(['企业官网', '新疆', '阿勒泰地区',
               '北屯 供应链组织者（应届本科，财务/统计相关专业）',
               '国药集团新疆新特药业有限公司', '国企', '1000-2000人', '批发业',
               '校园招聘', '校招', '渠道专员/助理', '5600~7000 元/月', 1,
               '本科', '应届生', '财务会计类, 统计学类', '阿勒泰', '',
               '2026-11-09 23:59:59',
               '负责资质证照的备案、盯计划、反馈缺货、协调配送、调价、退货、对账、回款核销等全链路运营操作'])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='岗位导入模板.xlsx')


# ==================== 管理员管理（仅超管） ====================
@admin_bp.route('/users/page')
@admin_required
@super_admin_required
def users_page():
    """管理员管理页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    ctx['campuses'] = Campus.query.filter_by(is_active=True, is_deleted=False).all()
    ctx['roles'] = Role.query.filter_by(is_active=True, is_deleted=False).all()
    return render_template('admin/users_list.html', **ctx)


@admin_bp.route('/users')
@admin_required
@super_admin_required
def users_list():
    """管理员管理数据接口：仅返回管理员，前端负责渲染"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    keyword = request.args.get('keyword', '')
    campus = request.args.get('campus', '')
    role = request.args.get('role', '')
    status = request.args.get('status', '')
    
    if per_page not in [20, 50, 100]:
        per_page = 20
    
    query = User.query.filter_by(user_type='admin', is_deleted=False)
    if keyword:
        query = query.filter(db.or_(
            User.username.contains(keyword), User.real_name.contains(keyword),
            User.phone.contains(keyword)
        ))
    if campus:
        campus_obj = Campus.query.filter_by(name=campus, is_deleted=False).first()
        if campus_obj:
            query = query.filter(User.campus_id == campus_obj.id)
    if role:
        query = query.filter(User.role == role)
    if status:
        query = query.filter(User.is_active == (status == '1'))
    pagination = query.order_by(User.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    users = []
    for user in pagination.items:
        user_data = {
            'id': user.id,
            'real_name': user.real_name,
            'id_card_last6': user.get_id_card_last6(),
            'user_type': user.user_type,
            'campus': user.campus.name if user.campus else '-',
            'role': user.role or '-',
            'phone': user.phone,
            'can_push_jobs': user.can_push_jobs,
            'can_view_jobs': user.can_view_jobs,
            'can_manage_students': user.can_manage_students,
            'can_ai_recognition': user.can_ai_recognition,
            'creator': user.creator.real_name if user.creator else '-',
            'is_active': user.is_active,
            'created_at': user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else '-',
            'updated_at': user.updated_at.strftime('%Y-%m-%d %H:%M') if user.updated_at else '-'
        }
        if current_user.is_super_admin():
            user_data['password'] = user.password_plain or '-'
        users.append(user_data)
    
    return jsonify({
        'success': True,
        'users': users,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@admin_required
@super_admin_required
def user_add():
    ctx = get_template_context()
    ctx['campuses'] = Campus.query.filter_by(is_active=True, is_deleted=False).all()
    ctx['roles'] = Role.query.filter_by(is_active=True, is_deleted=False).all()
    ajax = _is_ajax()
    
    if request.method == 'POST':
        real_name = request.form.get('real_name', '').strip()
        phone = request.form.get('phone', '').strip()
        
        if not is_valid_phone(phone):
            msg = '手机号格式不正确，应为11位数字且以1开头'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/user_form.html', **ctx)
        
        if User.query.filter_by(username=phone, is_deleted=False).first():
            msg = f'手机号"{phone}"已注册'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/user_form.html', **ctx)
        
        password = request.form.get('password', '')
        if not password:
            password = phone[-6:] if len(phone) >= 6 else '123456'
        
        user = User(
            username=phone,
            user_type='admin',
            real_name=real_name,
            phone=phone,
            campus_id=safe_int(request.form.get('campus_id', 0)) or None,
            role=request.form.get('role', ''),
            can_push_jobs=bool(request.form.get('can_push_jobs')),
            can_view_jobs=bool(request.form.get('can_view_jobs')),
            can_manage_students=bool(request.form.get('can_manage_students')),
            can_ai_recognition=bool(request.form.get('can_ai_recognition')),
            avatar=request.form.get('avatar', ''),
            is_active=request.form.get('is_active') == '1',
            created_by=current_user.id
        )
        user.set_password(password)
        db.session.add(user)
        log_operation('add_user', 'user', 0, f'新增管理员：{user.real_name}')
        db.session.commit()
        msg = '管理员添加成功'
        if ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('admin.users_page'))
    
    return render_template('admin/user_form.html', **ctx)


@admin_bp.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@super_admin_required
def user_edit(id):
    ctx = get_template_context()
    user = User.query.filter_by(id=id, is_deleted=False).first_or_404()
    if user.user_type != 'admin':
        msg = '该用户不是管理员，请到学员管理操作'
        if request.method == 'POST' and _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return redirect(url_for('admin.users_page'))
    ctx['campuses'] = Campus.query.filter_by(is_active=True, is_deleted=False).all()
    ctx['roles'] = Role.query.filter_by(is_active=True, is_deleted=False).all()
    
    if request.method == 'POST':
        new_password = request.form.get('password', '')
        if not new_password:
            msg = '请输入密码'
            if _is_ajax():
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/user_form.html', **ctx)
        
        user.real_name = request.form.get('real_name', '')
        user.phone = request.form.get('phone', '')
        if not is_valid_phone(user.phone):
            if _is_ajax():
                return jsonify({'success': False, 'message': '手机号格式不正确，应为11位数字且以1开头'})
            flash('手机号格式不正确，应为11位数字且以1开头', 'danger')
            return render_template('admin/user_form.html', **ctx)
        user.campus_id = safe_int(request.form.get('campus_id', 0)) or None
        user.role = request.form.get('role', '')
        user.can_push_jobs = bool(request.form.get('can_push_jobs'))
        user.can_view_jobs = bool(request.form.get('can_view_jobs'))
        user.can_manage_students = bool(request.form.get('can_manage_students'))
        user.can_ai_recognition = bool(request.form.get('can_ai_recognition'))
        user.avatar = request.form.get('avatar', '')
        user.is_active = request.form.get('is_active') == '1'
        
        if new_password != user.password_plain:
            user.set_password(new_password)
        
        log_operation('edit_user', 'user', user.id, f'编辑管理员：{user.real_name}')
        db.session.commit()
        msg = '管理员信息更新成功'
        if _is_ajax():
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('admin.users_page'))
    ctx['user_obj'] = user
    return render_template('admin/user_form.html', **ctx)


@admin_bp.route('/users/delete', methods=['POST'])
@admin_required
@super_admin_required
def user_delete():
    user_id = request.form.get('user_id')
    verify_name = request.form.get('verify_name', '').strip()
    verify_phone = request.form.get('verify_phone', '').strip()
    
    user = User.query.filter_by(id=user_id, is_deleted=False).first_or_404()
    
    if user.user_type != 'admin':
        msg = '该用户不是管理员，请到学员管理操作'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return redirect(url_for('admin.users_page'))
    
    if user.id == current_user.id:
        msg = '不能删除自己的账号'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return redirect(url_for('admin.users_page'))
    
    if user.real_name != verify_name or user.phone != verify_phone:
        msg = '姓名或电话验证失败'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return redirect(url_for('admin.users_page'))
    
    user.is_deleted = True
    log_operation('delete_user', 'user', user.id, f'删除管理员：{user.real_name}')
    db.session.commit()
    msg = '管理员删除成功'
    if _is_ajax():
        return jsonify({'success': True, 'message': msg})
    flash(msg, 'success')
    return redirect(url_for('admin.users_page'))


@admin_bp.route('/users/batch-delete', methods=['POST'])
@admin_required
@super_admin_required
def user_batch_delete():
    user_ids = request.form.getlist('user_ids')
    if not user_ids:
        return jsonify({'success': False, 'message': '请选择要删除的管理员'})
    
    deleted_count = 0
    skipped_self = 0
    for uid in user_ids:
        user = User.query.filter_by(id=uid, is_deleted=False).first()
        if not user:
            continue
        if user.user_type != 'admin':
            continue
        if user.id == current_user.id:
            skipped_self += 1
            continue
        user.is_deleted = True
        log_operation('delete_user', 'user', user.id, f'批量删除管理员：{user.real_name}')
        deleted_count += 1
    
    db.session.commit()
    
    msg = f'成功删除 {deleted_count} 个管理员'
    if skipped_self > 0:
        msg += f'，跳过 {skipped_self} 个（不能删除自己）'
    return jsonify({'success': True, 'message': msg})


@admin_bp.route('/users/toggle_status', methods=['POST'])
@admin_required
@super_admin_required
def user_toggle_status():
    user_id = request.form.get('user_id', type=int)
    if not user_id:
        return jsonify({'success': False, 'message': '参数错误'})
    user = User.query.filter_by(id=user_id, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'})
    user.is_active = not user.is_active
    log_operation('toggle_status', 'user', user.id, f'切换状态：{user.real_name} → {"启用" if user.is_active else "禁用"}')
    db.session.commit()
    return jsonify({'success': True, 'message': f'已{"启用" if user.is_active else "禁用"}', 'is_active': user.is_active})


@admin_bp.route('/users/list_json')
@admin_required
def users_list_json():
    if current_user.is_super_admin():
        students = User.query.filter_by(user_type='student', is_active=True, is_deleted=False).all()
    else:
        students = User.query.filter_by(user_type='student', is_active=True, created_by=current_user.id, is_deleted=False).all()
    return jsonify([{
        'id': s.id, 'username': s.username, 
        'real_name': s.real_name, 'id_card_last6': s.get_id_card_last6()
    } for s in students])


# ==================== 学员管理 ====================
@admin_bp.route('/students/page')
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def students_page():
    """学员管理页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    if current_user.is_super_admin():
        ctx['campuses'] = Campus.query.filter_by(is_active=True, is_deleted=False).all()
    else:
        ctx['campuses'] = Campus.query.filter_by(id=current_user.campus_id, is_active=True, is_deleted=False).all()
    ctx['admins'] = User.query.filter_by(user_type='admin', is_active=True, is_deleted=False).order_by(User.real_name.asc()).all()
    return render_template('admin/students_list.html', **ctx)


@admin_bp.route('/push_students')
@admin_required
@permission_required(PERMISSION_PUSH_JOBS)
def push_students():
    """岗位推送弹窗学员列表（仅需推送权限）"""
    campus = request.args.get('campus', '').strip()
    status = request.args.get('status', 'active')
    query = User.query.filter_by(user_type='student', is_deleted=False)
    campus_filter = get_campus_filter()
    if campus_filter is not None:
        query = query.filter_by(campus_id=campus_filter)
    if campus:
        campus_obj = Campus.query.filter_by(name=campus, is_deleted=False).first()
        if campus_obj:
            query = query.filter(User.campus_id == campus_obj.id)
    if status == 'active':
        query = query.filter(User.is_active == True)
    elif status == 'disabled':
        query = query.filter(User.is_active == False)
    students = query.order_by(User.updated_at.desc()).limit(500).all()
    data = []
    for stu in students:
        campus_name = stu.campus.name if stu.campus else '-'
        data.append({
            'id': stu.id,
            'real_name': stu.real_name,
            'phone': stu.phone,
            'campus': campus_name,
            'education': stu.education or '-',
            'major': stu.major or '-'
        })
    return jsonify({'success': True, 'students': data})


@admin_bp.route('/students')
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def students_list():
    """学员管理数据接口：返回JSON数据，前端负责渲染"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    keyword = request.args.get('keyword', '')
    campus = request.args.get('campus', '')
    education = request.args.get('education', '')
    status = request.args.get('status', '')
    creator_id = request.args.get('creator_id', '', type=str)
    
    if per_page == 0:
        per_page = 10000
    elif per_page not in [20, 50, 100]:
        per_page = 20
    
    query = User.query.filter_by(user_type='student', is_deleted=False)
    campus_filter = get_campus_filter()
    if campus_filter is not None:
        query = query.filter_by(campus_id=campus_filter)
    if keyword:
        query = query.filter(db.or_(
            User.username.contains(keyword), User.real_name.contains(keyword),
            User.phone.contains(keyword)
        ))
    if campus:
        campus_obj = Campus.query.filter_by(name=campus, is_deleted=False).first()
        if campus_obj:
            query = query.filter(User.campus_id == campus_obj.id)
    if education:
        query = query.filter(User.education == education)
    if status:
        if status == 'active':
            query = query.filter(User.is_active == True)
        elif status == 'disabled':
            query = query.filter(User.is_active == False)
    if creator_id:
        query = query.filter(User.created_by == creator_id)
    pagination = query.order_by(User.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    students = []
    for stu in pagination.items:
        campus_name = stu.campus.name if stu.campus else '-'
        students.append({
            'id': stu.id,
            'real_name': stu.real_name,
            'username': stu.username,
            'campus': campus_name,
            'id_card_last6': stu.get_id_card_last6(),
            'phone': stu.phone,
            'gender': stu.gender or '-',
            'age': stu.get_age() or '-',
            'education': stu.education or '-',
            'major': stu.major or '-',
            'intention_city': stu.intention_city or '-',
            'graduation_date': stu.graduation_date.strftime('%Y-%m-%d') if stu.graduation_date else '-',
            'creator': stu.creator.real_name if stu.creator else '-',
            'password': stu.password_plain or '-',
            'is_active': stu.is_active,
            'updated_at': stu.updated_at.strftime('%Y-%m-%d %H:%M') if stu.updated_at else '-'
        })
    
    return jsonify({
        'success': True,
        'students': students,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


@admin_bp.route('/students/add', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def student_add():
    ctx = get_template_context()
    ajax = _is_ajax()
    
    if request.method == 'POST':
        real_name = request.form.get('real_name', '').strip()
        phone = request.form.get('phone', '').strip()
        id_card = request.form.get('id_card', '').strip()
        intention_city = request.form.get('intention_city', '').strip()
        password = request.form.get('password', '').strip()
        
        if not phone:
            msg = '请输入手机号'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/student_form.html', **ctx)
        
        if not is_valid_phone(phone):
            msg = '手机号格式不正确，应为11位数字且以1开头'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/student_form.html', **ctx)
        
        if not id_card or len(id_card) != 18:
            msg = '请输入18位身份证号'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/student_form.html', **ctx)
        
        if User.query.filter_by(username=phone, is_deleted=False).first():
            msg = f'手机号"{phone}"已注册'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/student_form.html', **ctx)
        
        gender, birth_date, age = User.parse_id_card(id_card)
        if not password:
            password = id_card[-6:]
        _gdate_str = request.form.get('graduation_date', '').strip()
        _gdate = None
        if _gdate_str:
            _parsed = safe_strptime(_gdate_str, '%Y-%m-%d')
            if _parsed:
                _gdate = _parsed.date()

        user = User(
            username=phone,
            user_type='student',
            real_name=real_name,
            phone=phone,
            id_card=id_card,
            gender=gender or request.form.get('gender', ''),
            birth_date=birth_date,
            education=request.form.get('education', ''),
            major=request.form.get('major', ''),
            political_status=request.form.get('political_status', ''),
            intention_city=intention_city,
            first_intention=request.form.get('first_intention', ''),
            second_intention=request.form.get('second_intention', ''),
            third_intention=request.form.get('third_intention', ''),
            certificate=request.form.get('certificate', ''),
            remark=request.form.get('remark', ''),
            graduation_date=_gdate,
            origin_place=request.form.get('origin_place', ''),
            avatar=request.form.get('avatar', ''),
            campus_id=current_user.campus_id,
            created_by=current_user.id
        )
        user.set_password(password)
        db.session.add(user)
        log_operation('add_user', 'user', 0, f'新增学员：{user.real_name}')
        db.session.commit()
        msg = '学员添加成功'
        if ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('admin.students_page'))
    
    return render_template('admin/student_form.html', **ctx)


@admin_bp.route('/students/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def student_edit(id):
    ctx = get_template_context()
    student = User.query.filter_by(id=id, user_type='student', is_deleted=False).first_or_404()
    
    valid, resp = validate_object_campus(student)
    if not valid:
        return resp
    
    if request.method == 'POST':
        intention_city = request.form.get('intention_city', '').strip()
        
        student.real_name = request.form.get('real_name', '')
        student.phone = request.form.get('phone', '')
        if not is_valid_phone(student.phone):
            if _is_ajax():
                return jsonify({'success': False, 'message': '手机号格式不正确，应为11位数字且以1开头'})
            flash('手机号格式不正确，应为11位数字且以1开头', 'danger')
            return render_template('admin/student_form.html', student=student, **ctx)
        student.education = request.form.get('education', '')
        student.major = request.form.get('major', '')
        student.political_status = request.form.get('political_status', '')
        student.intention_city = intention_city
        student.first_intention = request.form.get('first_intention', '')
        student.second_intention = request.form.get('second_intention', '')
        student.third_intention = request.form.get('third_intention', '')
        student.certificate = request.form.get('certificate', '')
        student.remark = request.form.get('remark', '')
        _gdate_str = request.form.get('graduation_date', '').strip()
        _parsed = safe_strptime(_gdate_str, '%Y-%m-%d') if _gdate_str else None
        student.graduation_date = _parsed.date() if _parsed else None
        student.origin_place = request.form.get('origin_place', '')
        student.avatar = request.form.get('avatar', '')
        
        new_password = request.form.get('password', '')
        if not new_password:
            msg = '请输入密码'
            if _is_ajax():
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/student_form.html', **ctx)
        student.set_password(new_password)
        
        log_operation('edit_user', 'user', student.id, f'编辑学员：{student.real_name}')
        db.session.commit()
        msg = '学员信息更新成功'
        if _is_ajax():
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('admin.students_page'))
    ctx['student'] = student
    return render_template('admin/student_form.html', **ctx)


@admin_bp.route('/students/delete', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def student_delete():
    user_id = request.form.get('user_id')
    verify_name = request.form.get('verify_name', '').strip()
    verify_phone = request.form.get('verify_phone', '').strip()
    
    user = User.query.filter_by(id=user_id, user_type='student', is_deleted=False).first_or_404()
    
    valid, resp = validate_object_campus(user)
    if not valid:
        return resp
    
    if user.real_name != verify_name or user.phone != verify_phone:
        msg = '姓名或电话验证失败'
        if _is_ajax():
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')
        return redirect(url_for('admin.students_page'))
    
    user.is_deleted = True
    log_operation('delete_user', 'user', user.id, f'删除学员：{user.real_name}')
    db.session.commit()
    msg = '学员删除成功'
    if _is_ajax():
        return jsonify({'success': True, 'message': msg})
    flash(msg, 'success')
    return redirect(url_for('admin.students_page'))


@admin_bp.route('/students/toggle-status', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def student_toggle_status():
    student_id = request.form.get('student_id')
    student = User.query.filter_by(id=student_id, user_type='student', is_deleted=False).first_or_404()
    valid, resp = validate_object_campus(student)
    if not valid:
        return resp
    student.is_active = not student.is_active
    status_text = '启用' if student.is_active else '禁用'
    log_operation('toggle_student_status', 'user', student.id, f'学员{status_text}：{student.real_name}')
    db.session.commit()
    return jsonify({'success': True, 'message': f'学员已{status_text}'})


@admin_bp.route('/students/batch-delete', methods=['POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def student_batch_delete():
    student_ids = request.form.getlist('student_ids')
    if not student_ids:
        return jsonify({'success': False, 'message': '请选择要删除的学员'})
    
    deleted_count = 0
    for sid in student_ids:
        student = User.query.filter_by(id=sid, user_type='student', is_deleted=False).first()
        if not student:
            continue
        valid, _ = validate_object_campus(student)
        if not valid:
            continue
        student.is_deleted = True
        log_operation('delete_user', 'user', student.id, f'批量删除学员：{student.real_name}')
        deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'成功删除 {deleted_count} 个学员'})


# ==================== 岗位推荐 ====================
@admin_bp.route('/push/page')
@admin_required
def push_page():
    """推荐记录页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    return render_template('admin/push_list.html', **ctx)


@admin_bp.route('/push/campuses')
@admin_required
def push_campuses():
    """推送功能校区列表：超管返回全部，管理员返回当前校区"""
    campus_filter = get_campus_filter()
    if campus_filter is None:
        campuses = Campus.query.filter_by(is_active=True, is_deleted=False).all()
    else:
        campuses = Campus.query.filter_by(id=campus_filter, is_active=True, is_deleted=False).all()
    
    data = []
    for campus in campuses:
        student_count = User.query.filter_by(campus_id=campus.id, user_type='student', is_active=True, is_deleted=False).count()
        data.append({
            'id': campus.id,
            'name': campus.name,
            'student_count': student_count
        })
    
    return jsonify({'success': True, 'campuses': data})


@admin_bp.route('/push')
@admin_required
def push_list():
    """推荐记录数据接口：返回JSON数据，前端负责渲染"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    keyword_job = request.args.get('keyword_job', '').strip()
    keyword_company = request.args.get('keyword_company', '').strip()
    keyword_student = request.args.get('keyword_student', '').strip()
    keyword_pusher = request.args.get('keyword_pusher', '').strip()
    is_read = request.args.get('is_read', '').strip()
    
    if per_page not in [20, 50, 100]:
        per_page = 20
    
    query = PushRecord.query.filter_by(is_deleted=False)
    if keyword_job:
        J = aliased(Job)
        query = query.join(J, PushRecord.job_id == J.id, isouter=True).filter(J.job_name.contains(keyword_job))
    if keyword_company:
        Jc = aliased(Job)
        query = query.join(Jc, PushRecord.job_id == Jc.id, isouter=True).filter(Jc.company_name.contains(keyword_company))
    if keyword_student:
        Us = aliased(User)
        query = query.join(Us, PushRecord.student_id == Us.id, isouter=True).filter(
            db.or_(Us.real_name.contains(keyword_student), Us.username.contains(keyword_student))
        )
    if keyword_pusher:
        Up = aliased(User)
        query = query.join(Up, PushRecord.pushed_by == Up.id, isouter=True).filter(
            db.or_(Up.real_name.contains(keyword_pusher), Up.username.contains(keyword_pusher))
        )
    if is_read == '1':
        query = query.filter(PushRecord.is_read == True)
    elif is_read == '0':
        query = query.filter(PushRecord.is_read == False)
    
    # 管理员只显示当前校区的推送记录
    campus_filter = get_campus_filter()
    if campus_filter is not None:
        Uc = aliased(User)
        query = query.join(Uc, PushRecord.student_id == Uc.id, isouter=True).filter(Uc.campus_id == campus_filter)
    
    pagination = query.order_by(PushRecord.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    pushes = []
    for push in pagination.items:
        pushes.append({
            'id': push.id,
            'job_name': push.job.job_name if push.job else '',
            'company_name': push.job.company_name if push.job else '',
            'student': push.student.real_name or push.student.username,
            'campus': push.student.campus.name if push.student.campus else '-',
            'pusher': push.pusher.real_name or push.pusher.username,
            'pushed_at': push.pushed_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': push.updated_at.strftime('%Y-%m-%d %H:%M') if push.updated_at else '-',
            'is_read': push.is_read,
            'is_revoked': push.is_revoked
        })
    
    return jsonify({
        'success': True,
        'pushes': pushes,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


@admin_bp.route('/push/do', methods=['POST'])
@admin_required
@permission_required(PERMISSION_PUSH_JOBS)
def push_do():
    job_ids = request.form.getlist('job_ids')
    student_ids = request.form.getlist('student_ids')
    if not job_ids:
        if _is_ajax():
            return jsonify({'success': False, 'message': '请选择岗位'})
        flash('请选择岗位', 'warning')
        return redirect(url_for('admin.push_page'))
    if not student_ids:
        if _is_ajax():
            return jsonify({'success': False, 'message': '请选择学员'})
        flash('请选择学员', 'warning')
        return redirect(url_for('admin.push_page'))
    
    count = 0
    valid_jids = [safe_int(jid) for jid in job_ids if safe_int(jid)]
    valid_sids = [safe_int(sid) for sid in student_ids if safe_int(sid)]

    # 校验岗位是否存在，避免外键异常
    valid_jids = [jid for jid in valid_jids if Job.query.filter_by(id=jid, is_deleted=False).first()]
    # 校验学员是否存在，且未被删除
    valid_sids = [sid for sid in valid_sids if User.query.filter_by(id=sid, user_type='student', is_deleted=False).first()]

    # 管理员只能推送当前校区的学员
    campus_filter = get_campus_filter()
    if campus_filter is not None:
        valid_sids = [sid for sid in valid_sids if User.query.filter_by(id=sid, user_type='student', campus_id=campus_filter, is_deleted=False).first()]

    for jid in valid_jids:
        for sid in valid_sids:
            push = PushRecord(job_id=jid, student_id=sid, pushed_by=current_user.id)
            db.session.add(push)
            count += 1
    log_operation('push_jobs', 'push', 0, f'推送 {len(valid_jids)} 个岗位给 {len(valid_sids)} 个学员')
    db.session.commit()
    if _is_ajax():
        return jsonify({'success': True, 'message': f'成功推送 {len(valid_jids)} 条岗位给 {len(valid_sids)} 人', 'count': count})
    flash(f'成功推送 {len(valid_jids)} 条岗位给 {len(valid_sids)} 人', 'success')
    return redirect(url_for('admin.push_page'))


@admin_bp.route('/push/toggle_revoke', methods=['POST'])
@admin_required
def push_toggle_revoke():
    """撤销/恢复推送记录：撤销后学员不可见，恢复后可见"""
    push_id = request.form.get('push_id', type=int)
    if not push_id:
        return jsonify({'success': False, 'message': '参数错误'})
    push = PushRecord.query.filter_by(id=push_id, is_deleted=False).first()
    if not push:
        return jsonify({'success': False, 'message': '推送记录不存在'})
    push.is_revoked = not push.is_revoked
    status_text = '撤销' if push.is_revoked else '恢复'
    log_operation('toggle_push_revoke', 'push', push.id,
                  f'{status_text}推送：{push.job.job_name if push.job else ""} → {push.student.real_name or push.student.username}')
    db.session.commit()
    return jsonify({'success': True, 'message': f'推送已{status_text}', 'is_revoked': push.is_revoked})


# ==================== 操作日志 ====================
@admin_bp.route('/logs/page')
@admin_required
def logs_page():
    """操作日志页面（HTML骨架，数据由前端异步加载）"""
    ctx = get_template_context()
    return render_template('admin/logs_list.html', **ctx)


@admin_bp.route('/logs')
@admin_required
def logs_list():
    """操作日志数据接口：返回JSON数据，前端负责渲染"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    action = request.args.get('action', '')
    operator = request.args.get('operator', '').strip()
    
    if per_page not in [20, 50, 100]:
        per_page = 20
    
    query = OperationLog.query.filter_by(is_deleted=False)
    if action:
        query = query.filter_by(action=action)
    
    # 管理员只显示当前校区的操作日志
    campus_filter = get_campus_filter()
    if campus_filter is not None:
        U1 = aliased(User)
        query = query.join(U1, OperationLog.user_id == U1.id, isouter=True).filter(U1.campus_id == campus_filter)
    
    # 按操作人搜索
    if operator:
        U2 = aliased(User)
        query = query.join(U2, OperationLog.user_id == U2.id, isouter=True).filter(
            db.or_(U2.real_name.contains(operator), U2.username.contains(operator))
        )
    
    pagination = query.order_by(OperationLog.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    logs = []
    for log in pagination.items:
        logs.append({
            'id': log.id,
            'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '-',
            'operator': log.user.real_name or log.user.username,
            'action': log.action,
            'details': log.details or '-',
            'ip_address': log.ip_address
        })
    
    return jsonify({
        'success': True,
        'logs': logs,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num
        }
    })


# ==================== 管理员导入（超管） ====================
@admin_bp.route('/import_admins', methods=['GET', 'POST'])
@admin_required
@super_admin_required
def import_admins():
    ctx = get_template_context()
    ajax = _is_ajax()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            msg = '请选择文件'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/import_admins.html', **ctx)
        if not file.filename.endswith(('.xlsx', '.xls')):
            msg = '请上传Excel文件'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/import_admins.html', **ctx)
        try:
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            row_count = max(1, ws.max_row - 1)
            count = 0
            errors = []

            header_cells = [str(c.value).strip() if c.value is not None else '' for c in ws[1]]
            colmap = {}
            for i, h in enumerate(header_cells):
                if h:
                    colmap.setdefault(h, i)

            def val(row, *names):
                for n in names:
                    if n in colmap and colmap[n] < len(row):
                        return row[colmap[n]]
                return ''

            for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                real_name = str(val(row, '姓名') or '').strip()
                if not real_name:
                    continue
                phone = str(val(row, '手机号') or '').strip()
                campus_name = str(val(row, '校区名称') or '').strip()
                password = str(val(row, '密码(默认手机号后6位)', '密码') or '').strip()
                role = str(val(row, '角色(校长/老师等)', '角色') or '').strip()
                is_active_str = str(val(row, '状态(启用/禁用)', '状态') or '启用').strip()
                is_active = is_active_str not in ('禁用', 'no', 'false', '0', '×')
                can_push_str = str(val(row, '岗位推送权限(是/否)', '岗位推送权限') or '').strip()
                can_view_str = str(val(row, '岗位查看权限(是/否)', '岗位查看权限') or '').strip()
                can_manage_str = str(val(row, '学员管理权限(是/否)', '学员管理权限') or '').strip()
                
                can_push = can_push_str.lower() in ('是', 'yes', 'true', '1', '√') if can_push_str else True
                can_view = can_view_str.lower() in ('是', 'yes', 'true', '1', '√') if can_view_str else True
                can_manage = can_manage_str.lower() in ('是', 'yes', 'true', '1', '√') if can_manage_str else True
                
                if not real_name:
                    errors.append(f'第{idx}行：姓名为空')
                    continue
                if not phone:
                    errors.append(f'第{idx}行：手机号为空')
                    continue
                if not is_valid_phone(phone):
                    errors.append(f'第{idx}行：手机号格式不正确')
                    continue
                if not campus_name:
                    errors.append(f'第{idx}行：校区名称为空')
                    continue
                
                if not password:
                    password = phone[-6:] if len(phone) >= 6 else '123456'
                
                campus_id = None
                campus = Campus.query.filter_by(name=campus_name, is_deleted=False).first()
                if not campus:
                    if not current_user.is_super_admin():
                        errors.append(f'第{idx}行：校区"{campus_name}"不存在，仅超级管理员可创建新校区')
                        continue
                    campus = Campus(name=campus_name)
                    db.session.add(campus)
                    db.session.flush()
                campus_id = campus.id
                
                username = phone
                if User.query.filter_by(username=username, is_deleted=False).first():
                    errors.append(f'第{idx}行：账号{username}已存在')
                    continue
                
                user = User(
                    username=username,
                    user_type='admin',
                    real_name=real_name,
                    phone=phone,
                    campus_id=campus_id,
                    role=role,
                    is_active=is_active,
                    can_push_jobs=can_push,
                    can_view_jobs=can_view,
                    can_manage_students=can_manage,
                    created_by=current_user.id
                )
                user.set_password(password)
                db.session.add(user)
                count += 1
            
            if count == 0 and not errors:
                msg = '未导入任何管理员，请检查文件格式'
                if ajax:
                    return jsonify({'success': False, 'message': msg})
                flash(msg, 'warning')
                return render_template('admin/import_admins.html', **ctx)
            
            log_operation('import_admins', 'user', 0, f'批量导入 {count} 个管理员')
            db.session.commit()
            
            if errors:
                result_msg = f'成功导入 {count} 个管理员，{len(errors)} 条警告：' + '; '.join(errors[:5])
                result_type = 'warning'
            else:
                result_msg = f'成功导入 {count} 个管理员'
                result_type = 'success'
            if ajax:
                return jsonify({'success': True, 'message': result_msg, 'count': count, 'errors': errors, 'total_rows': row_count})
            flash(result_msg, result_type)
            return redirect(url_for('admin.users_page'))
        except Exception as e:
            db.session.rollback()
            msg = f'导入失败：{str(e)}'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
    return render_template('admin/import_admins.html', **ctx)


@admin_bp.route('/template_admins')
@admin_required
@super_admin_required
def template_admins():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '管理员导入模板'
    ws.append(['姓名', '手机号', '校区名称', '密码(默认手机号后6位)', '角色(校长/老师等)', 
               '状态(启用/禁用)', '岗位推送权限(是/否)', '岗位查看权限(是/否)', '学员管理权限(是/否)'])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='管理员导入模板.xlsx')


# ==================== 学员导入 ====================
@admin_bp.route('/import_students', methods=['GET', 'POST'])
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def import_students():
    ctx = get_template_context()
    if request.method == 'POST':
        file = request.files.get('file')
        ajax = _is_ajax()
        if not file:
            msg = '请选择文件'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/import_students.html', **ctx)
        if not file.filename.endswith(('.xlsx', '.xls')):
            msg = '请上传Excel文件'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
            return render_template('admin/import_students.html', **ctx)
        try:
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            count = 0
            errors = []

            header_cells = [str(c.value).strip() if c.value is not None else '' for c in ws[1]]
            colmap = {}
            for i, h in enumerate(header_cells):
                if h:
                    colmap.setdefault(h, i)

            def val(row, *names):
                for n in names:
                    if n in colmap and colmap[n] < len(row):
                        return row[colmap[n]]
                return ''

            for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                real_name = str(val(row, '姓名') or '').strip()
                if not real_name:
                    continue
                phone = str(val(row, '手机号') or '').strip()
                id_card = str(val(row, '身份证号(18位)', '身份证号') or '').strip()
                password = str(val(row, '密码(默认身份证后6位)', '密码') or '').strip()
                is_active_str = str(val(row, '状态(启用/禁用)', '状态') or '启用').strip()
                is_active = is_active_str not in ('禁用', 'no', 'false', '0', '×')
                campus_name = str(val(row, '校区名称') or '').strip()
                education = str(val(row, '学历(大专/本科/硕士/博士)', '学历') or '').strip()
                major = str(val(row, '专业') or '').strip()
                intention_city = str(val(row, '意向城市') or '').strip()
                first_intention = str(val(row, '第一意向岗位') or '').strip()
                second_intention = str(val(row, '第二意向岗位') or '').strip()
                third_intention = str(val(row, '第三意向岗位') or '').strip()
                certificate = str(val(row, '证书') or '').strip()
                remark = str(val(row, '备注') or '').strip()
                graduation_date_str = str(val(row, '毕业时间(YYYY-MM-DD)', '毕业时间') or '').strip()
                origin_place = str(val(row, '生源地') or '').strip()

                if not real_name:
                    errors.append(f'第{idx}行：姓名为空')
                    continue
                if not phone:
                    errors.append(f'第{idx}行：手机号为空')
                    continue
                if not is_valid_phone(phone):
                    errors.append(f'第{idx}行：手机号格式不正确')
                    continue
                if not id_card or len(id_card) != 18:
                    errors.append(f'第{idx}行：身份证号格式错误')
                    continue

                if User.query.filter_by(username=phone, is_deleted=False).first():
                    errors.append(f'第{idx}行：手机号{phone}已注册')
                    continue

                auto_gender, birth_date, age = User.parse_id_card(id_card)
                
                if not password:
                    password = id_card[-6:]
                
                graduation_date = None
                if graduation_date_str:
                    try:
                        graduation_date = datetime.strptime(graduation_date_str, '%Y-%m-%d').date()
                    except:
                        pass
                
                campus_id = None
                if campus_name:
                    campus = Campus.query.filter_by(name=campus_name, is_deleted=False).first()
                    if not campus:
                        if not current_user.is_super_admin():
                            errors.append(f'第{idx}行：校区"{campus_name}"不存在，仅超级管理员可创建新校区')
                            continue
                        campus = Campus(name=campus_name)
                        db.session.add(campus)
                        db.session.flush()
                    campus_id = campus.id
                else:
                    campus_id = current_user.campus_id
                
                # 管理员只能导入到当前校区
                if not current_user.is_super_admin() and campus_id != current_user.campus_id:
                    errors.append(f'第{idx}行：无权导入到其他校区')
                    continue
                
                user = User(
                    username=phone,
                    user_type='student',
                    real_name=real_name,
                    phone=phone,
                    id_card=id_card,
                    gender=auto_gender,
                    birth_date=birth_date,
                    education=education,
                    major=major,
                    intention_city=intention_city,
                    first_intention=first_intention,
                    second_intention=second_intention,
                    third_intention=third_intention,
                    certificate=certificate,
                    remark=remark,
                    graduation_date=graduation_date,
                    origin_place=origin_place,
                    campus_id=campus_id,
                    is_active=is_active,
                    created_by=current_user.id
                )
                user.set_password(password)
                db.session.add(user)
                count += 1
            
            if count == 0 and not errors:
                msg = '未导入任何学员，请检查文件格式'
                if ajax:
                    return jsonify({'success': False, 'message': msg})
                flash(msg, 'warning')
                return render_template('admin/import_students.html', **ctx)
            
            log_operation('import_students', 'user', 0, f'批量导入 {count} 个学员')
            db.session.commit()
            
            if errors:
                result_msg = f'成功导入 {count} 个学员，{len(errors)} 条警告：' + '; '.join(errors[:5])
                result_type = 'warning'
            else:
                result_msg = f'成功导入 {count} 个学员'
                result_type = 'success'
            if ajax:
                return jsonify({'success': True, 'message': result_msg, 'count': count, 'errors': errors})
            flash(result_msg, result_type)
            return redirect(url_for('admin.students_page'))
        except Exception as e:
            db.session.rollback()
            msg = f'导入失败：{str(e)}'
            if ajax:
                return jsonify({'success': False, 'message': msg})
            flash(msg, 'danger')
    return render_template('admin/import_students.html', **ctx)


@admin_bp.route('/template_students')
@admin_required
@permission_required(PERMISSION_MANAGE_STUDENTS)
def template_students():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '学员导入模板'
    ws.append(['姓名', '手机号', '身份证号(18位)', '密码(默认身份证后6位)', '状态(启用/禁用)', 
               '校区名称', '学历(大专/本科/硕士/博士)', '专业', '意向城市', '第一意向岗位', 
               '第二意向岗位', '第三意向岗位', '证书', '备注', '毕业时间(YYYY-MM-DD)', '生源地'])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='学员导入模板.xlsx')
