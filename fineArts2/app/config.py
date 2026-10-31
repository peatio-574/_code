# -*- coding: utf-8 -*-
"""应用配置（fineArts2：仅报名与后台管理）

数据库连接从项目根目录的 .env 读取；未配置时使用本地默认值。
"""
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # fineArts2/app
PROJECT_ROOT = os.path.dirname(BASE_DIR)                    # fineArts2
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# 上传目录：报名电子照片等
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
SIGNUP_UPLOAD_DIR = os.path.join(UPLOAD_FOLDER, 'signup')

# 自动加载项目根目录的 .env（不存在则使用下方默认值）
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

# ---- 数据库连接 ----
DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
DB_PORT = os.environ.get('DB_PORT', '3306')
DB_USER = os.environ.get('DB_USER', 'finearts')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'Finearts@2026')
DB_NAME = os.environ.get('DB_NAME', 'finearts2')


def _build_database_uri():
    # 用户名/密码含特殊字符必须 URL 编码
    return 'mysql+pymysql://%s:%s@%s:%s/%s?charset=utf8mb4' % (
        quote_plus(DB_USER), quote_plus(DB_PASSWORD), DB_HOST, DB_PORT, DB_NAME)


class Config(object):
    SECRET_KEY = os.environ.get(
        'SECRET_KEY', 'caa-finearts2-signup-manager-secret-key-2026')

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }

    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB

    # 报名电子照片
    SIGNUP_UPLOAD_DIR = SIGNUP_UPLOAD_DIR
    ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'bmp', 'webp'}
    MAX_PHOTO_SIZE = 8 * 1024 * 1024  # 8MB

    # 默认管理员（首次初始化数据库时创建）
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Caa@Admin2026')

    # 路由前缀：前台 /new/apply，后台 /new/manage，静态资源 /new/static
    ROUTE_PREFIX = (os.environ.get('ROUTE_PREFIX') or '/new').rstrip('/')
    ADMIN_ROUTE_PREFIX = ROUTE_PREFIX + '/manage'
    STATIC_URL_PATH = ROUTE_PREFIX + '/static'

    # 站点信息
    SITE_TITLE = '中国美术学院-社会美术水平考级管理系统'
    SITE_SUBTITLE = '社会艺术水平考级中心'
    OFFICIAL_SITE = 'https://kjzx.caa.edu.cn/'
    HOME_URL = 'https://mskj.caa.edu.cn/'
    # 机构报名二维码底部展示的链接文案（留空则使用实际报名链接）
    SITE_BASE_URL = ''

    PER_PAGE = 20


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}


def ensure_mysql_database():
    """确保目标数据库存在（不存在则自动创建）"""
    import pymysql

    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER,
        password=DB_PASSWORD, charset='utf8mb4', connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `%s` DEFAULT CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_general_ci" % DB_NAME
            )
        conn.commit()
    finally:
        conn.close()
