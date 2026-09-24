-- Built-in seed data and column defaults that the MySQL initial schema
-- intentionally keeps code-free. The SQLite history carried these in its
-- migrations; they are re-created here for the MySQL baseline.

-- Courses may be inserted without a description (tests, bulk imports).
ALTER TABLE courses
    MODIFY description TEXT NOT NULL DEFAULT ('');

-- Built-in roles: registration assigns the `student` role, so these must
-- exist before the first application seed runs. created_at/updated_at are
-- backfilled by the Rust seed (see src/seed.rs) on every startup.
INSERT INTO roles (code, name, description, data_scope, level, built_in, status, created_at, updated_at)
SELECT seed.code, seed.name, seed.description, seed.data_scope, seed.level, 1, 1, 0, 0
FROM (
    SELECT 'system_admin' AS code, '超级管理员' AS name, '平台全局管理' AS description, 'all' AS data_scope, 1 AS level
    UNION SELECT 'principal', '校长', '管理名下班主任及学员', 'tree', 10
    UNION SELECT 'homeroom_teacher', '班主任', '管理名下学员并发布考试', 'direct', 20
    UNION SELECT 'teacher', '授课教师', '课程授课教师', 'self', 50
    UNION SELECT 'student', '学员', '课程学习、练题与模拟考试', 'self', 100
) AS seed
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.code = seed.code);

-- The course-type dictionary mirrors the SQLite 0013 migration seed.
INSERT INTO dictionary_types (code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT 'course_type', '课程类型', '视频课程的业务分类', 1, 10, 1, 0, 0
WHERE NOT EXISTS (SELECT 1 FROM dictionary_types WHERE code = 'course_type');
