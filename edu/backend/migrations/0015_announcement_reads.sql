-- 公告阅读记录与更新时间。
--
-- 项目约定：不使用外键、唯一约束、检查约束与触发器；业务唯一性由应用层的
-- 命名锁（named_lock）保证。此处仅新增表、索引与列。
--
-- 1) announcement_reads 记录「某用户已阅读某公告」，用于统计已读/待读人数。
-- 2) announcements.updated_at 记录最近更新时间，列表展示用。
CREATE TABLE announcement_reads (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    announcement_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    read_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX announcement_reads_announcement_id ON announcement_reads(announcement_id);
CREATE INDEX announcement_reads_user_id ON announcement_reads(user_id);

ALTER TABLE announcements ADD COLUMN updated_at BIGINT NOT NULL DEFAULT 0;
UPDATE announcements SET updated_at = created_at WHERE updated_at = 0;
