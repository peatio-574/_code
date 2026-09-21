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
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)


class Certificate(db.Model):
    __tablename__ = 'certificate'

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(50), nullable=False, index=True)           # 姓名
    issue_date = db.Column(db.String(20))                                 # 发证日期
    major = db.Column(db.String(50))                                      # 考级专业
    level_range = db.Column(db.String(20))                                # 起止级
    level = db.Column(db.String(20))                                      # 等级
    org = db.Column(db.String(100))                                       # 报考考级机构
    id_card = db.Column(db.String(50), index=True)                        # 证件号
    nationality = db.Column(db.String(50))                                # 国籍
    ethnicity = db.Column(db.String(50))                                  # 民族
    birth_date = db.Column(db.String(20))                                 # 出生日期
    name_pinyin = db.Column(db.String(100))                               # 姓名全拼
    cert_no = db.Column(db.String(50), index=True)                        # 证书编号

    created_at = db.Column(db.DateTime, default=datetime.now)             # 创建时间
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now)                         # 更新时间

    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)  # 软删除标记
    deleted_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'issue_date': self.issue_date,
            'major': self.major,
            'level_range': self.level_range,
            'level': self.level,
            'org': self.org,
            'id_card': self.id_card,
            'nationality': self.nationality,
            'ethnicity': self.ethnicity,
            'birth_date': self.birth_date,
            'name_pinyin': self.name_pinyin,
            'cert_no': self.cert_no,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
        }

    def __repr__(self):
        return '<Certificate %s %s>' % (self.name, self.cert_no)
