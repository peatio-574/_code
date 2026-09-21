# -*- coding: utf-8 -*-
"""前台：证书查询"""
from flask import Blueprint

public_bp = Blueprint('public', __name__)

from . import routes  # noqa: E402,F401
