"""SQLAlchemy 数据模型（仅用于查询映射）。

表结构由 ../migrations 下的 SQL 迁移维护，禁止使用 create_all 建表。
设计约束与旧后端一致：只有主键与非唯一查询索引，不使用外键、级联、
唯一约束或触发器；业务完整性由应用代码与事务保证。
每个字段的注释见下方各模型。
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Integer, Numeric, String, Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str] = mapped_column(String(512), default="")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    manager_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_scope: Mapped[str] = mapped_column(String(20), default="self")
    level: Mapped[int] = mapped_column(Integer, default=100)
    built_in: Mapped[int] = mapped_column(TINYINT, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    module: Mapped[str] = mapped_column(String(50), default="")
    built_in: Mapped[int] = mapped_column(TINYINT, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    role_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger)
    permission_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    csrf_token: Mapped[str] = mapped_column(String(64))
    login_log_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_seen_at: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[int] = mapped_column(BigInteger, default=0)
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")


class LoginThrottle(Base):
    __tablename__ = "login_throttles"

    throttle_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class LoginLog(Base):
    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempted_identity: Mapped[str] = mapped_column(String(255))
    success: Mapped[int] = mapped_column(TINYINT, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    login_at: Mapped[int] = mapped_column(BigInteger, default=0)
    logout_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class SysConfig(Base):
    __tablename__ = "sys_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(MEDIUMTEXT)
    type: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Campus(Base):
    __tablename__ = "campuses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(255), default="")
    contact_name: Mapped[str] = mapped_column(String(100), default="")
    contact_mobile: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class CampusMember(Base):
    __tablename__ = "campus_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campus_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    member_type: Mapped[str] = mapped_column(String(30))
    is_primary: Mapped[int] = mapped_column(TINYINT, default=1)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    joined_at: Mapped[int] = mapped_column(BigInteger, default=0)
    left_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)


class DictionaryType(Base):
    __tablename__ = "dictionary_types"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    built_in: Mapped[int] = mapped_column(TINYINT, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class DictionaryItem(Base):
    __tablename__ = "dictionary_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type_id: Mapped[int] = mapped_column(BigInteger)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    built_in: Mapped[int] = mapped_column(TINYINT, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    avatar: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    short_description: Mapped[str] = mapped_column(String(500), default="")
    category_id: Mapped[int] = mapped_column(BigInteger, default=0)
    cover: Mapped[str] = mapped_column(String(512), default="")
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    duration: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=2)
    published_at: Mapped[int] = mapped_column(BigInteger, default=0)
    description_image: Mapped[str] = mapped_column(String(512), default="")
    course_type_code: Mapped[str] = mapped_column(String(100), default="")
    campus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class CourseTeacher(Base):
    __tablename__ = "course_teachers"

    course_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class CourseChapter(Base):
    __tablename__ = "course_chapters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    file: Mapped[str] = mapped_column(String(512), default="")
    duration: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    teacher_id: Mapped[int] = mapped_column(BigInteger, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(MEDIUMTEXT)
    status: Mapped[int] = mapped_column(TINYINT, default=0)
    top: Mapped[int] = mapped_column(TINYINT, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    created_user: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_at: Mapped[int] = mapped_column(BigInteger, default=0)
    campus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class QuestionCategory(Base):
    __tablename__ = "question_categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    options: Mapped[str] = mapped_column(String(4000), default="")
    answer: Mapped[str] = mapped_column(String(4000), default="")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    category_id: Mapped[int] = mapped_column(BigInteger, default=0)
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class QuestionRecord(Base):
    __tablename__ = "question_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    question_id: Mapped[int] = mapped_column(BigInteger)
    answer: Mapped[str] = mapped_column(String(4000), default="")
    is_correct: Mapped[int] = mapped_column(TINYINT, default=0)
    answered: Mapped[int] = mapped_column(TINYINT, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class QuestionFirstAnswer(Base):
    __tablename__ = "question_first_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    question_id: Mapped[int] = mapped_column(BigInteger)
    answer: Mapped[str] = mapped_column(String(4000), default="")
    is_correct: Mapped[int] = mapped_column(TINYINT, default=0)
    answered_at: Mapped[int] = mapped_column(BigInteger)


class QuestionRetryAttempt(Base):
    __tablename__ = "question_retry_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[int] = mapped_column(TINYINT, default=0)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[int] = mapped_column(BigInteger)
    completed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class QuestionRetryAnswer(Base):
    __tablename__ = "question_retry_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    question_id: Mapped[int] = mapped_column(BigInteger)
    answer: Mapped[str] = mapped_column(String(4000), default="")
    is_correct: Mapped[int] = mapped_column(TINYINT, default=0)
    answered_at: Mapped[int] = mapped_column(BigInteger)


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(100))
    exam_time: Mapped[int] = mapped_column(BigInteger, default=0)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    is_mock: Mapped[int] = mapped_column(TINYINT, default=0)
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    pass_score: Mapped[int] = mapped_column(Integer, default=60)
    published_at: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class ExamSection(Base):
    __tablename__ = "exam_sections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(500), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ExamSectionQuestion(Base):
    __tablename__ = "exam_section_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_section_id: Mapped[int] = mapped_column(BigInteger)
    question_id: Mapped[int] = mapped_column(BigInteger)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    exam_id: Mapped[int] = mapped_column(BigInteger)
    start_time: Mapped[int] = mapped_column(BigInteger, default=0)
    end_time: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=0)
    submitted_at: Mapped[int] = mapped_column(BigInteger, default=0)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    campus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ExamAnswer(Base):
    __tablename__ = "exam_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(BigInteger)
    question_id: Mapped[int] = mapped_column(BigInteger)
    answer: Mapped[str] = mapped_column(String(4000), default="")
    is_correct: Mapped[int] = mapped_column(TINYINT, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    md5: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[int] = mapped_column(TINYINT, default=1)
    storage_path: Mapped[str] = mapped_column(String(512))
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class FileUpload(Base):
    __tablename__ = "file_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    expected_size: Mapped[int] = mapped_column(BigInteger)
    md5: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(16), default="local")
    status: Mapped[int] = mapped_column(TINYINT, default=0)
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class FileUploadPart(Base):
    __tablename__ = "file_upload_parts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[str] = mapped_column(String(36))
    part_number: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(BigInteger)
    etag: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[int] = mapped_column(BigInteger)


class LearningProgress(Base):
    __tablename__ = "learning_progress"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(BigInteger)
    chapter_id: Mapped[int] = mapped_column(BigInteger, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger)
    progress: Mapped[float] = mapped_column(Numeric(7, 4), default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    campus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class CourseNote(Base):
    __tablename__ = "course_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    comment: Mapped[str] = mapped_column(Text)
    created_time: Mapped[int] = mapped_column(BigInteger, default=0)
    attachments: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)


class NoteLike(Base):
    __tablename__ = "note_likes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    comment_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)


class CourseWatchProgress(Base):
    __tablename__ = "course_watch_progress"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    course_id: Mapped[int] = mapped_column(BigInteger)
    chapter_id: Mapped[int] = mapped_column(BigInteger)
    first_watched_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_watched_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_position_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    video_duration_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    watched_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    completed: Mapped[int] = mapped_column(TINYINT, default=0)
    last_report_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    campus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class CourseWatchSession(Base):
    __tablename__ = "course_watch_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    course_id: Mapped[int] = mapped_column(BigInteger)
    chapter_id: Mapped[int] = mapped_column(BigInteger)
    client_session_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_reported_at: Mapped[int] = mapped_column(BigInteger, default=0)
    ended_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    start_position_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    last_position_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    watched_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[int] = mapped_column(TINYINT, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    campus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
