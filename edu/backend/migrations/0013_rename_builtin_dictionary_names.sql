-- 课程分类：课程管理中统称“课程分类”，由字典管理维护。
-- 仅调整内置字典类型的名称与说明，字典项与编码保持不变，历史数据无需迁移。
UPDATE dictionary_types
SET name = '课程分类', description = '课程业务分类'
WHERE code = 'course_type';

-- 题库类型同步为“练习类型”，与题库练习页面口径一致。
UPDATE dictionary_types
SET name = '练习类型', description = '题目作答与练习分类'
WHERE code = 'question_type';
