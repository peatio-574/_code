"""应用配置。

通过环境变量或 backend/.env 读取，字段语义与旧 Rust 后端 AppConfig 保持一致，
便于直接对接同一套数据库与运行参数。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置。

    所有字段均可用同名大写环境变量覆盖，例如 DATABASE_URL、SESSION_MAX_AGE_SECONDS。
    """

    # 读取 backend/.env；忽略未声明的多余变量
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 服务监听地址
    host: str = "127.0.0.1"
    port: int = 8080

    # MySQL 连接串（必须使用 mysql+pymysql 驱动前缀）与连接池参数
    database_url: str = "mysql+pymysql://root:root123@127.0.0.1:3306/education"
    database_max_connections: int = 10
    database_acquire_timeout_seconds: int = 10

    # 允许跨域的前端来源，多个用英文逗号分隔
    cors_allow_origins: str = "http://localhost:3000"

    # Cookie 是否仅在 HTTPS 下发送；生产环境应设为 true
    cookie_secure: bool = False
    # 会话最长有效期（秒），默认 7 天
    session_max_age_seconds: int = 604_800
    # 登录连续失败上限与锁定时长（秒）
    login_max_failures: int = 5
    login_lockout_seconds: int = 900

    # 本地文件存储目录（头像、封面、视频等）
    storage_dir: str = "data/uploads"

    @property
    def cors_origins(self) -> list[str]:
        """把逗号分隔的来源字符串解析为列表，去除空白项。"""
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """进程内缓存配置对象，避免重复读取 .env。"""
    return Settings()
