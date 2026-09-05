"""
数据模型定义
包含：校区、用户（超管/管理员/学员）、岗位、推送记录、操作日志
"""
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class Campus(db.Model):
    """
    校区表
    用于存储各校区信息，管理员归属校区
    """
    __tablename__ = 'campuses'
    __table_args__ = {'comment': '校区信息表'}
    
    id = db.Column(db.Integer, primary_key=True, comment='校区ID，主键')
    name = db.Column(db.String(100), unique=True, nullable=False, comment='校区名称')
    is_active = db.Column(db.Boolean, default=True, comment='是否启用：1=启用，0=禁用')
    is_deleted = db.Column(db.Boolean, default=False, comment='是否删除：1=已删除，0=正常')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def __repr__(self):
        return f'<Campus {self.name}>'


class Role(db.Model):
    """
    角色表
    用于存储管理员角色，可由超管自定义
    """
    __tablename__ = 'roles'
    __table_args__ = {'comment': '角色信息表'}
    
    id = db.Column(db.Integer, primary_key=True, comment='角色ID，主键')
    name = db.Column(db.String(50), unique=True, nullable=False, comment='角色名称')
    is_active = db.Column(db.Boolean, default=True, comment='是否启用')
    is_deleted = db.Column(db.Boolean, default=False, comment='是否删除')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def __repr__(self):
        return f'<Role {self.name}>'


class User(UserMixin, db.Model):
    """
    用户表
    存储所有用户信息，包括超级管理员、管理员、学员三种角色
    """
    __tablename__ = 'users'
    __table_args__ = {'comment': '用户信息表（超管/管理员/学员）'}

    id = db.Column(db.Integer, primary_key=True, comment='用户ID，主键')
    username = db.Column(db.String(18), unique=True, nullable=False, index=True, comment='登录账号')
    password_hash = db.Column(db.String(256), nullable=False, comment='密码哈希值')
    password_plain = db.Column(db.String(100), default='', comment='密码明文（仅超管可见）')
    user_type = db.Column(db.String(20), nullable=False, comment='用户类型：super_admin/admin/student')
    
    real_name = db.Column(db.String(50), default='', comment='真实姓名')
    phone = db.Column(db.String(20), default='', comment='手机号码')
    email = db.Column(db.String(120), default='', comment='邮箱')
    id_card = db.Column(db.String(18), default='', comment='身份证号')
    gender = db.Column(db.String(10), default='', comment='性别')
    birth_date = db.Column(db.Date, nullable=True, comment='出生日期')
    avatar = db.Column(db.String(256), default='', comment='头像')
    
    education = db.Column(db.String(20), default='', comment='学历')
    major = db.Column(db.String(100), default='', comment='专业')
    political_status = db.Column(db.String(20), default='', comment='政治面貌')
    is_party_member = db.Column(db.Boolean, default=False, comment='是否党员')
    intention_city = db.Column(db.String(100), default='', comment='意向城市')
    first_intention = db.Column(db.String(100), default='', comment='第一意向岗位')
    second_intention = db.Column(db.String(100), default='', comment='第二意向岗位')
    third_intention = db.Column(db.String(100), default='', comment='第三意向岗位')
    certificate = db.Column(db.String(200), default='', comment='证书')
    remark = db.Column(db.Text, default='', comment='备注')
    graduation_date = db.Column(db.Date, nullable=True, comment='毕业时间')
    origin_place = db.Column(db.String(100), default='', comment='生源地')
    
    campus_id = db.Column(db.Integer, db.ForeignKey('campuses.id'), nullable=True, comment='所属校区')
    role = db.Column(db.String(50), default='', comment='角色名称')
    can_push_jobs = db.Column(db.Boolean, default=False, comment='岗位推送权限')
    can_view_jobs = db.Column(db.Boolean, default=False, comment='岗位查看权限')
    can_manage_students = db.Column(db.Boolean, default=False, comment='学员管理权限')
    
    is_active = db.Column(db.Boolean, default=True, comment='账号状态')
    is_deleted = db.Column(db.Boolean, default=False, comment='是否删除')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, comment='创建人ID')
    
    creator = db.relationship('User', remote_side=[id], backref='created_users')
    campus = db.relationship('Campus', backref='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_plain = password

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_super_admin(self):
        return self.user_type == 'super_admin'

    def is_admin(self):
        return self.user_type in ('super_admin', 'admin')

    def is_student(self):
        return self.user_type == 'student'

    def get_id_card_last6(self):
        if self.id_card and len(self.id_card) >= 6:
            return self.id_card[-6:]
        return ''
    
    def get_age(self):
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return ''
    
    @staticmethod
    def parse_id_card(id_card):
        if len(id_card) != 18:
            return None, None, None
        try:
            birth_str = id_card[6:14]
            birth_date = date(int(birth_str[:4]), int(birth_str[4:6]), int(birth_str[6:8]))
            gender = '男' if int(id_card[16]) % 2 == 1 else '女'
            today = date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return gender, birth_date, age
        except:
            return None, None, None

    def __repr__(self):
        return f'<User {self.username}>'


class Job(db.Model):
    """
    岗位信息表
    """
    __tablename__ = 'jobs'
    __table_args__ = {'comment': '岗位信息表'}

    id = db.Column(db.Integer, primary_key=True, comment='岗位ID')
    province = db.Column(db.String(50), default='', comment='省份')
    city = db.Column(db.String(50), default='', comment='城市')
    job_name = db.Column(db.String(100), nullable=False, comment='职位名称')
    company_name = db.Column(db.String(200), nullable=False, comment='公司名称')
    company_type = db.Column(db.String(50), default='', comment='公司性质')
    company_size = db.Column(db.String(50), default='', comment='公司规模')
    company_industry = db.Column(db.String(100), default='', comment='公司行业')
    recruit_type = db.Column(db.String(50), default='', comment='招聘类型')
    job_nature = db.Column(db.String(50), default='', comment='职位性质')
    job_category = db.Column(db.String(100), default='', comment='职位类别')
    salary_range = db.Column(db.String(50), default='', comment='薪资范围')
    recruit_count = db.Column(db.Integer, default=1, comment='招聘人数')
    education_req = db.Column(db.String(50), default='', comment='学历要求')
    experience_req = db.Column(db.String(50), default='', comment='经验要求')
    major_req = db.Column(db.String(200), default='', comment='专业要求')
    work_location = db.Column(db.String(100), default='', comment='工作地点')
    address = db.Column(db.String(200), default='', comment='详细地址')
    deadline = db.Column(db.DateTime, nullable=True, comment='报名截止时间')
    job_detail = db.Column(db.Text, default='', comment='职位描述')
    status = db.Column(db.String(20), default='active', comment='状态')
    is_deleted = db.Column(db.Boolean, default=False, comment='是否删除')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), comment='创建人')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    creator = db.relationship('User', backref='created_jobs')
    push_records = db.relationship('PushRecord', backref='job', lazy='dynamic')

    def is_expired(self):
        if self.deadline is None:
            return False
        return self.deadline < datetime.now()

    @property
    def salary_display(self):
        s = (self.salary_range or '').replace(' ', '').strip()
        if not s:
            return '面议'
        if not (s.replace('0', '').replace('~', '').replace('-', '').replace('—', '').replace('–', '').replace('至', '').replace('元', '').replace('/', '').replace('月', '').replace(',', '').replace('.', '')):
            return '面议'
        return s

    def __repr__(self):
        return f'<Job {self.job_name}>'


class PushRecord(db.Model):
    """
    岗位推送记录表
    """
    __tablename__ = 'push_records'
    __table_args__ = {'comment': '岗位推送记录表'}

    id = db.Column(db.Integer, primary_key=True, comment='记录ID')
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False, comment='岗位ID')
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, comment='学员ID')
    pushed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, comment='推送人ID')
    pushed_at = db.Column(db.DateTime, default=datetime.now, comment='推送时间')
    is_read = db.Column(db.Boolean, default=False, comment='是否已读')
    is_deleted = db.Column(db.Boolean, default=False, comment='是否删除')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    student = db.relationship('User', backref='received_pushes', foreign_keys=[student_id])
    pusher = db.relationship('User', backref='sent_pushes', foreign_keys=[pushed_by])


class OperationLog(db.Model):
    """
    操作日志表
    """
    __tablename__ = 'operation_logs'
    __table_args__ = {'comment': '操作日志表'}

    id = db.Column(db.Integer, primary_key=True, comment='日志ID')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, comment='操作人')
    action = db.Column(db.String(50), nullable=False, comment='操作类型')
    target_type = db.Column(db.String(50), default='', comment='操作对象类型')
    target_id = db.Column(db.Integer, default=0, comment='操作对象ID')
    details = db.Column(db.Text, default='', comment='操作详情')
    ip_address = db.Column(db.String(50), default='', comment='IP地址')
    is_deleted = db.Column(db.Boolean, default=False, comment='是否删除')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    user = db.relationship('User', backref='operation_logs')
