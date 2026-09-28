-- 课程方向：课程管理中统称“课程方向”，由字典管理维护。
-- 仅调整内置字典类型的名称与说明，字典项与编码保持不变，历史数据无需迁移。
UPDATE dictionary_types
SET name = '课程方向', description = '课程业务方向'
WHERE code = 'course_type';
