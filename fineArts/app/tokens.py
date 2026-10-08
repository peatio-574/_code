# -*- coding: utf-8 -*-
"""证书详情令牌。

两类签名令牌：
- 限时令牌（查询结果跳转用，默认 1 小时有效）
- 永久令牌（打印在二维码上，长期有效，便于证书长期扫码核验）
"""
from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

DETAIL_SALT = 'finearts-cert-detail'
QR_SALT = 'finearts-cert-qr'


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)


def make_token(cert_id):
    """限时详情令牌（查询结果页使用）。"""
    return _serializer(DETAIL_SALT).dumps({'id': cert_id})


def load_token(token, max_age=3600):
    try:
        data = _serializer(DETAIL_SALT).loads(token, max_age=max_age)
        return data.get('id')
    except (BadSignature, SignatureExpired):
        return None


def make_qr_token(cert_id):
    """永久详情令牌（证书二维码使用，不设过期）。"""
    return _serializer(QR_SALT).dumps({'id': cert_id})


def load_qr_token(token):
    try:
        data = _serializer(QR_SALT).loads(token)  # 不传 max_age：永不过期
        return data.get('id')
    except BadSignature:
        return None
