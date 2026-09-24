"""系统配置与内容：配置读取/写入、首页 Banner、关于页与站点内容。"""

from __future__ import annotations


import json

from fastapi import APIRouter, Request
from sqlalchemy import text

from ..common import now
from ..db import get_engine, named_lock
from ..error import forbidden, validation
from ..response import ok

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/api")

FIELDS: list[tuple[str, str]] = [
    ("systemName", "system_name"),
    ("logo", "logo"),
    ("footerHtml", "footer_html"),
    ("homepageHtml", "homepage_html"),
    ("homePageContent", "home_page_content"),
    ("homepageBanner", "homepage_banner"),
    ("homeBanners", "home_banners"),
    ("aboutHtml", "about_html"),
    ("privacyHtml", "privacy_html"),
    ("userAgreementHtml", "user_agreement_html"),
    ("friendLinks", "friend_links"),
    ("homeBackgrounds", "home_backgrounds"),
    ("mockExamTotal", "mock_exam_total"),
    ("mockExamRatios", "mock_exam_ratios"),
    ("mockExamDuration", "mock_exam_duration"),
    ("autoExamEnabled", "auto_exam_enabled"),
    ("autoExamTitle", "auto_exam_title"),
    ("autoExamTotal", "auto_exam_total"),
    ("autoExamDuration", "auto_exam_duration"),
    ("autoExamCategories", "auto_exam_categories"),
    ("autoExamRatios", "auto_exam_ratios"),
    ("autoExamIncludeGroup", "auto_exam_include_group"),
    ("autoExamTargetScore", "auto_exam_target_score"),
    ("autoExamExcludeDays", "auto_exam_exclude_days"),
]


@public_router.get("/system/config")
def get_config():
    with get_engine().connect() as connection:
        rows = connection.execute(
            text("SELECT `key`, value FROM sys_config")
        ).fetchall()
        connection.commit()
    stored = {row[0]: row[1] for row in rows}
    data: dict = {}
    for field, key in FIELDS:
        if key in stored:
            data[field] = stored[key]
    return ok(data)


@public_router.get("/about")
def about():
    with get_engine().connect() as connection:
        row = connection.execute(
            text(
                "SELECT value FROM sys_config WHERE `key` IN ('about_html','about') "
                "ORDER BY CASE `key` WHEN 'about_html' THEN 0 ELSE 1 END LIMIT 1"
            )
        ).scalar()
        connection.commit()
    return ok(row or "")


@public_router.get("/notice")
def notice():
    with get_engine().connect() as connection:
        value = connection.execute(
            text("SELECT value FROM sys_config WHERE `key`='notice'")
        ).scalar()
        connection.commit()
    return ok(value or "")


@public_router.get("/home_page_content")
def home_page_content():
    with get_engine().connect() as connection:
        value = connection.execute(
            text("SELECT value FROM sys_config WHERE `key`='home_page_content'")
        ).scalar()
        connection.commit()
    return ok(value or "")


@public_router.get("/homeBanners")
def home_banners():
    with get_engine().connect() as connection:
        value = connection.execute(
            text("SELECT value FROM sys_config WHERE `key`='home_banners'")
        ).scalar()
        connection.commit()
    return ok(value or "")


def _require_super(request: Request) -> int:
    from ..common import actor_id, is_super_admin

    actor = actor_id(request)
    with get_engine().connect() as connection:
        is_super = is_super_admin(connection, actor)
        connection.commit()
    if not is_super:
        raise forbidden()
    return actor


@router.put("/admin/system/config")
def save_config(payload: dict, request: Request):
    actor = _require_super(request)
    recognized = {field: key for field, key in FIELDS}
    updates: dict[str, str] = {}
    for field, value in payload.items():
        key = recognized.get(field)
        if key is None:
            continue
        updates[key] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if updates:
        with named_lock("sys_config:upsert") as connection:
            timestamp = now()
            for key, value in updates.items():
                exists = connection.execute(
                    text("SELECT id FROM sys_config WHERE `key`=:key"), {"key": key}
                ).scalar()
                if exists:
                    connection.execute(
                        text(
                            "UPDATE sys_config SET value=:value, updated_by=:actor, updated_at=:ts "
                            "WHERE `key`=:key"
                        ),
                        {"value": value, "actor": actor, "ts": timestamp, "key": key},
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO sys_config(`key`, value, type, created_by, updated_by, "
                            "created_at, updated_at) VALUES(:key, :value, 1, :actor, :actor, "
                            ":ts, :ts)"
                        ),
                        {"key": key, "value": value, "actor": actor, "ts": timestamp},
                    )
    return ok(payload)


@router.put("/admin/home-banners")
def save_home_banners(payload: list, request: Request):
    actor = _require_super(request)
    value = json.dumps(payload, ensure_ascii=False)
    with named_lock("sys_config:upsert") as connection:
        timestamp = now()
        exists = connection.execute(
            text("SELECT id FROM sys_config WHERE `key`='home_banners'")
        ).scalar()
        if exists:
            connection.execute(
                text(
                    "UPDATE sys_config SET value=:value, type=5, updated_by=:actor, "
                    "updated_at=:ts WHERE `key`='home_banners'"
                ),
                {"value": value, "actor": actor, "ts": timestamp},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO sys_config(`key`, value, type, created_by, updated_by, "
                    "created_at, updated_at) VALUES('home_banners', :value, 5, :actor, :actor, "
                    ":ts, :ts)"
                ),
                {"value": value, "actor": actor, "ts": timestamp},
            )
    return ok(payload)
