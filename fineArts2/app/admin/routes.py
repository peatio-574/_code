# -*- coding: utf-8 -*-
"""后台管理：报名、机构、账号"""
import base64
import io
import os
import re
from datetime import datetime, timedelta

from flask import (current_app, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from ..api import fail, ok, pagination_dict
from ..models import db, Admin, Registration, Institution
from ..qr import generate_qr_png
from . import admin_bp


# --------------------------------------------------------------------------- #
# 登录 / 退出
# --------------------------------------------------------------------------- #
def _admin_prefix():
    return current_app.config.get('ADMIN_ROUTE_PREFIX', '/new/manager')


def _home_endpoint(user):
    """登录后的首页统一进入报名管理。"""
    return url_for('admin.registrations')


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_home_endpoint(current_user))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = Admin.query.filter_by(username=username).first()
        if user and user.verify_password(password):
            login_user(user)
            return redirect(request.args.get('next') or _home_endpoint(user))
        flash('用户名或密码错误', 'error')
    return render_template('admin/login.html')


@admin_bp.before_request
def _restrict_limited_account():
    """按角色限制后台访问权限。

    - admin：全部页面
    - user：报名管理、机构管理、修改密码
    - institution：仅本机构报名管理
    """
    if not current_user.is_authenticated:
        return None
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role == 'admin':
        return None

    path = request.path
    prefix = _admin_prefix()

    if role == 'institution':
        allowed = (
            prefix + '/registrations',
            prefix + '/registration/',
            prefix + '/api/registrations',
            prefix + '/api/registration/',
            prefix + '/password',
            prefix + '/logout',
        )
        if path.startswith(allowed):
            return None
        if path in (prefix, prefix + '/'):
            return redirect(url_for('admin.registrations'))
        if path.startswith(prefix + '/api/'):
            return fail('无权访问', status=403)
        flash('无权访问该页面', 'error')
        return redirect(url_for('admin.registrations'))

    # role == 'user'：报名管理、机构管理、账号管理
    allowed = (
        prefix + '/registrations',
        prefix + '/registration/',
        prefix + '/api/registrations',
        prefix + '/api/registration/',
        prefix + '/institutions',
        prefix + '/api/institution',
        prefix + '/institution/',
        prefix + '/accounts',
        prefix + '/api/accounts',
        prefix + '/api/account',
        prefix + '/password',
        prefix + '/logout',
    )
    if path.startswith(allowed):
        return None
    if path in (prefix, prefix + '/'):
        return redirect(url_for('admin.registrations'))
    if path.startswith(prefix + '/api/'):
        return fail('无权访问', status=403)
    flash('无权访问该页面', 'error')
    return redirect(url_for('admin.registrations'))


def _admin_only():
    """仅超管可访问。"""
    return (getattr(current_user, 'role', 'admin') or 'admin') == 'admin'


def _reg_scope_query():
    """报名数据范围：机构账号仅能看到本机构数据。"""
    query = Registration.query.filter(Registration.is_deleted.is_(False))
    if (getattr(current_user, 'role', '') or '') == 'institution':
        query = query.filter(Registration.institution_id == current_user.institution_id)
    return query


def _can_access_reg(reg):
    """判断当前账号是否有权访问该条报名。"""
    if (getattr(current_user, 'role', '') or '') == 'institution':
        return reg.institution_id == current_user.institution_id
    return True


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
# 考试报名管理
# --------------------------------------------------------------------------- #
@admin_bp.route('/', methods=['GET'])
@login_required
def index():
    return redirect(url_for('admin.registrations'))


@admin_bp.route('/registrations', methods=['GET'])
@login_required
def registrations():
    """报名管理页面（固定 HTML，数据由 /new/manager/api/registrations 填充）"""
    if (getattr(current_user, 'role', '') or '') == 'institution':
        names = []
    else:
        names = [row[0] for row in db.session.query(Registration.institution)
                 .filter(Registration.institution.isnot(None), Registration.institution != '',
                         Registration.is_deleted.is_(False))
                 .distinct().all()]
    return render_template('admin/registrations.html', institutions=sorted(names))


def _reg_serialize(reg):
    return reg.to_dict()


@admin_bp.route('/api/registrations')
def api_registrations():
    """报名列表接口（统一 JSON 格式：success + pagination + data）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', current_app.config['PER_PAGE'], type=int)
    keyword = (request.args.get('q') or '').strip()
    subject = (request.args.get('subject') or '').strip()

    query = _reg_scope_query()
    if keyword:
        like = '%%%s%%' % keyword
        query = query.filter(db.or_(Registration.name.like(like),
                                    Registration.id_card.like(like),
                                    Registration.subject.like(like)))
    if subject:
        query = query.filter(Registration.subject == subject)
    institution = (request.args.get('institution') or '').strip()
    if institution:
        query = query.filter(Registration.institution == institution)

    # 排序：所有字段支持 asc/desc
    sortable = {
        'id': Registration.id,
        'institution': Registration.institution,
        'name': Registration.name,
        'gender': Registration.gender,
        'ethnicity': Registration.ethnicity,
        'nationality': Registration.nationality,
        'id_card': Registration.id_card,
        # 科目级别：按科目、级别依次排序
        'subject': Registration.subject,
        'level': Registration.level,
        'subject_level': Registration.subject,
        'created_at': Registration.created_at,
        'updated_at': Registration.updated_at,
    }
    sort_field = (request.args.get('sort') or '').strip()
    sort_order = (request.args.get('order') or 'desc').strip().lower()
    column = sortable.get(sort_field)
    if column is not None:
        order_exprs = [column.asc() if sort_order == 'asc' else column.desc()]
        if sort_field in ('subject', 'subject_level'):
            order_exprs.append(
                Registration.level.asc() if sort_order == 'asc' else Registration.level.desc())
        query = query.order_by(*order_exprs)
    else:
        query = query.order_by(Registration.id.desc())

    pagination = query.paginate(
        page=page, per_page=per_page, error_out=False)
    data = [_reg_serialize(r) for r in pagination.items]
    return ok(data, pagination=pagination_dict(pagination))


@admin_bp.route('/api/registration/<int:rid>', methods=['GET'])
def api_registration_get(rid):
    """获取单条报名（详情弹窗用）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    reg = Registration.query.get_or_404(rid)
    if not _can_access_reg(reg):
        return fail('无权访问该报名', status=403)
    return ok(_reg_serialize(reg))


@admin_bp.route('/api/registration/<int:rid>', methods=['POST'])
def api_registration_update(rid):
    """编辑单条报名"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    reg = Registration.query.get_or_404(rid)
    if not _can_access_reg(reg):
        return fail('无权访问该报名', status=403)
    payload = request.form

    name = (payload.get('name') or '').strip()
    if not name:
        return fail('请填写考生姓名')

    id_card = (payload.get('id_card') or '').strip().upper()
    if id_card and not re.match(r'^(\d{15}|\d{17}[\dXx])$', id_card):
        return fail('身份证号格式不正确')

    reg.name = name
    reg.gender = (payload.get('gender') or '').strip()
    reg.ethnicity = (payload.get('ethnicity') or '').strip()
    reg.nationality = (payload.get('nationality') or '').strip()
    reg.id_card = id_card
    # 后台「科目级别」合并输入：拆分科目与级别（未传时保留原值）
    if 'subject_level' in payload or 'subject' in payload:
        subject_level = (payload.get('subject_level') or '').strip()
        if subject_level:
            m = re.match(r'^(.*?)[\s\-_/]*([0-9]{1,2})\s*级?$', subject_level)
            if m and m.group(1).strip():
                reg.subject = m.group(1).strip()
                reg.level = m.group(2).strip()
            else:
                reg.subject = subject_level
                reg.level = ''
        else:
            reg.subject = (payload.get('subject') or '').strip()
            reg.level = (payload.get('level') or '').strip().replace('级', '')

    db.session.commit()
    return ok(_reg_serialize(reg), message='保存成功')


@admin_bp.route('/registration/<int:rid>/delete', methods=['POST'])
@login_required
def registration_delete(rid):
    reg = Registration.query.get_or_404(rid)
    if not _can_access_reg(reg):
        flash('无权操作该报名', 'error')
        return redirect(url_for('admin.registrations'))
    reg.is_deleted = True
    reg.deleted_at = datetime.now()
    db.session.commit()
    flash('已删除', 'success')
    return redirect(request.referrer or url_for('admin.registrations'))


@admin_bp.route('/registrations/batch_delete', methods=['POST'])
def registrations_batch_delete():
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
        return fail('请选择要删除的报名')

    query = _reg_scope_query().filter(Registration.id.in_(ids))
    regs = query.all()
    now = datetime.now()
    for reg in regs:
        reg.is_deleted = True
        reg.deleted_at = now
    db.session.commit()
    return ok({'deleted': len(regs)}, message='已删除 %d 条' % len(regs))


@admin_bp.route('/registrations/export', methods=['GET', 'POST'])
@login_required
def registrations_export():
    """导出报名数据；传入 ids 时只导出选中项"""
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

    query = _reg_scope_query()
    if ids:
        query = query.filter(Registration.id.in_(ids))
    regs = query.order_by(Registration.id.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = '报名数据'
    headers = ['姓名', '身份证号', '性别', '报考科目', '报考级别', '民族', '国籍', '所属机构', '报名时间']
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

    for r, reg in enumerate(regs, start=2):
        values = [reg.name, reg.id_card, reg.gender, reg.subject, reg.level, reg.ethnicity,
                  reg.nationality, reg.institution,
                  reg.created_at.strftime('%Y-%m-%d %H:%M:%S') if reg.created_at else '']
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = border
            if c == 2:
                cell.number_format = '@'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='报名数据导出.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# --------------------------------------------------------------------------- #
# 报名机构管理（按机构生成报名链接）
# --------------------------------------------------------------------------- #
def _signup_link(code):
    """机构报名链接：按当前访问域名生成（本地即 127.0.0.1，线上即线上域名）。"""
    return url_for('public.signup', i=code, _external=True)


def _inst_serialize(inst):
    data = inst.to_dict()
    data['link'] = _signup_link(inst.code)
    data['count'] = Registration.query.filter(
        Registration.institution_id == inst.id, Registration.is_deleted.is_(False)).count()
    account = Admin.query.filter_by(institution_id=inst.id, role='institution').first()
    data['account'] = account.username if account else ''
    data['password'] = (account.password_plain or '') if account else ''
    return data


@admin_bp.route('/institutions', methods=['GET'])
@login_required
def institutions():
    """机构管理页面（固定 HTML，数据由 /new/manager/api/institutions 填充）"""
    return render_template('admin/institutions.html')


@admin_bp.route('/api/institutions')
def api_institutions():
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', current_app.config['PER_PAGE'], type=int)
    keyword = (request.args.get('q') or '').strip()

    query = Institution.query.filter(Institution.is_deleted.is_(False))
    if keyword:
        query = query.filter(Institution.name.like('%%%s%%' % keyword))
    pagination = query.order_by(Institution.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    changed = False
    for inst in pagination.items:
        if not Admin.query.filter_by(institution_id=inst.id, role='institution').first():
            account = Admin(username=inst.code, role='institution', institution_id=inst.id)
            account.set_password('user123')
            db.session.add(account)
            changed = True
    if changed:
        db.session.commit()
    data = [_inst_serialize(i) for i in pagination.items]
    return ok(data, pagination=pagination_dict(pagination))


def _parse_expiry(value):
    """解析有效期（YYYY-MM-DD），空值返回 (None)；格式非法抛 ValueError。"""
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], '%Y-%m-%d')
    except ValueError:
        raise ValueError('有效期格式应为 YYYY-MM-DD')


@admin_bp.route('/api/institution', methods=['POST'])
def api_institution_create():
    """新增机构并生成报名链接（含有效期，默认 6 个月）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    payload = request.get_json(silent=True) or request.form
    name = (payload.get('name') or '').strip()
    if not name:
        return fail('请填写机构名称')
    if len(name) > 100:
        return fail('机构名称过长')
    if Institution.query.filter(Institution.name == name, Institution.is_deleted.is_(False)).first():
        return fail('该机构已存在')

    try:
        expires_at = _parse_expiry(payload.get('expires_at'))
    except ValueError as exc:
        return fail(str(exc))
    if expires_at is None:
        expires_at = datetime.now() + timedelta(days=183)  # 默认 6 个月

    import secrets
    code = secrets.token_urlsafe(6).replace('-', 'A').replace('_', 'B')[:10]
    while Institution.query.filter_by(code=code).first():
        code = secrets.token_urlsafe(6).replace('-', 'A').replace('_', 'B')[:10]
    inst = Institution(name=name, code=code, expires_at=expires_at)
    db.session.add(inst)
    db.session.flush()

    # 自动为该机构生成登录账号：账号即机构编码，默认密码 user123
    account = Admin(username=code, role='institution', institution_id=inst.id)
    account.set_password('user123')
    db.session.add(account)
    db.session.commit()
    return ok(_inst_serialize(inst), message='机构已创建，并已生成登录账号')


@admin_bp.route('/api/institution/<int:iid>', methods=['POST'])
def api_institution_update(iid):
    """修改机构（名称、有效期）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    inst = Institution.query.get_or_404(iid)
    payload = request.get_json(silent=True) or request.form

    name = (payload.get('name') or '').strip()
    if name:
        exists = Institution.query.filter(
            Institution.name == name, Institution.is_deleted.is_(False), Institution.id != iid).first()
        if exists:
            return fail('该机构名称已存在')
        inst.name = name
        # 同步更新报名记录中的机构名称
        Registration.query.filter(Registration.institution_id == inst.id).update(
            {Registration.institution: name}, synchronize_session=False)

    if 'expires_at' in payload:
        try:
            inst.expires_at = _parse_expiry(payload.get('expires_at'))
        except ValueError as exc:
            return fail(str(exc))

    db.session.commit()
    return ok(_inst_serialize(inst), message='保存成功')


@admin_bp.route('/institution/<int:iid>/delete', methods=['POST'])
@login_required
def institution_delete(iid):
    inst = Institution.query.get_or_404(iid)
    inst.is_deleted = True
    db.session.commit()
    flash('已删除', 'success')
    return redirect(request.referrer or url_for('admin.institutions'))


@admin_bp.route('/api/institution/<int:iid>/qrcode')
def api_institution_qrcode(iid):
    """生成机构报名链接的二维码（中间带 logo、底部带链接），返回链接与 data URI 图片"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    inst = Institution.query.get_or_404(iid)
    import base64
    url = _signup_link(inst.code)
    caption = (current_app.config.get('SITE_BASE_URL') or '').rstrip('/') or url
    logo_path = os.path.join(current_app.static_folder, 'img', 'share.png')
    buf = generate_qr_png(url, logo_path=logo_path, caption=caption)
    image = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
    return ok({'id': inst.id, 'name': inst.name, 'url': url, 'caption': caption, 'image': image})


# --------------------------------------------------------------------------- #
# 账号管理（仅超管可见）
# --------------------------------------------------------------------------- #
def _account_serialize(a):
    inst = None
    if a.institution_id:
        obj = Institution.query.get(a.institution_id)
        inst = obj.name if obj else ''
    return {
        'id': a.id,
        'username': a.username,
        'password': a.password_plain or '',
        'role': a.role or 'admin',
        'role_text': {'admin': '超级管理员', 'user': '运营账号', 'institution': '机构账号'}.get(
            a.role or 'admin', a.role),
        'institution': inst or '',
        'created_at': a.created_at.strftime('%Y-%m-%d %H:%M:%S') if a.created_at else '',
    }


@admin_bp.route('/accounts', methods=['GET'])
@login_required
def accounts():
    """账号管理页面（超管、运营账号可访问）"""
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role not in ('admin', 'user'):
        flash('无权访问该页面', 'error')
        return redirect(url_for('admin.registrations'))
    return render_template('admin/accounts.html')


@admin_bp.route('/api/accounts')
def api_accounts():
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role not in ('admin', 'user'):
        return fail('无权访问', status=403)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', current_app.config['PER_PAGE'], type=int)
    keyword = (request.args.get('q') or '').strip()
    institution_id = request.args.get('institution_id', type=int)
    no_institution = (request.args.get('no_institution') or '') == '1'
    query = Admin.query
    # 运营账号看不到超级管理员账号
    if role != 'admin':
        query = query.filter(Admin.role != 'admin')
    if keyword:
        query = query.filter(Admin.username.like('%%%s%%' % keyword))
    if no_institution:
        query = query.filter(Admin.institution_id.is_(None))
    elif institution_id:
        query = query.filter(Admin.institution_id == institution_id)
    pagination = query.order_by(Admin.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    data = [_account_serialize(a) for a in pagination.items]
    return ok(data, pagination=pagination_dict(pagination))


@admin_bp.route('/api/account-institutions')
def api_account_institutions():
    """账号筛选用的机构下拉列表。"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role not in ('admin', 'user'):
        return fail('无权访问', status=403)
    rows = db.session.query(Institution.id, Institution.name).filter(
        Institution.is_deleted.is_(False)).order_by(Institution.name).all()
    return ok([{'id': r[0], 'name': r[1]} for r in rows])


def _account_access_denied(account):
    """运营账号不得操作超级管理员账号。"""
    role = getattr(current_user, 'role', 'admin') or 'admin'
    return role != 'admin' and (account.role or '') == 'admin'


@admin_bp.route('/api/account/<int:aid>', methods=['GET'])
def api_account_get(aid):
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role not in ('admin', 'user'):
        return fail('无权访问', status=403)
    account = Admin.query.get_or_404(aid)
    if _account_access_denied(account):
        return fail('无权访问', status=403)
    return ok(_account_serialize(account))


@admin_bp.route('/api/account/<int:aid>', methods=['POST'])
def api_account_update(aid):
    """编辑账号（账号名、密码、角色）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role not in ('admin', 'user'):
        return fail('无权访问', status=403)
    account = Admin.query.get_or_404(aid)
    if _account_access_denied(account):
        return fail('无权访问', status=403)
    payload = request.get_json(silent=True) or request.form

    username = (payload.get('username') or '').strip()
    if username:
        if len(username) > 50:
            return fail('账号过长')
        exists = Admin.query.filter(Admin.username == username, Admin.id != aid).first()
        if exists:
            return fail('该账号已存在')
        account.username = username

    password = (payload.get('password') or '').strip()
    if password:
        if len(password) < 6:
            return fail('密码至少 6 位')
        account.set_password(password)

    new_role = (payload.get('role') or '').strip()
    if new_role in ('admin', 'user', 'institution'):
        # 运营账号不能提升他人为超管
        if role != 'admin' and new_role == 'admin':
            return fail('无权设置超级管理员角色')
        if account.role == 'admin' and new_role != 'admin':
            remaining = Admin.query.filter(Admin.role == 'admin', Admin.id != account.id).count()
            if remaining == 0:
                return fail('至少需要保留一个超级管理员')
        account.role = new_role

    db.session.commit()
    return ok(_account_serialize(account), message='保存成功')


@admin_bp.route('/api/account/<int:aid>/delete', methods=['POST'])
def api_account_delete(aid):
    """删除账号（不可删除自己、不可删除最后一个超管）"""
    if not current_user.is_authenticated:
        return fail('未登录或登录已过期', status=401)
    role = getattr(current_user, 'role', 'admin') or 'admin'
    if role not in ('admin', 'user'):
        return fail('无权访问', status=403)
    account = Admin.query.get_or_404(aid)
    if _account_access_denied(account):
        return fail('无权访问', status=403)
    if account.id == current_user.id:
        return fail('不能删除当前登录账号')
    if account.role == 'admin':
        remaining = Admin.query.filter(Admin.role == 'admin', Admin.id != account.id).count()
        if remaining == 0:
            return fail('至少需要保留一个超级管理员')
    db.session.delete(account)
    db.session.commit()
    return ok({'deleted': aid}, message='已删除')
