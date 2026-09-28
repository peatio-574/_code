-- 统一“题目方向”：以字典类型 question_direction 为唯一来源，
-- 将原 question_categories（练习类型）迁移为字典项，并把题目关联切换到字典项。

INSERT INTO dictionary_types
    (code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT 'question_direction', '题目方向', '题库题目的方向分类', 1, 30, 1, 0, 0
WHERE NOT EXISTS (SELECT 1 FROM dictionary_types WHERE code = 'question_direction');

INSERT INTO dictionary_items
    (type_id, code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT dt.id, CONCAT('dir_', qc.id), qc.name, '', qc.status, qc.sort_order, 0, 0, 0
FROM question_categories qc
JOIN dictionary_types dt ON dt.code = 'question_direction'
WHERE NOT EXISTS (
    SELECT 1 FROM dictionary_items di WHERE di.type_id = dt.id AND di.name = qc.name
);

UPDATE questions q
JOIN question_categories qc ON qc.id = q.category_id
JOIN dictionary_types dt ON dt.code = 'question_direction'
JOIN dictionary_items di ON di.type_id = dt.id AND di.name = qc.name
SET q.category_id = di.id;
