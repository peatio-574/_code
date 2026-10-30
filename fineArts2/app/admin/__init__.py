# -*- coding: utf-8 -*-
"""后台管理"""
from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

from . import routes  # noqa: E402,F401
