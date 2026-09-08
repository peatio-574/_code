import os
from datetime import timedelta
from urllib.parse import quote

basedir = os.path.abspath(os.path.dirname(__file__))

# ---------------- 数据库连接（单一来源，供应用与 init_db.py 共用） ----------------
# 密码只在此配置一次；用 .env / 环境变量覆盖即可，不要在多处代码里重复写。
DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
DB_PORT = os.environ.get('DB_PORT', '3306')
DB_USER = os.environ.get('DB_USER', 'job_CAIQABiAB')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'BBii@BDIKCAU&QABiiBBi*JBTIH')
DB_NAME = os.environ.get('DB_NAME', 'job')


def _build_database_uri():
    # 密码含特殊字符（@ & / 等）必须 URL 编码，否则 SQLAlchemy 解析报错
    return (f"mysql+pymysql://{DB_USER}:{quote(DB_PASSWORD, safe='')}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4")


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True
    }
    UPLOAD_FOLDER = os.path.join(basedir, '..', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # ---------------- AI 简历识别配置 ----------------
    # 配置了 AI_API_KEY 才真正调用外部大模型；否则内置启发式分析（离线兜底）。
    AI_API_KEY = os.environ.get('AI_API_KEY', '')                  # API Key（建议放 .env，勿提交）
    AI_BASE_URL = os.environ.get('AI_BASE_URL', 'https://api.deepseek.com')
    AI_MODEL = os.environ.get('AI_MODEL', 'deepseek-v4-flash-vision-exp')
    # 说明：AI 模型只接收【提取出的文本】，因此 PDF/Word/Excel 都会先转成文本再交给模型，
    # 模型本身不需要直接“识别 PDF”。对于没有文字层的 PDF（扫描件），需要 OCR 才能转文本。
    AI_OCR_ENABLED = os.environ.get('AI_OCR_ENABLED', 'true').lower() == 'true'


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
