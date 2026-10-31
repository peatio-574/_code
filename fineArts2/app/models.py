# -*- coding: utf-8 -*-
"""数据模型"""
from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class Admin(UserMixin, db.Model):
    __tablename__ = 'admin'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # 密码明文（仅用于超管在「账号管理」查看；实际登录校验仍用密码哈希）
    password_plain = db.Column(db.String(100), default='')
    # 角色：admin=全部权限；user=报名/机构管理；institution=仅本机构报名
    role = db.Column(db.String(20), default='admin', nullable=False)
    # 机构账号绑定的机构ID（role=institution 时生效）
    institution_id = db.Column(db.Integer, default=None)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_plain = password

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)


class Registration(db.Model):
    """考试报名信息（前台手机/微信表单收集，后台管理查看）。"""

    __tablename__ = 'registration'

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(50), nullable=False, index=True)      # 考生姓名
    gender = db.Column(db.String(10))                                # 性别
    ethnicity = db.Column(db.String(50))                             # 民族
    nationality = db.Column(db.String(50))                           # 国籍
    id_card = db.Column(db.String(50), index=True)                   # 身份证号
    subject = db.Column(db.String(50))                               # 报考科目
    level = db.Column(db.String(50))                                 # 报考级别
    photo = db.Column(db.String(256))                                # 电子照片文件名

    institution_id = db.Column(db.Integer, index=True)               # 所属机构ID（可空）
    institution = db.Column(db.String(100), index=True)              # 所属机构名称

    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)  # 软删除标记
    deleted_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.now)        # 报名时间
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'gender': self.gender,
            'ethnicity': self.ethnicity,
            'nationality': self.nationality,
            'id_card': self.id_card,
            'subject': self.subject,
            'level': self.level,
            'photo': self.photo or '',
            'has_photo': bool(self.photo),
            'institution_id': self.institution_id,
            'institution': self.institution,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
        }

    def __repr__(self):
        return '<Registration %s %s>' % (self.name, self.id_card)


class Institution(db.Model):
    """报名机构：每个机构对应一个可分享的报名链接（/new/apply?i=<code>）。"""

    __tablename__ = 'institution'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)     # 机构名称
    code = db.Column(db.String(32), unique=True, index=True)         # 链接唯一编码
    # 报名链接有效期（为空表示长期有效）
    expires_at = db.Column(db.DateTime, default=None, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def is_expired(self):
        return bool(self.expires_at and datetime.now() > self.expires_at)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'expires_at': self.expires_at.strftime('%Y-%m-%d') if self.expires_at else '',
            'expired': self.is_expired(),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
        }

    def __repr__(self):
        return '<Institution %s (%s)>' % (self.name, self.code)
