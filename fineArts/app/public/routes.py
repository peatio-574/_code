# -*- coding: utf-8 -*-
"""前台：证书查询"""
from flask import (Response, jsonify, redirect, render_template,
                   request, url_for)

from ..api import fail, ok, single_pagination
from ..captcha import captcha_data_uri, create_captcha, render_png, verify_captcha
from ..models import Certificate
from ..tokens import load_qr_token, load_token, make_token
from . import public_bp


# 微信扫码中转页：微信内打开时引导「在浏览器打开」，系统浏览器直接跳转
# 默认目标为普通商品链接（商品 id），在手机浏览器中免登录直接打开商品详情页
TAOBAO_JUMP_TARGET = 'https://item.taobao.com/item.htm?id=1088451299872'


@public_bp.route('/tz', methods=['GET'])
def jump():
    """扫码中转页：用于微信内引导跳转到淘宝等外部页面。"""
    target = request.args.get('u') or ''
    # 仅允许跳转到淘宝/阿里相关域名，避免被滥用为开放重定向
    low = target.lower()
    allowed = low.startswith('https://') and any(
        d in low for d in ('taobao.com', 'tb.cn', 'tmall.com', 'alicdn.com', 'alibaba.com'))
    if not allowed:
        target = TAOBAO_JUMP_TARGET
    return render_template('public/jump.html', target=target)


@public_bp.route('/', methods=['GET'])
def root():
    """根路径跳转到查询页 index.html"""
    return redirect(url_for('public.index'))


@public_bp.route('/index.html', methods=['GET'])
def index():
    key, _text, _answer = create_captcha()
    return render_template('public/query.html', captcha_key=key)


@public_bp.route('/captcha/<key>.png')
def captcha_image(key):
    from ..captcha import get_captcha_text
    text = get_captcha_text(key)
    if not text:
        text = '----'
    return Response(render_png(text), mimetype='image/png')


@public_bp.route('/captcha/new')
def captcha_new():
    key, _text, _answer = create_captcha()
    return jsonify({'code': 200, 'data': {'key': key, 'img': captcha_data_uri(key)}})


@public_bp.route('/query', methods=['POST'])
def query():
    """证书查询接口（返回 JSON）

    成功： {"code": 200, "message": "success", "data": [ ... ]}
    未找到：{"code": 404, "message": "未查询到相关信息", "data": []}
    参数错误：{"code": 422, "message": "请检查输入", "errors": {...}}
    验证码错误：{"code": 400, "message": "验证码错误，请重新输入"}
    """
    payload = request.get_json(silent=True) or request.form
    student_name = (payload.get('student_name') or '').strip()
    query_type = str(payload.get('type') or '1').strip()
    id_num = (payload.get('id_num') or '').strip()
    certificate_code = (payload.get('certificate_code') or '').strip()
    captcha_key = (payload.get('captcha_key') or '').strip()
    captcha_value = (payload.get('captcha_value') or '').strip()

    errors = {}
    if not student_name:
        errors['student_name'] = '姓名不能为空'
    if query_type == '2':
        if not certificate_code:
            errors['certificate_code'] = '证书编号不能为空'
    else:
        if not id_num:
            errors['id_num'] = '证件号不能为空'
    if errors:
        return fail('请检查输入', errors=errors)

    if not verify_captcha(captcha_key, captcha_value):
        return fail('验证码错误，请重新输入')

    query = Certificate.query.filter(Certificate.is_deleted.is_(False),
                                     Certificate.name == student_name)
    if query_type == '2':
        query = query.filter(Certificate.cert_no == certificate_code)
    else:
        query = query.filter(Certificate.id_card == id_num)
    certs = query.order_by(Certificate.issue_date.desc()).all()

    data = []
    for c in certs:
        token = make_token(c.id)
        data.append({
            'id': c.id,
            'name': c.name,
            'id_card': c.id_card,
            'cert_no': c.cert_no,
            'issue_date': c.issue_date,
            'level': c.level,
            'major': c.major,
            'level_range': c.level_range,
            'token': token,
            'detail_url': url_for('public.detail', token=token),
        })
    return ok(data, pagination=single_pagination(len(data)))


@public_bp.route('/certificate/<token>')
def detail(token):
    # 先尝试限时令牌（查询结果跳转），再尝试永久令牌（证书二维码，不过期）
    cert_id = load_token(token) or load_qr_token(token)
    if not cert_id:
        return render_template('public/detail_invalid.html'), 404
    cert = Certificate.query.filter(Certificate.id == cert_id,
                                    Certificate.is_deleted.is_(False)).first()
    if not cert:
        return render_template('public/detail_invalid.html'), 404
    return render_template('public/detail.html', cert=cert, token=token)
