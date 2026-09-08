import os
from datetime import timedelta
from urllib.parse import quote
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))

# 自动加载项目根目录的 .env（含真实值，不入库）；不存在则用下方默认/空配置。
load_dotenv(os.path.join(basedir, '..', '.env'))

# ============================================================
# 统一配置区 —— 数据库连接 + AI 模型（全部从 .env 读取）
# 本文件不再内置任何真实值，默认空；实际值统一写在 .env（由 .env.example 复制）。
# ============================================================
# ---- 数据库连接 ----
DB_HOST = os.environ.get('DB_HOST', '')
DB_PORT = os.environ.get('DB_PORT', '')
DB_USER = os.environ.get('DB_USER', '')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', '')

# ---- AI 模型（OpenAI 兼容协议）----
# AI_API_KEY 配了才调用外部大模型；否则回落到内置启发式分析（离线兜底）。
AI_API_KEY = os.environ.get('AI_API_KEY', '')
AI_BASE_URL = os.environ.get('AI_BASE_URL', '')
AI_MODEL = os.environ.get('AI_MODEL', '')
AI_OCR_ENABLED = os.environ.get('AI_OCR_ENABLED', 'true').lower() == 'true'
# ============================================================


def _build_database_uri():
    # 密码/用户名含特殊字符（@ & / 等）必须 URL 编码，否则 SQLAlchemy 解析报错。
    # host/port/库名 仅作结构兜底（MySQL 惯例值，非机密），用户/密码仍取 .env 配置。
    host = DB_HOST or '127.0.0.1'
    port = DB_PORT or '3306'
    name = DB_NAME or 'job'
    return (f"mysql+pymysql://{quote(DB_USER, safe='')}:{quote(DB_PASSWORD, safe='')}"
            f"@{host}:{port}/{name}?charset=utf8mb4")


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True
    }
    UPLOAD_FOLDER = os.path.join(basedir, '..', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # 引用上方统一配置区的值，供 current_app.config.get('AI_*') 读取
    AI_API_KEY = AI_API_KEY
    AI_BASE_URL = AI_BASE_URL
    AI_MODEL = AI_MODEL
    AI_OCR_ENABLED = AI_OCR_ENABLED


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
