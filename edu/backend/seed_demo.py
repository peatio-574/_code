"""开发演示数据：生成 10 个校区，每个校区 20 名管理员，每名管理员名下 100 名学员。

严格对齐业务建号逻辑（app/api/users.py、app/api/campuses.py）：
- users.username = mobile（唯一），学员/管理员默认密码为 Test123!（本脚本统一复用同一哈希）
- 管理员：user_roles = principal / homeroom_teacher；campus_members.member_type 同角色；manager_id = 超管
- 学员：user_roles = student；manager_id = 所属管理员；created_by = 所属管理员；campus_members.member_type = student
- 所有审计时间由应用生成（Unix 秒）

用法（在 backend 目录下执行）：
    .venv\\Scripts\\python seed_demo.py            # 已存在演示数据时跳过
    .venv\\Scripts\\python seed_demo.py --force    # 先清理旧演示数据再生成
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import bindparam, text

from app.common import now
from app.db import get_engine, named_lock
from app.security import hash_password

CAMPUS_COUNT = 10
ADMINS_PER_CAMPUS = 20
STUDENTS_PER_ADMIN = 100
PHONE_BASE = 13800000000
DEMO_PASSWORD = "Test123!"
CAMPUS_CODE_PREFIX = "DEMO"


def phone_for(offset: int) -> str:
    return str(PHONE_BASE + offset)


def in_use_usernames(connection) -> set[str]:
    rows = connection.execute(
        text("SELECT username FROM users WHERE username REGEXP '^[0-9]{11}$'")
    ).fetchall()
    return {row[0] for row in rows}


def clear_demo(connection) -> None:
    """删除本脚本生成的演示账号与校区（按号码段识别，避免误删真实数据）。"""
    admin_offsets = range(0, CAMPUS_COUNT * ADMINS_PER_CAMPUS)
    student_offsets = range(CAMPUS_COUNT * ADMINS_PER_CAMPUS, CAMPUS_COUNT * ADMINS_PER_CAMPUS + CAMPUS_COUNT * ADMINS_PER_CAMPUS * STUDENTS_PER_ADMIN)
    phones = [phone_for(i) for i in list(admin_offsets) + list(student_offsets)]
    ids: list[int] = []
    chunk = 500
    for start in range(0, len(phones), chunk):
        part = phones[start:start + chunk]
        rows = connection.execute(
            text("SELECT id FROM users WHERE username IN :phones").bindparams(
                bindparam("phones", expanding=True)
            ),
            {"phones": part},
        ).fetchall()
        ids.extend(row[0] for row in rows)
    for start in range(0, len(ids), chunk):
        part = ids[start:start + chunk]
        connection.execute(
            text("DELETE FROM user_roles WHERE user_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": part},
        )
        connection.execute(
            text("DELETE FROM campus_members WHERE user_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": part},
        )
        connection.execute(
            text("DELETE FROM users WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": part},
        )
    connection.execute(
        text(f"DELETE FROM campuses WHERE code LIKE '{CAMPUS_CODE_PREFIX}%'")
    )


def run(force: bool) -> None:
    engine = get_engine()
    timestamp = now()
    password_hash = hash_password(DEMO_PASSWORD)

    with named_lock("seed:demo") as connection:
        if force:
            clear_demo(connection)

        existing = connection.execute(
            text("SELECT COUNT(*) FROM campuses WHERE code LIKE :prefix"),
            {"prefix": f"{CAMPUS_CODE_PREFIX}%"},
        ).scalar()
        if existing:
            print("检测到已存在演示校区，跳过。如需重建请加 --force。")
            return

        actor = connection.execute(
            text(
                "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id "
                "JOIN roles r ON r.id=ur.role_id WHERE r.code='system_admin' "
                "ORDER BY u.id LIMIT 1"
            )
        ).scalar()
        role_ids = {
            row[0]: row[1]
            for row in connection.execute(
                text("SELECT code, id FROM roles WHERE code IN ('principal','homeroom_teacher','student')")
            ).fetchall()
        }
        principal_role = role_ids["principal"]
        homeroom_role = role_ids["homeroom_teacher"]
        student_role = role_ids["student"]

        used = in_use_usernames(connection)
        admin_offset = 0
        student_offset = CAMPUS_COUNT * ADMINS_PER_CAMPUS
        summary: list[tuple[str, str]] = []

        for campus_index in range(1, CAMPUS_COUNT + 1):
            campus_name = f"示范校区{campus_index:02d}"
            campus_code = f"{CAMPUS_CODE_PREFIX}{campus_index:02d}"
            first_admin_phone = phone_for(admin_offset)
            campus_id = connection.execute(
                text(
                    "INSERT INTO campuses(code, name, address, contact_name, contact_mobile, "
                    "status, created_by, created_at, updated_at) VALUES(:code, :name, :address, "
                    ":contact_name, :contact_mobile, 1, :actor, :ts, :ts)"
                ),
                {
                    "code": campus_code,
                    "name": campus_name,
                    "address": f"{campus_name}示范路 {campus_index} 号",
                    "contact_name": f"负责人{campus_index:02d}",
                    "contact_mobile": first_admin_phone,
                    "actor": actor,
                    "ts": timestamp,
                },
            ).lastrowid

            for admin_index in range(1, ADMINS_PER_CAMPUS + 1):
                phone = phone_for(admin_offset)
                admin_offset += 1
                if phone in used:
                    continue
                used.add(phone)
                is_principal = admin_index == 1
                role_code = "principal" if is_principal else "homeroom_teacher"
                role_id = principal_role if is_principal else homeroom_role
                display_name = f"管理员{campus_index:02d}-{admin_index:02d}"
                admin_id = connection.execute(
                    text(
                        "INSERT INTO users(username, password_hash, display_name, mobile, status, "
                        "manager_id, created_by, created_at, updated_at) VALUES(:username, :hash, "
                        ":display_name, :mobile, 1, :manager_id, :actor, :ts, :ts)"
                    ),
                    {
                        "username": phone,
                        "hash": password_hash,
                        "display_name": display_name,
                        "mobile": phone,
                        "manager_id": actor,
                        "actor": actor,
                        "ts": timestamp,
                    },
                ).lastrowid
                connection.execute(
                    text(
                        "INSERT INTO user_roles(user_id, role_id, created_at) VALUES(:uid, :rid, :ts)"
                    ),
                    {"uid": admin_id, "rid": role_id, "ts": timestamp},
                )
                connection.execute(
                    text(
                        "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, "
                        "status, joined_at, created_by, created_at) VALUES(:cid, :uid, :type, 1, 1, "
                        ":ts, :actor, :ts)"
                    ),
                    {
                        "cid": campus_id,
                        "uid": admin_id,
                        "type": role_code,
                        "ts": timestamp,
                        "actor": actor,
                    },
                )

                student_rows = []
                for student_index in range(1, STUDENTS_PER_ADMIN + 1):
                    sphone = phone_for(student_offset)
                    student_offset += 1
                    if sphone in used:
                        continue
                    used.add(sphone)
                    student_rows.append(
                        {
                            "username": sphone,
                            "hash": password_hash,
                            "display_name": f"学员{campus_index:02d}-{admin_index:02d}-{student_index:03d}",
                            "mobile": sphone,
                            "manager_id": admin_id,
                            "actor": admin_id,
                            "ts": timestamp,
                        }
                    )
                if not student_rows:
                    continue
                connection.execute(
                    text(
                        "INSERT INTO users(username, password_hash, display_name, mobile, status, "
                        "manager_id, created_by, created_at, updated_at) VALUES(:username, :hash, "
                        ":display_name, :mobile, 1, :manager_id, :actor, :ts, :ts)"
                    ),
                    student_rows,
                )
                phones = [row["username"] for row in student_rows]
                students = connection.execute(
                    text("SELECT id, username FROM users WHERE username IN :phones").bindparams(
                        bindparam("phones", expanding=True)
                    ),
                    {"phones": phones},
                ).fetchall()
                connection.execute(
                    text(
                        "INSERT INTO user_roles(user_id, role_id, created_at) VALUES(:uid, :rid, :ts)"
                    ),
                    [{"uid": sid, "rid": student_role, "ts": timestamp} for sid, _ in students],
                )
                connection.execute(
                    text(
                        "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, "
                        "status, joined_at, created_by, created_at) VALUES(:cid, :uid, 'student', 1, 1, "
                        ":ts, :actor, :ts)"
                    ),
                    [
                        {"cid": campus_id, "uid": sid, "ts": timestamp, "actor": admin_id}
                        for sid, _ in students
                    ],
                )

            summary.append((campus_name, campus_code))

        connection.commit()

    print("演示数据生成完成：")
    print(f"  校区 {CAMPUS_COUNT} 个（{summary[0][0]} ~ {summary[-1][0]}）")
    print(f"  管理员 {CAMPUS_COUNT * ADMINS_PER_CAMPUS} 名")
    print(f"  学员 {CAMPUS_COUNT * ADMINS_PER_CAMPUS * STUDENTS_PER_ADMIN} 名")
    print(f"  统一登录密码：{DEMO_PASSWORD}")
    print(f"  首个管理员账号：{phone_for(0)}")
    print(f"  首个学员账号：{phone_for(CAMPUS_COUNT * ADMINS_PER_CAMPUS)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成演示校区/管理员/学员数据")
    parser.add_argument("--force", action="store_true", help="先清理旧演示数据再生成")
    args = parser.parse_args()
    try:
        run(args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"生成失败：{exc}", file=sys.stderr)
        raise
