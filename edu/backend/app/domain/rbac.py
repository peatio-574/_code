from __future__ import annotations

from dataclasses import dataclass

# Built-in role codes (the retired `teacher` role is intentionally absent).
ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_PRINCIPAL = "principal"
ROLE_HOMEROOM_TEACHER = "homeroom_teacher"
ROLE_STUDENT = "student"

# Data scope levels, ordered from narrowest to broadest.
DATA_SCOPE_SELF = "self"
DATA_SCOPE_DIRECT = "direct"
DATA_SCOPE_TREE = "tree"
DATA_SCOPE_ALL = "all"

DATA_SCOPE_ORDER = [
    DATA_SCOPE_SELF,
    DATA_SCOPE_DIRECT,
    DATA_SCOPE_TREE,
    DATA_SCOPE_ALL,
]

# Permission codes: format <area>.<resource>.<action>.
PERM_TEACHERS_MANAGE = "console.teachers.manage"
PERM_ADMINISTRATORS_MANAGE = "console.administrators.manage"
PERM_STUDENTS_MANAGE = "console.students.manage"
PERM_COURSES_MANAGE = "console.courses.manage"
PERM_ANNOUNCEMENTS_MANAGE = "console.announcements.manage"
PERM_QUESTIONS_MANAGE = "console.questions.manage"
PERM_EXAMS_VIEW = "console.exams.view"
PERM_EXAMS_COMPOSE = "console.exams.compose"
PERM_EXAMS_EDIT = "console.exams.edit"
PERM_EXAMS_MANAGE = "console.exams.manage"
PERM_EXAMS_PUBLISH = "console.exams.publish"
PERM_EXAMS_WITHDRAW = "console.exams.withdraw"
PERM_SYSTEM_MANAGE = "console.system.manage"
PERM_DICTIONARIES_MANAGE = "console.dictionaries.manage"
PERM_LEARNING_USE = "learning.use"
PERM_CAMPUSES_VIEW = "console.campuses.view"
PERM_CAMPUSES_MANAGE = "console.campuses.manage"
PERM_CAMPUS_MEMBERS_MANAGE = "console.campus_members.manage"
PERM_CAMPUS_REPORTS_VIEW = "console.campus_reports.view"
PERM_DASHBOARD_VIEW = "console.dashboard.view"
PERM_ROLES_MANAGE = "console.roles.manage"


@dataclass(frozen=True)
class BuiltInRole:
    code: str
    name: str
    description: str
    data_scope: str
    level: int


BUILTIN_ROLES: list[BuiltInRole] = [
    BuiltInRole(ROLE_SYSTEM_ADMIN, "超级管理员", "平台全局管理", DATA_SCOPE_ALL, 1),
    BuiltInRole(ROLE_PRINCIPAL, "校长", "管理名下班主任及学员", DATA_SCOPE_TREE, 10),
    BuiltInRole(ROLE_HOMEROOM_TEACHER, "班主任", "管理名下学员并发布考试", DATA_SCOPE_DIRECT, 20),
    BuiltInRole(ROLE_STUDENT, "学员", "课程学习、练题与模拟考试", DATA_SCOPE_SELF, 100),
]


@dataclass(frozen=True)
class BuiltInPermission:
    code: str
    name: str
    module: str


BUILTIN_PERMISSIONS: list[BuiltInPermission] = [
    BuiltInPermission(PERM_TEACHERS_MANAGE, "教师管理", "teachers"),
    BuiltInPermission(PERM_ADMINISTRATORS_MANAGE, "管理员管理", "administrators"),
    BuiltInPermission(PERM_STUDENTS_MANAGE, "学员管理", "students"),
    BuiltInPermission(PERM_COURSES_MANAGE, "课程管理", "courses"),
    BuiltInPermission(PERM_ANNOUNCEMENTS_MANAGE, "公告管理", "announcements"),
    BuiltInPermission(PERM_QUESTIONS_MANAGE, "题库管理", "questions"),
    BuiltInPermission(PERM_EXAMS_VIEW, "考试查看", "exams"),
    BuiltInPermission(PERM_EXAMS_COMPOSE, "考试组卷", "exams"),
    BuiltInPermission(PERM_EXAMS_EDIT, "考试改题", "exams"),
    BuiltInPermission(PERM_EXAMS_MANAGE, "考试管理", "exams"),
    BuiltInPermission(PERM_EXAMS_PUBLISH, "考试发布", "exams"),
    BuiltInPermission(PERM_EXAMS_WITHDRAW, "考试撤回", "exams"),
    BuiltInPermission(PERM_SYSTEM_MANAGE, "系统配置", "system"),
    BuiltInPermission(PERM_DICTIONARIES_MANAGE, "字典管理", "dictionaries"),
    BuiltInPermission(PERM_LEARNING_USE, "学习功能", "learning"),
    BuiltInPermission(PERM_CAMPUSES_VIEW, "校区查看", "campuses"),
    BuiltInPermission(PERM_CAMPUSES_MANAGE, "校区管理", "campuses"),
    BuiltInPermission(PERM_CAMPUS_MEMBERS_MANAGE, "校区成员管理", "campuses"),
    BuiltInPermission(PERM_CAMPUS_REPORTS_VIEW, "校区报表查看", "campuses"),
    BuiltInPermission(PERM_DASHBOARD_VIEW, "控制台总览", "dashboard"),
    BuiltInPermission(PERM_ROLES_MANAGE, "角色管理", "roles"),
]


def get_builtin_role_permissions() -> list[tuple[str, list[str]]]:
    """Role-permission matrix for built-in initialization."""
    return [
        (
            ROLE_SYSTEM_ADMIN,
            [
                PERM_TEACHERS_MANAGE,
                PERM_ADMINISTRATORS_MANAGE,
                PERM_STUDENTS_MANAGE,
                PERM_COURSES_MANAGE,
                PERM_ANNOUNCEMENTS_MANAGE,
                PERM_QUESTIONS_MANAGE,
                PERM_EXAMS_VIEW,
                PERM_EXAMS_COMPOSE,
                PERM_EXAMS_EDIT,
                PERM_EXAMS_MANAGE,
                PERM_EXAMS_PUBLISH,
                PERM_EXAMS_WITHDRAW,
                PERM_SYSTEM_MANAGE,
                PERM_DICTIONARIES_MANAGE,
                PERM_LEARNING_USE,
                PERM_CAMPUSES_VIEW,
                PERM_CAMPUSES_MANAGE,
                PERM_CAMPUS_MEMBERS_MANAGE,
                PERM_CAMPUS_REPORTS_VIEW,
                PERM_DASHBOARD_VIEW,
                PERM_ROLES_MANAGE,
            ],
        ),
        (
            ROLE_PRINCIPAL,
            [
                PERM_ADMINISTRATORS_MANAGE,
                PERM_STUDENTS_MANAGE,
                PERM_EXAMS_VIEW,
                PERM_LEARNING_USE,
                PERM_CAMPUSES_VIEW,
                PERM_CAMPUS_MEMBERS_MANAGE,
                PERM_DASHBOARD_VIEW,
            ],
        ),
        (
            ROLE_HOMEROOM_TEACHER,
            [
                PERM_STUDENTS_MANAGE,
                PERM_EXAMS_VIEW,
                PERM_EXAMS_PUBLISH,
                PERM_EXAMS_COMPOSE,
                PERM_EXAMS_EDIT,
                PERM_EXAMS_WITHDRAW,
                PERM_LEARNING_USE,
                PERM_DASHBOARD_VIEW,
            ],
        ),
        (ROLE_STUDENT, [PERM_LEARNING_USE]),
    ]


def data_scope_rank(scope: str) -> int:
    try:
        return DATA_SCOPE_ORDER.index(scope) + 1
    except ValueError:
        return 0


def is_valid_data_scope(scope: str) -> bool:
    return scope in DATA_SCOPE_ORDER
