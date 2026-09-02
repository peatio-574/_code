from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)  # 'admin' or 'student'
    real_name = db.Column(db.String(50), default='')
    phone = db.Column(db.String(20), default='')
    email = db.Column(db.String(120), default='')
    avatar = db.Column(db.String(256), default='')
    education = db.Column(db.String(20), default='')  # 学历
    major = db.Column(db.String(100), default='')  # 专业
    is_party_member = db.Column(db.Boolean, default=False)  # 是否党员
    intention_city = db.Column(db.String(100), default='')  # 意向城市
    certificate = db.Column(db.String(200), default='')  # 证书
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 权限字段（内部管理员子账号）
    can_manage_jobs = db.Column(db.Boolean, default=True)
    can_manage_students = db.Column(db.Boolean, default=False)
    can_manage_accounts = db.Column(db.Boolean, default=False)
    can_push_jobs = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.user_type == 'admin'

    def is_student(self):
        return self.user_type == 'student'

    def __repr__(self):
        return f'<User {self.username}>'


class Job(db.Model):
    __tablename__ = 'jobs'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)  # 单位名称
    job_name = db.Column(db.String(100), nullable=False)  # 岗位名称
    education_req = db.Column(db.String(50), default='')  # 学历要求
    major_req = db.Column(db.String(200), default='')  # 专业要求
    certificate_req = db.Column(db.String(200), default='')  # 证书要求
    party_member_req = db.Column(db.Boolean, default=False)  # 党员要求
    work_location = db.Column(db.String(100), default='')  # 工作地点
    recruit_count = db.Column(db.Integer, default=1)  # 招录人数
    deadline = db.Column(db.DateTime)  # 报名截止时间
    job_detail = db.Column(db.Text, default='')  # 岗位详情原文
    tags = db.Column(db.String(500), default='')  # 岗位标签（行业/国企类型）
    status = db.Column(db.String(20), default='active')  # active, inactive
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    creator = db.relationship('User', backref='created_jobs')
    push_records = db.relationship('PushRecord', backref='job', lazy='dynamic')

    def __repr__(self):
        return f'<Job {self.job_name}>'


class PushRecord(db.Model):
    __tablename__ = 'push_records'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    pushed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    pushed_at = db.Column(db.DateTime, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)

    # 关联
    student = db.relationship('User', backref='received_pushes', foreign_keys=[student_id])
    pusher = db.relationship('User', backref='sent_pushes', foreign_keys=[pushed_by])

    def __repr__(self):
        return f'<PushRecord job={self.job_id} student={self.student_id}>'


class OperationLog(db.Model):
    __tablename__ = 'operation_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 操作类型
    target_type = db.Column(db.String(50), default='')  # 操作对象类型
    target_id = db.Column(db.Integer, default=0)  # 操作对象ID
    details = db.Column(db.Text, default='')  # 操作详情
    ip_address = db.Column(db.String(50), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联
    user = db.relationship('User', backref='operation_logs')

    def __repr__(self):
        return f'<OperationLog {self.action} by user {self.user_id}>'
