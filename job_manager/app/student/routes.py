from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from ..models import db, Job, PushRecord, OperationLog
from ..permissions import student_required
from . import student_bp


@student_bp.route('/')
@student_required
def index():
    return redirect(url_for('student.my_pushes'))


@student_bp.route('/my_pushes')
@student_required
def my_pushes():
    """学员只能查看推送给自己的岗位"""
    page = request.args.get('page', 1, type=int)
    deadline_filter = request.args.get('deadline_before', '')
    job_id = request.args.get('job_id', '', type=str)

    # 只查询推送给当前学员的岗位
    query = PushRecord.query.filter_by(student_id=current_user.id)

    # 截止时间筛选
    if deadline_filter:
        try:
            days = int(deadline_filter)
            deadline_date = datetime.now() + timedelta(days=days)
            query = query.join(Job).filter(Job.deadline <= deadline_date, Job.deadline >= datetime.now())
        except (ValueError, TypeError):
            pass

    pagination = query.order_by(PushRecord.pushed_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    # 标记为已读
    for push in pagination.items:
        if not push.is_read:
            push.is_read = True
    db.session.commit()

    # 选中的岗位详情
    selected_job = None
    if job_id:
        try:
            job_id_int = int(job_id)
            # 验证权限：只能查看被推送的岗位
            has_push = PushRecord.query.filter_by(
                job_id=job_id_int,
                student_id=current_user.id
            ).first()
            if has_push:
                selected_job = Job.query.get(job_id_int)
        except (ValueError, TypeError):
            pass

    # 默认选中第一个
    if not selected_job and pagination.items:
        selected_job = pagination.items[0].job

    return render_template('student/my_pushes.html',
                         pushes=pagination.items,
                         pagination=pagination,
                         deadline_before=deadline_filter,
                         selected_job=selected_job,
                         now=datetime.now())


@student_bp.route('/job/<int:id>')
@student_required
def job_detail(id):
    """学员只能查看推送给自己的岗位详情"""
    job = Job.query.get_or_404(id)

    # 严格验证权限：只能查看被推送的岗位
    push = PushRecord.query.filter_by(
        job_id=id,
        student_id=current_user.id
    ).first()

    if not push:
        flash('无权查看该岗位', 'danger')
        return redirect(url_for('student.my_pushes'))

    # 标记为已读
    if not push.is_read:
        push.is_read = True
        db.session.commit()

    return render_template('student/job_detail.html', job=job, push=push, now=datetime.now())
