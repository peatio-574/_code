-- 课程方向枚举值与「题目方向」保持一致。
-- 以字典「题目方向」(code=question_direction) 的枚举项为准，重建「课程方向」
-- (code=course_type) 的枚举项：编码/名称/排序/状态完全对齐。
DELETE FROM dictionary_items
WHERE type_id = (SELECT id FROM dictionary_types WHERE code = 'course_type');

INSERT INTO dictionary_items
    (type_id, code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT
    (SELECT id FROM dictionary_types WHERE code = 'course_type'),
    di.code, di.name, di.description, di.status, di.sort_order, 0, di.created_at, di.updated_at
FROM dictionary_items di
WHERE di.type_id = (SELECT id FROM dictionary_types WHERE code = 'question_direction');
