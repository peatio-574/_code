-- 题型配置分数：每个题型分组可配置该题型每道题的分值。
-- 评卷时优先使用分组分值（score>0），否则回退题目自身分值。
ALTER TABLE exam_sections
    ADD COLUMN score INT NOT NULL DEFAULT 0;
