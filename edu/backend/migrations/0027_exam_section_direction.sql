-- 试卷题型分组的「题目方向」：每个分组可指定一个题目方向（单选）。
-- 保存时按该方向抽题/校验；0 表示不限方向。
ALTER TABLE exam_sections
    ADD COLUMN category_id BIGINT NOT NULL DEFAULT 0;
