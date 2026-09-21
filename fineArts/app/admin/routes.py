# -*- coding: utf-8 -*-
"""后台管理：证书管理"""
import io
from datetime import datetime

from flask import (current_app, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from ..api import fail, ok, pagination_dict
from ..excel_utils import COLUMNS, build_template, parse_workbook
from ..models import db, Admin, Certificate
from . import admin_bp

FIELDS = [c[1] for c in COLUMNS]


# --------------------------------------------------------------------------- #
# 登录 / 退出
# --------------------------------------------------------------------------- #
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.certificates'))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = Admin.query.filter_by(username=username).first()
        if user and user.verify_password(password):
            login_user(user)
            return redirect(request.args.get('next') or url_for('admin.certificates'))
        flash('用户名或密码错误', 'error')
    return render_template('admin/login.html')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


@admin_bp.route('/password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改当前管理员密码"""
    if request.method == 'POST':
        old_password = request.form.get('old_password') or ''
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not current_user.verify_password(old_password):
            flash('原密码错误', 'error')
        elif len(new_password) < 6:
            flash('新密码至少 6 位', 'error')
        elif new_password != confirm_password:
            flash('两次输入的新密码不一致', 'error')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('密码修改成功', 'success')
            return redirect(url_for('admin.change_password'))

    return render_template('admin/password.html')


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _cert_no_exists(cert_no, exclude_id=None):
    if not cert_no:
        return False
    query = Certificate.query.filter(Certificate.cert_no == cert_no,
                                     Certificate.is_deleted.is_(False))
    if exclude_id:
        query = query.filter(Certificate.id != exclude_id)
    return query.first() is not None


# --------------------------------------------------------------------------- #
# 证书列表
# --------------------------------------------------------------------------- #
@admin_bp.route('/', methods=['GET'])
@admin_bp.route('/certificates', methods=['GET'])
@login_required
def certificates():
    """证书管理页面（固定 HTML，数据由 /admin/api/certificates 填充）"""
    majors = [row[0] for row in db.session.query(Certificate.major)
              .filter(Certificate.major.isnot(None), Certificate.major != '')
              .distinct().all()]
    return render_template('admin/certificates.html', majors=sorted(majors))


def _serialize(cert):
    data = cert.to_dict()
    data['is_deleted'] = cert.is_deleted
    return data


@admin_bp.route('/api/certificates')
def api_certificates():
    """证书列表接口（统一 JSON 格式：success + pagination + data）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', current_app.config['PER_PAGE'], type=int)
    keyword = (request.args.get('q') or '').strip()
    major = (request.args.get('major') or '').strip()

    query = Certificate.query.filter(Certificate.is_deleted.is_(False))

    if keyword:
        like = '%%%s%%' % keyword
        query = query.filter(db.or_(Certificate.name.like(like),
                                    Certificate.cert_no.like(like),
                                    Certificate.id_card.like(like)))
    if major:
        query = query.filter(Certificate.major == major)

    pagination = query.order_by(Certificate.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    data = [_serialize(c) for c in pagination.items]
    return ok(data, pagination=pagination_dict(pagination))


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _validate(data):
    errors = []
    for title, field, required, _w in COLUMNS:
        if required and not data.get(field):
            errors.append('%s不能为空' % title)
    return errors


# --------------------------------------------------------------------------- #
# 软删除
# --------------------------------------------------------------------------- #
@admin_bp.route('/certificate/<int:cid>/delete', methods=['POST'])
@login_required
def certificate_delete(cid):
    cert = Certificate.query.get_or_404(cid)
    cert.is_deleted = True
    cert.deleted_at = datetime.now()
    db.session.commit()
    flash('已删除', 'success')
    return redirect(request.referrer or url_for('admin.certificates'))


@admin_bp.route('/api/certificate', methods=['POST'])
def api_certificate_create():
    """新增证书（弹窗用）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    payload = request.get_json(silent=True) or request.form
    data = {field: (payload.get(field) or '').strip() for field in FIELDS}

    errors = _validate(data)
    if not errors and _cert_no_exists(data['cert_no']):
        errors.append('证书编号已存在：%s' % data['cert_no'])
    if errors:
        return fail('；'.join(errors), errors=errors)

    cert = Certificate(**data)
    db.session.add(cert)
    db.session.commit()
    return ok(_serialize(cert), message='新增成功')


@admin_bp.route('/api/certificate/<int:cid>', methods=['GET'])
def api_certificate_get(cid):
    """获取单条证书（编辑弹窗用）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    cert = Certificate.query.get_or_404(cid)
    return ok(_serialize(cert))


@admin_bp.route('/api/certificate/<int:cid>', methods=['POST'])
def api_certificate_update(cid):
    """更新单条证书（编辑弹窗用）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    cert = Certificate.query.get_or_404(cid)
    payload = request.get_json(silent=True) or request.form
    data = {field: (payload.get(field) or '').strip() for field in FIELDS}

    errors = _validate(data)
    if not errors and _cert_no_exists(data['cert_no'], exclude_id=cid):
        errors.append('证书编号已存在：%s' % data['cert_no'])
    if errors:
        return fail('；'.join(errors), errors=errors)

    for field in FIELDS:
        setattr(cert, field, data[field])
    db.session.commit()
    return ok(_serialize(cert), message='保存成功')


@admin_bp.route('/certificates/batch_delete', methods=['POST'])
def certificates_batch_delete():
    """批量软删除"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)

    payload = request.get_json(silent=True) or {}
    ids = []
    for value in (payload.get('ids') or []):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return fail('请选择要删除的证书')

    certs = Certificate.query.filter(Certificate.id.in_(ids),
                                     Certificate.is_deleted.is_(False)).all()
    now = datetime.now()
    for cert in certs:
        cert.is_deleted = True
        cert.deleted_at = now
    db.session.commit()
    return ok({'deleted': len(certs)}, message='已删除 %d 条' % len(certs))


@admin_bp.route('/certificates/import', methods=['POST'])
def certificates_import():
    """导入证书（Excel），逐行校验必填字段并做证书编号去重（返回 JSON）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)

    file = request.files.get('file')
    if not file or not file.filename:
        return fail('请选择要导入的 Excel 文件')

    rows, fatal = parse_workbook(file.stream)
    if fatal:
        return fail(fatal)

    summary = {'total': len(rows), 'ok': 0, 'failed': 0, 'items': []}
    seen = set()
    for row in rows:
        cert_no = row.get('cert_no', '')
        name = row.get('name', '')
        errors = list(row.get('errors', []))

        if cert_no in seen:
            errors.append('文件内证书编号重复')
        elif _cert_no_exists(cert_no):
            errors.append('证书编号已存在')

        if errors:
            summary['failed'] += 1
            summary['items'].append({'row': row['_row'], 'name': name,
                                     'cert_no': cert_no, 'ok': False,
                                     'message': '；'.join(errors)})
            continue

        seen.add(cert_no)
        db.session.add(Certificate(**{f: row.get(f, '') for f in FIELDS}))
        summary['ok'] += 1
        summary['items'].append({'row': row['_row'], 'name': name,
                                 'cert_no': cert_no, 'ok': True,
                                 'message': '导入成功'})
    db.session.commit()
    return ok(summary, message='导入完成：成功 %d 条，失败 %d 条'
              % (summary['ok'], summary['failed']))


@admin_bp.route('/certificates/template')
@login_required
def certificates_template():
    buf = build_template()
    return send_file(buf, as_attachment=True,
                     download_name='证书导入模板.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@admin_bp.route('/certificates/export', methods=['GET', 'POST'])
@login_required
def certificates_export():
    """导出证书数据；传入 ids（GET 逗号分隔 / POST JSON）时只导出选中项"""
    raw_ids = []
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        raw_ids = payload.get('ids') or []
    elif request.args.get('ids'):
        raw_ids = request.args.get('ids').split(',')

    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue

    query = Certificate.query.filter(Certificate.is_deleted.is_(False))
    if ids:
        query = query.filter(Certificate.id.in_(ids))
    certs = query.order_by(Certificate.id.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = '证书数据'
    headers = [c[0] for c in COLUMNS] + ['创建时间', '更新时间']
    header_fill = PatternFill('solid', fgColor='D9D9D9')
    header_font = Font(color='000000', bold=True)
    thin = Side(style='thin', color='D9D9D9')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for idx, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=idx, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')
        cell.border = border
        ws.column_dimensions[cell.column_letter].width = 18

    for r, cert in enumerate(certs, start=2):
        for c, field in enumerate(FIELDS, start=1):
            cell = ws.cell(row=r, column=c, value=getattr(cert, field, ''))
            cell.border = border
            if field in ('id_card', 'cert_no', 'birth_date', 'issue_date'):
                cell.number_format = '@'
        ws.cell(row=r, column=len(FIELDS) + 1,
                value=cert.created_at.strftime('%Y-%m-%d %H:%M:%S') if cert.created_at else '')
        ws.cell(row=r, column=len(FIELDS) + 2,
                value=cert.updated_at.strftime('%Y-%m-%d %H:%M:%S') if cert.updated_at else '')

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='证书数据导出.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
