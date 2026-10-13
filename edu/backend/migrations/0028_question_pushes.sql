-- 题库推送：把若干题目推送给指定学员，学员端练习仅可见被推送的题目。
--
-- 项目约定：不使用外键/唯一/检查约束与触发器；业务唯一性由应用层命名锁保证。
CREATE TABLE question_pushes (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    question_id BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    pushed_by BIGINT NOT NULL,
    created_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX question_pushes_question_id ON question_pushes(question_id);
CREATE INDEX question_pushes_student_id ON question_pushes(student_id);
