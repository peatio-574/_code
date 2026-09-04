from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from ..models import db, Job, PushRecord
from ..permissions import student_required
from . import student_bp


@student_bp.route('/')
@student_required
def index():
    return redirect(url_for('student.my_pushes'))


@student_bp.route('/my_pushes')
@student_required
def my_pushes():
    """学员只能查看推送给自己的、未过期的岗位"""
    page = request.args.get('page', 1, type=int)
    deadline_filter = request.args.get('deadline_before', '')
    job_id = request.args.get('job_id', '', type=str)

    query = PushRecord.query.filter_by(student_id=current_user.id, is_deleted=False)
    query = query.join(Job).filter(
        Job.is_deleted == False,
        Job.status == 'active',
        db.or_(Job.deadline == None, Job.deadline >= datetime.now())
    )

    if deadline_filter:
        try:
            days = int(deadline_filter)
            deadline_date = datetime.now() + timedelta(days=days)
            query = query.filter(Job.deadline <= deadline_date, Job.deadline >= datetime.now())
        except (ValueError, TypeError):
            pass

    pagination = query.order_by(PushRecord.pushed_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

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
        except (ValueError, TypeError):
            pass

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
    job = Job.query.filter_by(id=id, is_deleted=False).first_or_404()
    if job.is_expired():
        flash('该岗位已过期', 'danger')
        return redirect(url_for('student.my_pushes'))
    
    push = PushRecord.query.filter_by(
        job_id=id, student_id=current_user.id, is_deleted=False
    ).first()
    if not push:
        flash('无权查看该岗位', 'danger')
        return redirect(url_for('student.my_pushes'))
    
    if not push.is_read:
        push.is_read = True
        db.session.commit()

    return render_template('student/job_detail.html', job=job, push=push, now=datetime.now())
