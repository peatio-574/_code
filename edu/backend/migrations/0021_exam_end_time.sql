-- 试卷结束时间：允许显式配置考试截止时间。
-- end_time > 0 时以其为准；为 0 时回退 exam_time + duration*60，兼容历史数据。
ALTER TABLE exams
    ADD COLUMN end_time BIGINT NOT NULL DEFAULT 0;
