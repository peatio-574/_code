"""数据库基础设施。

提供引擎/会话管理、MySQL 命名锁、建库与迁移对账。
沿用既有库表设计：不使用外键/唯一约束，业务唯一性由命名锁 + 事务保证。
"""
from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings
from .error import internal

# 迁移文件目录与命名规则（0001_xxx.sql）
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_FILE_RE = re.compile(r"^(\d+)_(.+)\.sql$")

# 获取命名锁的超时时间（秒）
LOCK_TIMEOUT_SECONDS = 10

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """SQLAlchemy 声明基类；表结构由 SQL 迁移维护，禁止 create_all。"""


def _build_engine() -> Engine:
    """按配置创建数据库引擎（连接池 + 预检）。"""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.database_max_connections,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )


def get_engine() -> Engine:
    """获取全局引擎（懒加载单例）。"""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """获取会话工厂（懒加载单例）。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def session_scope() -> Generator[Session, None, None]:
    """FastAPI 依赖：成功提交，异常回滚，最终关闭。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def named_lock(key: str) -> Iterator[Connection]:
    """在 MySQL 命名锁保护下执行一段逻辑。

    数据库不设唯一约束，因此「检查 + 写入」必须在本锁与事务内串行化，
    与旧 Rust 后端一致。业务异常（ApiError）会先提交再抛出，确保登录限流
    等有意写入的记录得以持久化。
    """
    from .error import ApiError

    # GET_LOCK 名称上限 64 字符，超长key做摘要折叠
    lock_name = key if len(key) <= 64 else "m" + hashlib.sha256(key.encode()).hexdigest()[:63]
    connection = get_engine().connect()
    try:
        acquired = connection.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": lock_name, "timeout": LOCK_TIMEOUT_SECONDS},
        ).scalar()
        connection.commit()
        if acquired != 1:
            raise internal()
        try:
            yield connection
            connection.commit()
        except ApiError:
            connection.commit()
            raise
        except Exception:
            connection.rollback()
            raise
    finally:
        try:
            connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
            connection.commit()
        finally:
            connection.close()


def ensure_database_exists(database_url: str) -> None:
    """目标库不存在时自动创建（开发便利，与旧后端行为一致）。"""
    url = make_url(database_url)
    name = url.database
    if not name:
        raise internal()
    # 连接时不指定库，仅用于执行 CREATE DATABASE
    server_url = url.set(database=None)
    server_engine = create_engine(server_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with server_engine.connect() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            )
    finally:
        server_engine.dispose()


def _split_statements(sql: str) -> list[str]:
    """把迁移 SQL 按顶层分号拆分为可执行语句，忽略注释与空行。"""
    statements: list[str] = []
    current: list[str] = []
    for raw_line in sql.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("--"):
            continue
        if not stripped:
            continue
        current.append(raw_line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _migration_files() -> list[tuple[int, Path]]:
    """列出迁移文件并按版本号升序排列。"""
    files: list[tuple[int, Path]] = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = MIGRATION_FILE_RE.match(path.name)
        if match:
            files.append((int(match.group(1)), path))
    files.sort(key=lambda item: item[0])
    return files


def run_migrations(engine: Engine) -> list[str]:
    """应用尚未记录的迁移并返回名称列表。

    兼容已由旧 Rust(sqlx) 迁移过的库：当存在 _sqlx_migrations 表时，
    将其成功版本导入本方记录表，避免重复执行同一迁移。
    """
    applied: list[str] = []
    # DDL 会隐式提交，统一使用 AUTOCOMMIT 执行
    autocommit = engine.execution_options(isolation_level="AUTOCOMMIT")
    with autocommit.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS py_schema_migrations ("
                "version BIGINT NOT NULL PRIMARY KEY, "
                "name VARCHAR(255) NOT NULL, "
                "applied_at BIGINT NOT NULL)"
            )
        )
        # 若检测到 sqlx 迁移记录表，导入其成功版本
        sqlx_exists = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = '_sqlx_migrations'"
            )
        ).scalar()
        if sqlx_exists:
            for (version,) in connection.execute(
                text("SELECT version FROM _sqlx_migrations WHERE success = 1")
            ).fetchall():
                connection.execute(
                    text(
                        "INSERT IGNORE INTO py_schema_migrations(version, name, applied_at) "
                        "VALUES(:version, 'imported-from-sqlx', :applied_at)"
                    ),
                    {"version": version, "applied_at": int(time.time())},
                )

    for version, path in _migration_files():
        with autocommit.connect() as connection:
            already = connection.execute(
                text("SELECT COUNT(*) FROM py_schema_migrations WHERE version = :version"),
                {"version": version},
            ).scalar()
            if already:
                continue
            for statement in _split_statements(path.read_text(encoding="utf-8")):
                connection.execute(text(statement))
            connection.execute(
                text(
                    "INSERT INTO py_schema_migrations(version, name, applied_at) "
                    "VALUES(:version, :name, :applied_at)"
                ),
                {"version": version, "name": path.name, "applied_at": int(time.time())},
            )
        applied.append(path.name)
    return applied
