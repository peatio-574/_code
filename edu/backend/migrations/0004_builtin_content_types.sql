-- Stable, application-owned content type dictionaries.
-- Built-in items may be renamed or disabled by administrators, but cannot be
-- deleted. Course delivery is currently restricted to `video` in Rust code;
-- future formats can be enabled without changing the courses table.

INSERT INTO dictionary_types
    (code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT 'course_type', '课程类型', '课程内容载体类型', 1, 10, 1, 0, 0
WHERE NOT EXISTS (SELECT 1 FROM dictionary_types WHERE code = 'course_type');

UPDATE dictionary_types
SET built_in = 1, description = '课程内容载体类型'
WHERE code = 'course_type';

INSERT INTO dictionary_items
    (type_id, code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT dt.id, 'video', '视频', '视频课程', 1, 10, 1, 0, 0
FROM dictionary_types dt
WHERE dt.code = 'course_type'
  AND NOT EXISTS (
      SELECT 1 FROM dictionary_items di WHERE di.type_id = dt.id AND di.code = 'video'
  );

UPDATE dictionary_items di
JOIN dictionary_types dt ON dt.id = di.type_id
SET di.built_in = 1
WHERE dt.code = 'course_type' AND di.code = 'video';

UPDATE courses SET course_type_code = 'video';

INSERT INTO dictionary_types
    (code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT 'question_type', '题库类型', '题目作答类型', 1, 20, 1, 0, 0
WHERE NOT EXISTS (SELECT 1 FROM dictionary_types WHERE code = 'question_type');

UPDATE dictionary_types SET built_in = 1 WHERE code = 'question_type';

INSERT INTO dictionary_items
    (type_id, code, name, description, status, sort_order, built_in, created_at, updated_at)
SELECT dt.id, seed.code, seed.name, '', 1, seed.sort_order, 1, 0, 0
FROM dictionary_types dt
JOIN (
    SELECT 'single' AS code, '单选题' AS name, 10 AS sort_order
    UNION SELECT 'multiple', '多选题', 20
    UNION SELECT 'true_false', '判断题', 30
    UNION SELECT 'fill', '填空题', 40
    UNION SELECT 'qa', '问答题', 50
    UNION SELECT 'group', '组合题/材料题', 60
) seed
WHERE dt.code = 'question_type'
  AND NOT EXISTS (
      SELECT 1 FROM dictionary_items di
      WHERE di.type_id = dt.id AND di.code = seed.code
  );

UPDATE dictionary_items di
JOIN dictionary_types dt ON dt.id = di.type_id
SET di.built_in = 1
WHERE dt.code = 'question_type'
  AND di.code IN ('single', 'multiple', 'true_false', 'fill', 'qa', 'group');
