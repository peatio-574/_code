-- Retire the `teacher` role: course instructors are course metadata only and
-- never sign in, so they no longer have accounts or RBAC roles. The `teachers`
-- table and teacher management endpoints remain for course association.
DELETE FROM role_permissions
WHERE role_id IN (SELECT id FROM roles WHERE code = 'teacher');

DELETE FROM user_roles
WHERE role_id IN (SELECT id FROM roles WHERE code = 'teacher');

DELETE FROM campus_members
WHERE member_type = 'teacher';

DELETE FROM roles WHERE code = 'teacher';
