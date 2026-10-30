# -*- coding: utf-8 -*-
"""前台：考试报名收集"""
import re

from flask import render_template, request

from ..api import fail, ok
from ..models import Institution, Registration, db
from . import public_bp


ID_CARD_RE = re.compile(r'^(\d{15}|\d{17}[\dXx])$')


@public_bp.route('/apply', methods=['GET', 'POST'])
def signup():
    """考试报名表单：GET 展示表单，POST 提交报名信息。

    支持按机构链接填写：/new/apply?i=<code>，报名数据会记录对应机构。
    """
    if request.method == 'GET':
        code = (request.args.get('i') or '').strip()
        institution = None
        if code:
            institution = Institution.query.filter_by(code=code, is_deleted=False).first()
            if institution and institution.is_expired():
                return render_template('public/signup.html', institution=None,
                                       institution_code='', expired_message='该报名链接已过期')
        return render_template('public/signup.html', institution=institution,
                               institution_code=code if institution else '')

    payload = request.form
    name = (payload.get('name') or '').strip()
    gender = (payload.get('gender') or '').strip()
    ethnicity = (payload.get('ethnicity') or '').strip()
    nationality = (payload.get('nationality') or '中国').strip()
    id_card = (payload.get('id_card') or '').strip().upper()
    subject = (payload.get('subject') or '').strip()
    level = (payload.get('level') or '').strip().replace('级', '')

    # 所属机构：以链接中的机构编码为准（防止前端篡改），无链接则为空
    code = (payload.get('institution_code') or '').strip()
    institution = None
    if code:
        institution = Institution.query.filter_by(code=code, is_deleted=False).first()
        if institution and institution.is_expired():
            return fail('该报名链接已过期，无法提交')

    errors = []
    if not name:
        errors.append('请填写考生姓名')
    if len(name) > 50:
        errors.append('姓名过长')
    if not gender:
        errors.append('请选择性别')
    if not id_card:
        errors.append('请填写身份证号')
    elif not ID_CARD_RE.match(id_card):
        errors.append('身份证号格式不正确')
    if not subject:
        errors.append('请填写报考科目')
    if not level:
        errors.append('请选择报考级别')
    if errors:
        return fail('；'.join(errors), errors=errors)

    record = Registration(
        name=name, gender=gender, ethnicity=ethnicity, nationality=nationality,
        id_card=id_card, subject=subject, level=level,
        institution_id=institution.id if institution else None,
        institution=institution.name if institution else '',
    )
    db.session.add(record)
    db.session.commit()
    return ok({'id': record.id, 'name': record.name}, message='报名成功')
