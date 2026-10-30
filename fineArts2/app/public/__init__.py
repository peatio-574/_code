# -*- coding: utf-8 -*-
"""前台：考试报名"""
from flask import Blueprint

public_bp = Blueprint('public', __name__)

from . import routes  # noqa: E402,F401
