-- 试卷开放校区：一份试卷可开放给多个校区（空表示不限校区）。
--
-- 项目约定：不使用外键/唯一/检查约束与触发器；业务唯一性由应用层命名锁保证。
CREATE TABLE exam_campuses (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    exam_id BIGINT NOT NULL,
    campus_id BIGINT NOT NULL,
    created_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX exam_campuses_exam_id ON exam_campuses(exam_id);
CREATE INDEX exam_campuses_campus_id ON exam_campuses(campus_id);
