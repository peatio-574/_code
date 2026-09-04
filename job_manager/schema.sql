-- ============================================
-- Job Manager 数据库DDL脚本
-- 生成时间: 2026-09-04
-- ============================================

-- 使用job数据库
USE job;

-- ============================================
-- 按照外键依赖顺序删除表
-- ============================================
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `operation_logs`;
DROP TABLE IF EXISTS `push_records`;
DROP TABLE IF EXISTS `jobs`;
DROP TABLE IF EXISTS `users`;
DROP TABLE IF EXISTS `roles`;
DROP TABLE IF EXISTS `campuses`;

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================
-- 1. 校区表
-- ============================================
CREATE TABLE `campuses` (
  `id` INT(11) NOT NULL AUTO_INCREMENT COMMENT '校区ID，主键',
  `name` VARCHAR(100) NOT NULL COMMENT '校区名称',
  `is_active` TINYINT(1) DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  `is_deleted` TINYINT(1) DEFAULT 0 COMMENT '是否删除：1=已删除，0=正常',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campuses_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='校区信息表';

-- ============================================
-- 2. 角色表
-- ============================================
DROP TABLE IF EXISTS `roles`;
CREATE TABLE `roles` (
  `id` INT(11) NOT NULL AUTO_INCREMENT COMMENT '角色ID，主键',
  `name` VARCHAR(50) NOT NULL COMMENT '角色名称',
  `is_active` TINYINT(1) DEFAULT 1 COMMENT '是否启用',
  `is_deleted` TINYINT(1) DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_roles_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色信息表';

-- ============================================
-- 3. 用户表（超管/管理员/学员）
-- ============================================
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `id` INT(11) NOT NULL AUTO_INCREMENT COMMENT '用户ID，主键',
  `username` VARCHAR(18) NOT NULL COMMENT '登录账号',
  `password_hash` VARCHAR(256) NOT NULL COMMENT '密码哈希值',
  `password_plain` VARCHAR(100) DEFAULT '' COMMENT '密码明文（仅超管可见）',
  `user_type` VARCHAR(20) NOT NULL COMMENT '用户类型：super_admin/admin/student',
  
  `real_name` VARCHAR(50) DEFAULT '' COMMENT '真实姓名',
  `phone` VARCHAR(20) DEFAULT '' COMMENT '手机号码',
  `email` VARCHAR(120) DEFAULT '' COMMENT '邮箱',
  `id_card` VARCHAR(18) DEFAULT '' COMMENT '身份证号',
  `gender` VARCHAR(10) DEFAULT '' COMMENT '性别',
  `birth_date` DATE DEFAULT NULL COMMENT '出生日期',
  `avatar` VARCHAR(256) DEFAULT '' COMMENT '头像',
  
  `education` VARCHAR(20) DEFAULT '' COMMENT '学历',
  `major` VARCHAR(100) DEFAULT '' COMMENT '专业',
  `political_status` VARCHAR(20) DEFAULT '' COMMENT '政治面貌',
  `is_party_member` TINYINT(1) DEFAULT 0 COMMENT '是否党员',
  `intention_city` VARCHAR(100) DEFAULT '' COMMENT '意向城市',
  `first_intention` VARCHAR(100) DEFAULT '' COMMENT '第一意向岗位',
  `second_intention` VARCHAR(100) DEFAULT '' COMMENT '第二意向岗位',
  `third_intention` VARCHAR(100) DEFAULT '' COMMENT '第三意向岗位',
  `certificate` VARCHAR(200) DEFAULT '' COMMENT '证书',
  `remark` TEXT COMMENT '备注',
  `graduation_date` DATE DEFAULT NULL COMMENT '毕业时间',
  `origin_place` VARCHAR(100) DEFAULT '' COMMENT '生源地',
  
  `campus_id` INT(11) DEFAULT NULL COMMENT '所属校区',
  `role` VARCHAR(50) DEFAULT '' COMMENT '角色名称',
  `can_push_jobs` TINYINT(1) DEFAULT 0 COMMENT '岗位推送权限',
  `can_view_jobs` TINYINT(1) DEFAULT 0 COMMENT '岗位查看权限',
  `can_manage_students` TINYINT(1) DEFAULT 0 COMMENT '学员管理权限',
  
  `is_active` TINYINT(1) DEFAULT 1 COMMENT '账号状态',
  `is_deleted` TINYINT(1) DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `created_by` INT(11) DEFAULT NULL COMMENT '创建人ID',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`),
  INDEX `idx_users_user_type` (`user_type`),
  INDEX `idx_users_campus_id` (`campus_id`),
  INDEX `idx_users_created_by` (`created_by`),
  CONSTRAINT `fk_users_campus` FOREIGN KEY (`campus_id`) REFERENCES `campuses` (`id`),
  CONSTRAINT `fk_users_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户信息表（超管/管理员/学员）';

-- ============================================
-- 4. 岗位信息表
-- ============================================
DROP TABLE IF EXISTS `jobs`;
CREATE TABLE `jobs` (
  `id` INT(11) NOT NULL AUTO_INCREMENT COMMENT '岗位ID',
  `province` VARCHAR(50) DEFAULT '' COMMENT '省份',
  `city` VARCHAR(50) DEFAULT '' COMMENT '城市',
  `job_name` VARCHAR(100) NOT NULL COMMENT '职位名称',
  `company_name` VARCHAR(200) NOT NULL COMMENT '公司名称',
  `company_type` VARCHAR(50) DEFAULT '' COMMENT '公司性质',
  `company_size` VARCHAR(50) DEFAULT '' COMMENT '公司规模',
  `company_industry` VARCHAR(100) DEFAULT '' COMMENT '公司行业',
  `recruit_type` VARCHAR(50) DEFAULT '' COMMENT '招聘类型',
  `job_nature` VARCHAR(50) DEFAULT '' COMMENT '职位性质',
  `job_category` VARCHAR(100) DEFAULT '' COMMENT '职位类别',
  `salary_range` VARCHAR(50) DEFAULT '' COMMENT '薪资范围',
  `recruit_count` INT(11) DEFAULT 1 COMMENT '招聘人数',
  `education_req` VARCHAR(50) DEFAULT '' COMMENT '学历要求',
  `experience_req` VARCHAR(50) DEFAULT '' COMMENT '经验要求',
  `major_req` VARCHAR(200) DEFAULT '' COMMENT '专业要求',
  `work_location` VARCHAR(100) DEFAULT '' COMMENT '工作地点',
  `address` VARCHAR(200) DEFAULT '' COMMENT '详细地址',
  `deadline` DATETIME DEFAULT NULL COMMENT '报名截止时间',
  `job_detail` TEXT COMMENT '职位描述',
  `status` VARCHAR(20) DEFAULT 'active' COMMENT '状态',
  `is_deleted` TINYINT(1) DEFAULT 0 COMMENT '是否删除',
  `created_by` INT(11) DEFAULT NULL COMMENT '创建人',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_jobs_status` (`status`),
  INDEX `idx_jobs_created_by` (`created_by`),
  CONSTRAINT `fk_jobs_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位信息表';

-- ============================================
-- 5. 岗位推送记录表
-- ============================================
DROP TABLE IF EXISTS `push_records`;
CREATE TABLE `push_records` (
  `id` INT(11) NOT NULL AUTO_INCREMENT COMMENT '记录ID',
  `job_id` INT(11) NOT NULL COMMENT '岗位ID',
  `student_id` INT(11) NOT NULL COMMENT '学员ID',
  `pushed_by` INT(11) NOT NULL COMMENT '推送人ID',
  `pushed_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '推送时间',
  `is_read` TINYINT(1) DEFAULT 0 COMMENT '是否已读',
  `is_deleted` TINYINT(1) DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_push_records_job_id` (`job_id`),
  INDEX `idx_push_records_student_id` (`student_id`),
  INDEX `idx_push_records_pushed_by` (`pushed_by`),
  CONSTRAINT `fk_push_records_job` FOREIGN KEY (`job_id`) REFERENCES `jobs` (`id`),
  CONSTRAINT `fk_push_records_student` FOREIGN KEY (`student_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_push_records_pusher` FOREIGN KEY (`pushed_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位推送记录表';

-- ============================================
-- 6. 操作日志表
-- ============================================
DROP TABLE IF EXISTS `operation_logs`;
CREATE TABLE `operation_logs` (
  `id` INT(11) NOT NULL AUTO_INCREMENT COMMENT '日志ID',
  `user_id` INT(11) NOT NULL COMMENT '操作人',
  `action` VARCHAR(50) NOT NULL COMMENT '操作类型',
  `target_type` VARCHAR(50) DEFAULT '' COMMENT '操作对象类型',
  `target_id` INT(11) DEFAULT 0 COMMENT '操作对象ID',
  `details` TEXT COMMENT '操作详情',
  `ip_address` VARCHAR(50) DEFAULT '' COMMENT 'IP地址',
  `is_deleted` TINYINT(1) DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_operation_logs_user_id` (`user_id`),
  CONSTRAINT `fk_operation_logs_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作日志表';

-- ============================================
-- 插入默认数据
-- ============================================

-- 插入默认角色
INSERT INTO `roles` (`name`, `is_active`) VALUES 
  ('超级管理员', 1),
  ('校区管理员', 1),
  ('普通管理员', 1);

-- 插入默认校区
INSERT INTO `campuses` (`name`, `is_active`) VALUES 
  ('默认校区', 1);

-- 插入超级管理员账号
-- 密码: admin123
INSERT INTO `users` (`username`, `password_hash`, `password_plain`, `user_type`, `real_name`, `role`, `is_active`) VALUES 
  ('admin', 'pbkdf2:sha256:260000$randomsalt$hashvalue', 'admin123', 'super_admin', '超级管理员', '超级管理员', 1);

-- 注意：实际的password_hash需要通过werkzeug生成，上面的hashvalue是占位符
-- 建议通过应用初始化脚本来创建超级管理员
