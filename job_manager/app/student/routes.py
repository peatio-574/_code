from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import re
from ..models import db, Job, PushRecord, OperationLog
from ..permissions import student_required
from . import student_bp


def _salary_interval(s):
    nums = [int(n) for n in re.findall(r'\d+', s or '')]
    if not nums:
        return None
    lo, hi = nums[0], nums[-1]
    if lo == 0 and hi == 0:
        return None
    return min(lo, hi), max(lo, hi)


def _salary_match(salary_range, band):
    interval = _salary_interval(salary_range)
    if interval is None:
        return False
    lo, hi = interval
    if band == '0-5000':
        return lo <= 5000
    if band == '5000-8000':
        return lo <= 8000 and hi >= 5000
    if band == '8000-12000':
        return lo <= 12000 and hi >= 8000
    if band == '12000-20000':
        return lo <= 20000 and hi >= 12000
    if band == '20000+':
        return hi >= 20000
    return False


def _size_num(company_size):
    nums = re.findall(r'\d+', company_size or '')
    return int(nums[0]) if nums else None


def _size_match(company_size, band):
    n = _size_num(company_size)
    if n is None:
        return False
    if band == '0-50':
        return n < 50
    if band == '50-200':
        return 50 <= n < 200
    if band == '200-1000':
        return 200 <= n < 1000
    if band == '1000-5000':
        return 1000 <= n < 5000
    if band == '5000+':
        return n >= 5000
    return False

@student_bp.route('/')
@student_required
def index():
    return redirect(url_for('student.my_pushes'))


@student_bp.route('/my_pushes')
@student_required
def my_pushes():
    """学员只能查看推送给自己的、未过期的岗位"""
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '').strip()
    education = request.args.get('education', '').strip()
    deadline_filter = request.args.get('deadline_before', '')
    sort = request.args.get('sort', '').strip()
    city = request.args.get('city', '').strip()
    salary = request.args.get('salary', '').strip()
    company_type = request.args.get('company_type', '').strip()
    company_size = request.args.get('company_size', '').strip()
    job_id = request.args.get('job_id', '', type=str)

    query = PushRecord.query.filter_by(student_id=current_user.id, is_deleted=False, is_revoked=False)
    query = query.join(Job).filter(
        Job.is_deleted == False,
        Job.status == 'active',
        db.or_(Job.deadline == None, Job.deadline >= datetime.now())
    )

    if keyword:
        query = query.filter(db.or_(
            Job.job_name.contains(keyword),
            Job.company_name.contains(keyword)
        ))

    if education:
        if education == '不限':
            query = query.filter(db.or_(Job.education_req == '不限',
                                        Job.education_req == '', Job.education_req == None))
        else:
            query = query.filter(Job.education_req == education)

    if city:
        query = query.filter(Job.city.contains(city))

    if company_type:
        query = query.filter(Job.company_type == company_type)

    if deadline_filter:
        try:
            days = int(deadline_filter)
            deadline_date = datetime.now() + timedelta(days=days)
            query = query.filter(Job.deadline <= deadline_date, Job.deadline >= datetime.now())
        except (ValueError, TypeError):
            pass

    if salary:
        # 薪资为自由文本，仅在候选（本学员已推送且满足其他条件）范围内解析匹配，避免全表扫描
        candidate_rows = query.with_entities(Job.id, Job.salary_range).all()
        matched_ids = [jid for jid, sr in candidate_rows if _salary_match(sr, salary)]
        query = query.filter(Job.id.in_(matched_ids or [-1]))

    if company_size:
        # 公司规模为文本，仅在候选（本学员已推送且满足其他条件）范围内解析匹配，避免全表扫描
        size_rows = query.with_entities(Job.id, Job.company_size).all()
        matched_ids = [jid for jid, cs in size_rows if _size_match(cs, company_size)]
        query = query.filter(Job.id.in_(matched_ids or [-1]))

    if sort == 'newest':
        query = query.order_by(Job.created_at.desc())
    else:
        query = query.order_by(PushRecord.pushed_at.desc())

    pagination = query.paginate(page=page, per_page=20, error_out=False)

    for push in pagination.items:
        if not push.is_read:
            push.is_read = True
    db.session.commit()

    selected_job = None
    if job_id:
        try:
            job_id_int = int(job_id)
            has_push = PushRecord.query.filter_by(
                job_id=job_id_int, student_id=current_user.id, is_deleted=False
            ).first()
            if has_push:
                job = Job.query.filter_by(id=job_id_int, is_deleted=False).first()
                if job and not job.is_expired():
                    selected_job = job
                    if not has_push.is_read:
                        has_push.is_read = True
                        db.session.commit()
        except (ValueError, TypeError):
            pass

    if not selected_job and pagination.items:
        selected_job = pagination.items[0].job

    cities = [r[0] for r in db.session.query(Job.city).filter(
        Job.is_deleted == False,
        Job.city != '',
        Job.city.isnot(None)
    ).distinct().all()]
    try:
        import locale
        locale.setlocale(locale.LC_COLLATE, 'zh_CN')
        cities.sort(key=locale.strxfrm)
    except Exception:
        cities.sort()

    return render_template('student/my_pushes.html',
                         pushes=pagination.items,
                         pagination=pagination,
                         keyword=keyword,
                         education=education,
                         deadline_before=deadline_filter,
                         sort=sort,
                         city=city,
                         salary=salary,
                         company_type=company_type,
                         company_size=company_size,
                         cities=cities,
                         selected_job=selected_job,
                         now=datetime.now())


@student_bp.route('/my_pushes/api')
@student_required
def my_pushes_api():
    """岗位列表JSON接口：支持分页与过滤，返回岗位卡片数据"""
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '').strip()
    education = request.args.get('education', '').strip()
    deadline_filter = request.args.get('deadline_before', '')
    sort = request.args.get('sort', '').strip()
    city = request.args.get('city', '').strip()
    salary = request.args.get('salary', '').strip()
    company_type = request.args.get('company_type', '').strip()
    company_size = request.args.get('company_size', '').strip()
    per_page = request.args.get('per_page', 10, type=int)

    query = PushRecord.query.filter_by(student_id=current_user.id, is_deleted=False, is_revoked=False)
    query = query.join(Job).filter(
        Job.is_deleted == False,
        Job.status == 'active',
        db.or_(Job.deadline == None, Job.deadline >= datetime.now())
    )

    if keyword:
        query = query.filter(db.or_(
            Job.job_name.contains(keyword),
            Job.company_name.contains(keyword)
        ))

    if education:
        if education == '不限':
            query = query.filter(db.or_(Job.education_req == '不限',
                                        Job.education_req == '', Job.education_req == None))
        else:
            query = query.filter(Job.education_req == education)

    if city:
        query = query.filter(Job.city.contains(city))

    if company_type:
        query = query.filter(Job.company_type == company_type)

    if deadline_filter:
        try:
            days = int(deadline_filter)
            deadline_date = datetime.now() + timedelta(days=days)
            query = query.filter(Job.deadline <= deadline_date, Job.deadline >= datetime.now())
        except (ValueError, TypeError):
            pass

    if salary:
        # 薪资为自由文本，仅在候选（本学员已推送且满足其他条件）范围内解析匹配，避免全表扫描
        candidate_rows = query.with_entities(Job.id, Job.salary_range).all()
        matched_ids = [jid for jid, sr in candidate_rows if _salary_match(sr, salary)]
        query = query.filter(Job.id.in_(matched_ids or [-1]))

    if company_size:
        # 公司规模为文本，仅在候选（本学员已推送且满足其他条件）范围内解析匹配，避免全表扫描
        size_rows = query.with_entities(Job.id, Job.company_size).all()
        matched_ids = [jid for jid, cs in size_rows if _size_match(cs, company_size)]
        query = query.filter(Job.id.in_(matched_ids or [-1]))

    if sort == 'newest':
        query = query.order_by(Job.created_at.desc())
    else:
        query = query.order_by(PushRecord.pushed_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    now = datetime.now()

    for push in pagination.items:
        if not push.is_read:
            push.is_read = True
    db.session.commit()

    items = []
    for push in pagination.items:
        job = push.job
        items.append({
            'id': job.id,
            'job_name': job.job_name,
            'company_name': job.company_name,
            'company_size': job.company_size,
            'company_industry': job.company_industry,
            'salary_display': job.salary_display,
            'education_req': job.education_req,
            'experience_req': job.experience_req,
            'job_category': job.job_category,
            'work_location': job.work_location,
            'recruit_count': job.recruit_count,
            'deadline': job.deadline.strftime('%Y-%m-%d') if job.deadline else '',
            'is_new': bool(job.created_at and (now - job.created_at).days <= 3),
            'selected': False
        })

    return {
        'success': True,
        'items': items,
        'has_more': pagination.has_next,
        'next_page': pagination.next_num if pagination.has_next else None,
        'page': pagination.page,
    }


@student_bp.route('/job/<int:id>')
@student_required
def job_detail(id):
    job = Job.query.filter_by(id=id, is_deleted=False).first_or_404()
    if job.is_expired():
        flash('该岗位已过期', 'danger')
        return redirect(url_for('student.my_pushes'))
    
    push = PushRecord.query.filter_by(
        job_id=id, student_id=current_user.id, is_deleted=False, is_revoked=False
    ).first()
    if not push:
        flash('无权查看该岗位', 'danger')
        return redirect(url_for('student.my_pushes'))
    
    if not push.is_read:
        push.is_read = True
        db.session.commit()

    return render_template('student/job_detail.html', job=job, push=push, now=datetime.now())


# ==================== 我的操作日志（仅本人可见） ====================
@student_bp.route('/logs')
@student_required
def logs_page():
    """学员操作日志页面（HTML骨架，数据由前端异步加载）"""
    return render_template('admin/logs_list.html', logs_api_url=url_for('student.logs_data'))


@student_bp.route('/logs/data')
@student_required
def logs_data():
    """学员操作日志数据接口：仅返回当前学员自己的操作记录"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    action = request.args.get('action', '').strip()

    if per_page not in [20, 50, 100]:
        per_page = 20

    query = OperationLog.query.filter_by(is_deleted=False, user_id=current_user.id)
    if action:
        query = query.filter_by(action=action)

    pagination = query.order_by(OperationLog.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    logs = []
    for log in pagination.items:
        logs.append({
            'id': log.id,
            'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '-',
            'operator': (log.user.real_name or log.user.username) if log.user else '-',
            'action': log.action,
            'details': log.details or '-',
            'ip_address': log.ip_address,
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
