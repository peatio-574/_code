# -*- coding: utf-8 -*-
"""统一的 JSON 接口响应格式

成功： {"success": true, "pagination": {...}, "data": [...]}
失败： {"success": false, "message": "...", "errors": {...}}
"""
from flask import jsonify


def pagination_dict(pagination):
    return {
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
        'total': pagination.total,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
        'next_num': pagination.next_num,
        'prev_num': pagination.prev_num,
    }


def single_pagination(total):
    """非分页查询统一包装成分页结构"""
    return {
        'page': 1,
        'per_page': total,
        'pages': 1 if total else 0,
        'total': total,
        'has_next': False,
        'has_prev': False,
        'next_num': None,
        'prev_num': None,
    }


def ok(data=None, pagination=None, message=None):
    payload = {'success': True}
    if pagination is not None:
        payload['pagination'] = pagination
    payload['data'] = data if data is not None else []
    if message:
        payload['message'] = message
    return jsonify(payload)


def fail(message, errors=None, status=200):
    payload = {'success': False, 'message': message}
    if errors:
        payload['errors'] = errors
    return jsonify(payload), status
