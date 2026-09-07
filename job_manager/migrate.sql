-- ============================================
-- 数据库迁移：为现有表补充新列
-- 执行方式： mysql -ujob_CAIQABiAB -p'密码' job < migrate.sql
-- ============================================

-- 1. 校区表：地址 / 负责人 / 联系方式
ALTER TABLE `campuses`
  ADD COLUMN `address` VARCHAR(200) DEFAULT '' COMMENT '校区地址' AFTER `name`,
  ADD COLUMN `manager` VARCHAR(50) DEFAULT '' COMMENT '负责人' AFTER `address`,
  ADD COLUMN `contact` VARCHAR(20) DEFAULT '' COMMENT '联系方式' AFTER `manager`;

-- 2. 岗位表：来源
ALTER TABLE `jobs`
  ADD COLUMN `source` VARCHAR(50) DEFAULT '' COMMENT '来源' AFTER `job_category`;

-- 3. 推送记录表：是否撤销
ALTER TABLE `push_records`
  ADD COLUMN `is_revoked` TINYINT(1) DEFAULT 0 COMMENT '是否撤销' AFTER `is_read`;
