"""管理员与学员管理：按校区/归属范围维护账号、启停、删除、重置密码、归属调整。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import is_super_admin, mask_phone, now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import conflict, forbidden, not_found, validation
from ..response import ok
from ..security import hash_password

router = APIRouter(prefix="/api/admin")

ADMIN_ROLE_CODES = ("principal", "homeroom_teacher")


class CreateUserInput(BaseModel):
    username: str | None = None
    display_name: str = ""
    real_name: str = ""
    phone: str = ""
    password: str = ""
    role_code: str = "principal"
    manager_id: int | None = None
    campus_id: int | None = None
    email: str = ""
    status: int = 1


class UpdateUserInput(BaseModel):
    id: int
    display_name: str | None = None
    real_name: str | None = None
    phone: str | None = None
    role_code: str | None = None
    campus_id: int | None = None
    status: int | None = None


class StatusInput(BaseModel):
    id: int
    status: int


class ResetPasswordInput(BaseModel):
    id: int
    password: str


class IdsInput(BaseModel):
    ids: list[int]


class ManagerInput(BaseModel):
    manager_id: int | None = None


def _manageable_predicate(actor: int, is_super: bool) -> str:
    if is_super:
        return "1 = 1"
    campus_scope = (
        "EXISTS (SELECT 1 FROM campus_members acm "
        "JOIN campus_members tcm ON tcm.campus_id = acm.campus_id AND tcm.status = 1 "
        "JOIN campuses sc ON sc.id = acm.campus_id "
        "WHERE acm.user_id = :actor AND acm.status = 1 AND sc.status = 1 AND tcm.user_id = u.id)"
    )
    homeroom = (
        "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
        "WHERE ur.user_id=u.id AND r.code='homeroom_teacher' AND r.status=1)"
    )
    student = (
        "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
        "WHERE ur.user_id=u.id AND r.code='student' AND r.status=1)"
    )
    principal_branch = (
        f"({campus_scope} AND (({homeroom} AND u.manager_id = :actor) OR "
        f"({student} AND (u.manager_id = :actor OR u.manager_id IN "
        "(SELECT id FROM users WHERE manager_id = :actor)))))"
    )
    homeroom_branch = f"({campus_scope} AND {student} AND u.manager_id = :actor)"
    return f"({principal_branch} OR {homeroom_branch})"


def _actor_roles(connection, actor: int) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            text(
                "SELECT r.code FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :actor AND r.status = 1"
            ),
            {"actor": actor},
        ).fetchall()
    ]


def _user_view(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "email": row["email"] or "",
        "mobile": mask_phone(row["mobile"]),
        "phone": mask_phone(row["mobile"]),
        "status": row["status"],
        "manager_id": row["manager_id"],
        "manager_name": row["manager_name"] or "",
        "campus_id": row["campus_id"],
        "campus_name": row["campus_name"] or "",
        "role_codes": (row["role_codes"] or "").split(",") if row["role_codes"] else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


_USER_SELECT = (
    "SELECT u.id, u.username, u.display_name, u.email, u.mobile, u.status, u.manager_id, "
    "u.created_at, u.updated_at, "
    "(SELECT COALESCE(NULLIF(mu.display_name,''), mu.username) FROM users mu WHERE mu.id=u.manager_id) manager_name, "
    "(SELECT cm.campus_id FROM campus_members cm WHERE cm.user_id=u.id AND cm.status=1 AND cm.is_primary=1 ORDER BY cm.id LIMIT 1) campus_id, "
    "(SELECT c.name FROM campus_members cm JOIN campuses c ON c.id=cm.campus_id WHERE cm.user_id=u.id AND cm.status=1 ORDER BY cm.id LIMIT 1) campus_name, "
    "(SELECT GROUP_CONCAT(r.code) FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=u.id AND r.status=1) role_codes "
    "FROM users u"
)


def _fetch_user(connection, user_id: int) -> dict:
    row = connection.execute(
        text(f"{_USER_SELECT} WHERE u.id = :id"), {"id": user_id}
    ).mappings().first()
    if row is None:
        raise not_found("用户不存在")
    return _user_view(row)


def _require_manageable(connection, actor: int, target_id: int) -> None:
    is_super = is_super_admin(connection, actor)
    if is_super:
        return
    row = connection.execute(
        text(f"SELECT u.id FROM users u WHERE u.id = :id AND ({_manageable_predicate(actor, False)})"),
        {"id": target_id, "actor": actor},
    ).first()
    if row is None:
        raise forbidden()


@router.get("/users")
def list_admins(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    campus_id = request.query_params.get("campus_id")
    status = (request.query_params.get("status") or "").strip()
    with get_engine().connect() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        roles = _actor_roles(connection, actor)
        where = [
            "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=u.id AND r.code IN ('principal','homeroom_teacher') AND r.status=1)"
        ]
        params: dict = {"actor": actor}
        if not is_super:
            if "principal" in roles:
                where.append(
                    "u.manager_id = :actor OR u.id IN "
                    "(SELECT id FROM users WHERE created_by = :actor)"
                )
            else:
                where.append("1 = 0")
        if keyword:
            where.append("(u.username LIKE :kw OR u.display_name LIKE :kw OR u.mobile LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if campus_id and campus_id.isdigit():
            where.append(
                "EXISTS (SELECT 1 FROM campus_members cm WHERE cm.user_id=u.id "
                "AND cm.campus_id=:campus_id AND cm.status=1)"
            )
            params["campus_id"] = int(campus_id)
        if status in ("0", "1"):
            where.append("u.status = :status")
            params["status"] = int(status)
        clause = " AND ".join(f"({w})" for w in where)
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM users u WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                f"{_USER_SELECT} WHERE {clause} ORDER BY u.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([_user_view(r) for r in rows], total, page, size))


@router.post("/user")
def create_admin(payload: CreateUserInput, request: Request):
    phone = (payload.phone or payload.username or "").strip()
    role_code = payload.role_code or "principal"
    if not phone or not phone.isdigit() or not (5 <= len(phone) <= 15):
        raise validation("手机号格式不正确")
    if role_code not in ADMIN_ROLE_CODES:
        raise validation("角色不合法")
    with named_lock("users:identity") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        if not is_super:
            actor_roles = _actor_roles(connection, actor)
            if "principal" not in actor_roles or role_code != "homeroom_teacher":
                raise forbidden()
        if connection.execute(
            text("SELECT COUNT(*) FROM users WHERE username = :phone OR mobile = :phone"),
            {"phone": phone},
        ).scalar():
            raise conflict("手机号已注册")
        campus_id = payload.campus_id
        if not is_super:
            campus_id = connection.execute(
                text(
                    "SELECT campus_id FROM campus_members WHERE user_id=:actor AND status=1 "
                    "AND is_primary=1 ORDER BY id LIMIT 1"
                ),
                {"actor": actor},
            ).scalar()
        password = payload.password.strip() or phone[-6:]
        display = (payload.real_name or payload.display_name or "").strip()
        timestamp = now()
        user_id = connection.execute(
            text(
                "INSERT INTO users(username, password_hash, display_name, mobile, status, "
                "manager_id, created_by, created_at, updated_at) VALUES(:username, :hash, "
                ":display_name, :mobile, :status, :manager_id, :actor, :created_at, :updated_at)"
            ),
            {
                "username": phone,
                "hash": hash_password(password),
                "display_name": display,
                "mobile": phone,
                "status": 1 if payload.status else 0,
                "manager_id": payload.manager_id if is_super else actor,
                "actor": actor,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        ).lastrowid
        connection.execute(
            text(
                "INSERT INTO user_roles(user_id, role_id, created_at) "
                "SELECT :uid, id, :created_at FROM roles WHERE code=:code AND status=1"
            ),
            {"uid": user_id, "created_at": timestamp, "code": role_code},
        )
        if campus_id:
            connection.execute(
                text(
                    "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, status, "
                    "joined_at, created_by, created_at) VALUES(:campus_id, :uid, :type, 1, 1, "
                    ":joined_at, :actor, :created_at)"
                ),
                {
                    "campus_id": campus_id,
                    "uid": user_id,
                    "type": role_code,
                    "joined_at": timestamp,
                    "actor": actor,
                    "created_at": timestamp,
                },
            )
        result = _fetch_user(connection, user_id)
    return ok(result)


@router.put("/user")
def update_admin(payload: UpdateUserInput, request: Request):
    with named_lock(f"user:update:{payload.id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        _require_manageable(connection, actor, payload.id)
        fields = ["updated_at = :updated_at"]
        params: dict = {"updated_at": now(), "id": payload.id}
        if payload.display_name is not None or payload.real_name is not None:
            fields.append("display_name = :display_name")
            params["display_name"] = (payload.real_name or payload.display_name or "").strip()
        if payload.phone is not None:
            phone = payload.phone.strip()
            if phone and phone != connection.execute(
                text("SELECT mobile FROM users WHERE id=:id"), {"id": payload.id}
            ).scalar():
                dup = connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE username=:p OR mobile=:p"),
                    {"p": phone},
                ).scalar()
                if dup:
                    raise conflict("手机号已被使用")
                fields += ["mobile = :phone", "username = :phone"]
                params["phone"] = phone
        status_changed = False
        if payload.status is not None:
            new_status = 1 if payload.status else 0
            if new_status == 0:
                _protect_last_admin(connection, payload.id)
            current = connection.execute(
                text("SELECT status FROM users WHERE id=:id"), {"id": payload.id}
            ).scalar()
            status_changed = current != new_status
            fields.append("status = :status")
            params["status"] = new_status
        connection.execute(
            text(f"UPDATE users SET {', '.join(fields)} WHERE id = :id"), params
        )
        if payload.role_code is not None:
            if payload.role_code not in ADMIN_ROLE_CODES:
                raise validation("角色不合法")
            connection.execute(
                text("DELETE FROM user_roles WHERE user_id=:id"), {"id": payload.id}
            )
            connection.execute(
                text(
                    "INSERT INTO user_roles(user_id, role_id, created_at) "
                    "SELECT :id, id, :ts FROM roles WHERE code=:code AND status=1"
                ),
                {"id": payload.id, "ts": now(), "code": payload.role_code},
            )
            status_changed = True
        if payload.campus_id is not None:
            connection.execute(
                text("DELETE FROM campus_members WHERE user_id=:id"), {"id": payload.id}
            )
            if payload.campus_id:
                connection.execute(
                    text(
                        "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, "
                        "status, joined_at, created_at) VALUES(:campus_id, :id, :type, 1, 1, :ts, :ts)"
                    ),
                    {
                        "campus_id": payload.campus_id,
                        "id": payload.id,
                        "type": payload.role_code or "principal",
                        "ts": now(),
                    },
                )
            status_changed = True
        if status_changed:
            connection.execute(
                text("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = :id"),
                {"id": payload.id},
            )
        result = _fetch_user(connection, payload.id)
    return ok(result)


def _protect_last_admin(connection, user_id: int) -> None:
    is_admin = connection.execute(
        text(
            "SELECT COUNT(*) FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=:id AND r.code='system_admin' AND r.status=1"
        ),
        {"id": user_id},
    ).scalar()
    if is_admin:
        count = connection.execute(
            text(
                "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur "
                "JOIN roles r ON r.id=ur.role_id JOIN users u ON u.id=ur.user_id "
                "WHERE r.code='system_admin' AND r.status=1 AND u.status=1"
            )
        ).scalar()
        if count <= 1:
            raise conflict("必须保留至少一名超级管理员")


def _purge_user(connection, user_id: int) -> None:
    for statement in (
        "DELETE FROM note_likes WHERE user_id=:id OR comment_id IN (SELECT id FROM course_notes WHERE user_id=:id)",
        "DELETE FROM course_notes WHERE user_id=:id",
        "DELETE FROM learning_progress WHERE user_id=:id",
        "DELETE FROM course_watch_progress WHERE user_id=:id",
        "DELETE FROM course_watch_sessions WHERE user_id=:id",
        "DELETE FROM question_records WHERE user_id=:id",
        "DELETE FROM question_first_answers WHERE user_id=:id",
        "DELETE FROM question_retry_answers WHERE user_id=:id",
        "DELETE FROM question_retry_attempts WHERE user_id=:id",
        "DELETE FROM exam_answers WHERE attempt_id IN (SELECT id FROM exam_attempts WHERE user_id=:id)",
        "DELETE FROM exam_attempts WHERE user_id=:id",
        "DELETE FROM auth_sessions WHERE user_id=:id",
        "DELETE FROM campus_members WHERE user_id=:id",
        "DELETE FROM user_roles WHERE user_id=:id",
    ):
        connection.execute(text(statement), {"id": user_id})


@router.delete("/user/{user_id}")
def delete_admin(user_id: int, request: Request, verify_name: str = "", verify_phone: str = ""):
    with named_lock(f"user:delete:{user_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if actor == user_id:
            raise validation("不能删除自己")
        _require_manageable(connection, actor, user_id)
        _protect_last_admin(connection, user_id)
        target = connection.execute(
            text("SELECT display_name, mobile FROM users WHERE id=:id"), {"id": user_id}
        ).mappings().first()
        if target is None:
            raise not_found("用户不存在")
        managing = connection.execute(
            text("SELECT COUNT(*) FROM users WHERE manager_id=:id"), {"id": user_id}
        ).scalar()
        if managing:
            raise conflict("该用户仍在管理其他学员，请先转移")
        if verify_name and target["display_name"] != verify_name:
            raise validation("姓名验证失败")
        if verify_phone and _unmask(target["mobile"]) != verify_phone:
            raise validation("电话验证失败")
        _purge_user(connection, user_id)
        connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
    return ok({"id": user_id})


def _unmask(phone: str | None) -> str:
    return phone or ""


@router.post("/user/toggle-status")
def toggle_admin_status(payload: StatusInput, request: Request):
    with named_lock(f"user:status:{payload.id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if actor == payload.id and payload.status == 0:
            raise validation("不能禁用自己")
        _require_manageable(connection, actor, payload.id)
        if payload.status == 0:
            _protect_last_admin(connection, payload.id)
        connection.execute(
            text(
                "UPDATE users SET status=:status, session_epoch=session_epoch+1, updated_at=:ts "
                "WHERE id=:id"
            ),
            {"status": 1 if payload.status else 0, "ts": now(), "id": payload.id},
        )
    return ok({"id": payload.id, "status": 1 if payload.status else 0})


@router.post("/user/reset-password")
def reset_password(payload: ResetPasswordInput, request: Request):
    if len(payload.password) < 6:
        raise validation("密码长度不能少于6位")
    with named_lock(f"user:pwd:{payload.id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if actor == payload.id:
            raise validation("请在个人中心修改自己的密码")
        _require_manageable(connection, actor, payload.id)
        connection.execute(
            text(
                "UPDATE users SET password_hash=:hash, session_epoch=session_epoch+1, "
                "updated_at=:ts WHERE id=:id"
            ),
            {"hash": hash_password(payload.password), "ts": now(), "id": payload.id},
        )
    return ok({"id": payload.id})


@router.post("/users/batch-delete")
def batch_delete_admins(payload: IdsInput, request: Request):
    if not payload.ids:
        raise validation("请选择要删除的管理员")
    deleted = 0
    skipped = 0
    with get_engine().begin() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        for user_id in payload.ids:
            if user_id == actor or user_id is None:
                skipped += 1
                continue
            try:
                _require_manageable(connection, actor, user_id)
                _protect_last_admin(connection, user_id)
                _purge_user(connection, user_id)
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                deleted += 1
            except Exception:
                skipped += 1
    return ok({"deleted_count": deleted, "skipped_count": skipped})


# ==================== 学员管理 ====================

STUDENT_SELECT = _USER_SELECT


@router.get("/students")
def list_students(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    campus_id = request.query_params.get("campus_id")
    status = (request.query_params.get("status") or "").strip()
    creator_id = request.query_params.get("creator_id")
    manager_id = request.query_params.get("manager_id")
    with get_engine().connect() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        roles = _actor_roles(connection, actor)
        where = [
            "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=u.id AND r.code='student' AND r.status=1)"
        ]
        params: dict = {"actor": actor}
        if not is_super:
            if "principal" in roles:
                where.append(
                    "u.manager_id = :actor OR u.manager_id IN "
                    "(SELECT id FROM users WHERE manager_id = :actor)"
                )
            elif "homeroom_teacher" in roles:
                where.append("u.manager_id = :actor")
            else:
                where.append("1 = 0")
        if keyword:
            where.append("(u.username LIKE :kw OR u.display_name LIKE :kw OR u.mobile LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if campus_id and campus_id.isdigit():
            where.append(
                "EXISTS (SELECT 1 FROM campus_members cm WHERE cm.user_id=u.id "
                "AND cm.campus_id=:campus_id AND cm.status=1)"
            )
            params["campus_id"] = int(campus_id)
        if creator_id and creator_id.isdigit():
            where.append("u.created_by = :creator_id")
            params["creator_id"] = int(creator_id)
        if manager_id and manager_id.isdigit():
            where.append("u.manager_id = :manager_id")
            params["manager_id"] = int(manager_id)
        if status in ("0", "1"):
            where.append("u.status = :status")
            params["status"] = int(status)
        clause = " AND ".join(f"({w})" for w in where)
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM users u WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                f"{_USER_SELECT} WHERE {clause} ORDER BY u.updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([_user_view(r) for r in rows], total, page, size))


class CreateStudentInput(BaseModel):
    real_name: str = ""
    display_name: str = ""
    phone: str = ""
    password: str = ""
    manager_id: int | None = None
    campus_id: int | None = None
    status: int = 1


@router.post("/student")
def create_student(payload: CreateStudentInput, request: Request):
    phone = payload.phone.strip()
    if not phone or not phone.isdigit() or len(phone) != 11:
        raise validation("手机号格式不正确，应为11位数字")
    with named_lock("users:identity") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if connection.execute(
            text("SELECT COUNT(*) FROM users WHERE username=:p OR mobile=:p"), {"p": phone}
        ).scalar():
            raise conflict(f'手机号"{phone}"已注册')
        campus_id = connection.execute(
            text(
                "SELECT campus_id FROM campus_members WHERE user_id=:actor AND status=1 "
                "AND is_primary=1 ORDER BY id LIMIT 1"
            ),
            {"actor": actor},
        ).scalar()
        password = payload.password.strip() or phone[-6:]
        display = (payload.real_name or payload.display_name or "").strip()
        timestamp = now()
        user_id = connection.execute(
            text(
                "INSERT INTO users(username, password_hash, display_name, mobile, status, "
                "manager_id, created_by, created_at, updated_at) VALUES(:username, :hash, "
                ":display_name, :mobile, :status, :manager_id, :actor, :created_at, :updated_at)"
            ),
            {
                "username": phone,
                "hash": hash_password(password),
                "display_name": display,
                "mobile": phone,
                "status": 1 if payload.status else 0,
                "manager_id": payload.manager_id or actor,
                "actor": actor,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        ).lastrowid
        connection.execute(
            text(
                "INSERT INTO user_roles(user_id, role_id, created_at) "
                "SELECT :uid, id, :ts FROM roles WHERE code='student' AND status=1"
            ),
            {"uid": user_id, "ts": timestamp},
        )
        if campus_id:
            connection.execute(
                text(
                    "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, status, "
                    "joined_at, created_by, created_at) VALUES(:campus_id, :uid, 'student', 1, 1, "
                    ":joined_at, :actor, :created_at)"
                ),
                {
                    "campus_id": campus_id,
                    "uid": user_id,
                    "joined_at": timestamp,
                    "actor": actor,
                    "created_at": timestamp,
                },
            )
        result = _fetch_user(connection, user_id)
    return ok(result)


@router.put("/student")
def update_student(payload: UpdateUserInput, request: Request):
    with named_lock(f"student:update:{payload.id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        _require_manageable(connection, actor, payload.id)
        fields = ["updated_at = :ts"]
        params: dict = {"ts": now(), "id": payload.id}
        if payload.display_name is not None or payload.real_name is not None:
            fields.append("display_name = :display_name")
            params["display_name"] = (payload.real_name or payload.display_name or "").strip()
        if payload.phone is not None:
            phone = payload.phone.strip()
            if phone:
                if not phone.isdigit() or len(phone) != 11:
                    raise validation("手机号格式不正确")
                dup = connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE (username=:p OR mobile=:p) AND id<>:id"),
                    {"p": phone, "id": payload.id},
                ).scalar()
                if dup:
                    raise conflict("手机号已被使用")
                fields += ["mobile = :phone", "username = :phone"]
                params["phone"] = phone
        epoch = False
        if payload.status is not None:
            fields.append("status = :status")
            params["status"] = 1 if payload.status else 0
            epoch = True
        connection.execute(text(f"UPDATE users SET {', '.join(fields)} WHERE id=:id"), params)
        if epoch:
            connection.execute(
                text("UPDATE users SET session_epoch=session_epoch+1 WHERE id=:id"),
                {"id": payload.id},
            )
        result = _fetch_user(connection, payload.id)
    return ok(result)


@router.post("/student/toggle-status")
def toggle_student_status(payload: StatusInput, request: Request):
    with named_lock(f"student:status:{payload.id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        _require_manageable(connection, actor, payload.id)
        connection.execute(
            text(
                "UPDATE users SET status=:status, session_epoch=session_epoch+1, updated_at=:ts "
                "WHERE id=:id"
            ),
            {"status": 1 if payload.status else 0, "ts": now(), "id": payload.id},
        )
    return ok({"id": payload.id, "status": 1 if payload.status else 0})


@router.delete("/student/{student_id}")
def delete_student(student_id: int, request: Request, verify_name: str = "", verify_phone: str = ""):
    with named_lock(f"student:delete:{student_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        _require_manageable(connection, actor, student_id)
        target = connection.execute(
            text("SELECT display_name, mobile FROM users WHERE id=:id"), {"id": student_id}
        ).mappings().first()
        if target is None:
            raise not_found("学员不存在")
        if verify_name and target["display_name"] != verify_name:
            raise validation("姓名验证失败")
        if verify_phone and (target["mobile"] or "") != verify_phone:
            raise validation("电话验证失败")
        _purge_user(connection, student_id)
        connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": student_id})
    return ok({"id": student_id})


@router.post("/students/batch-delete")
def batch_delete_students(payload: IdsInput, request: Request):
    if not payload.ids:
        raise validation("请选择要删除的学员")
    deleted = 0
    skipped = 0
    with get_engine().begin() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        for user_id in payload.ids:
            try:
                _require_manageable(connection, actor, user_id)
                _purge_user(connection, user_id)
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                deleted += 1
            except Exception:
                skipped += 1
    return ok({"deleted_count": deleted, "skipped_count": skipped})


# ==================== 归属管理 ====================


@router.get("/user-hierarchy")
def list_hierarchy(request: Request):
    with get_engine().connect() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        roles = _actor_roles(connection, actor)
        where = [
            "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=u.id AND r.code IN ('homeroom_teacher','student') AND r.status=1)"
        ]
        params: dict = {"actor": actor}
        if not is_super:
            if "principal" in roles:
                where.append(
                    "u.manager_id=:actor OR u.manager_id IN (SELECT id FROM users WHERE manager_id=:actor)"
                )
            elif "homeroom_teacher" in roles:
                where.append("u.manager_id=:actor")
            else:
                where.append("1=0")
        clause = " AND ".join(f"({w})" for w in where)
        rows = connection.execute(
            text(f"{_USER_SELECT} WHERE {clause} ORDER BY u.id DESC"),
            params,
        ).mappings().all()
        items = [_user_view(r) for r in rows]
        manager_where = (
            "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=u.id AND r.code IN ('principal','homeroom_teacher') AND r.status=1) "
            "AND u.status=1"
        )
        manager_params: dict = {}
        if not is_super:
            if "principal" in roles:
                manager_where += " AND (u.id=:actor OR u.manager_id=:actor)"
                manager_params["actor"] = actor
            else:
                manager_where += " AND u.id=:actor"
                manager_params["actor"] = actor
        managers = connection.execute(
            text(
                "SELECT u.id, u.username, u.display_name, "
                "(SELECT r.code FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                " WHERE ur.user_id=u.id AND r.code IN ('principal','homeroom_teacher') LIMIT 1) role_code "
                f"FROM users u WHERE {manager_where} ORDER BY u.id"
            ),
            manager_params,
        ).mappings().all()
        connection.commit()
    return ok({"items": items, "manager_options": [dict(m) for m in managers]})


@router.put("/user-hierarchy/{user_id}")
def update_manager(user_id: int, payload: ManagerInput, request: Request):
    with named_lock(f"hierarchy:{user_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if payload.manager_id == user_id:
            raise validation("不能将用户设为自己的上级")
        _require_manageable(connection, actor, user_id)
        if payload.manager_id is not None:
            _require_manageable(connection, actor, payload.manager_id)
            target_role = connection.execute(
                text(
                    "SELECT r.code FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                    "WHERE ur.user_id=:id AND r.code IN ('homeroom_teacher','student') LIMIT 1"
                ),
                {"id": user_id},
            ).scalar()
            manager_role = connection.execute(
                text(
                    "SELECT r.code FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                    "WHERE ur.user_id=:id AND r.code IN ('principal','homeroom_teacher') LIMIT 1"
                ),
                {"id": payload.manager_id},
            ).scalar()
            if target_role == "homeroom_teacher" and manager_role != "principal":
                raise validation("班主任的上级必须是校长")
            if target_role == "student" and manager_role not in ("principal", "homeroom_teacher"):
                raise validation("学员的上级必须是校长或班主任")
        connection.execute(
            text(
                "UPDATE users SET manager_id=:manager_id, session_epoch=session_epoch+1, "
                "updated_at=:ts WHERE id=:id"
            ),
            {"manager_id": payload.manager_id, "ts": now(), "id": user_id},
        )
    return ok({"user_id": user_id, "manager_id": payload.manager_id})
