-- 用户初始密码明文，供控制台编辑页回显。
--
-- 项目约定：迁移只追加、不使用外键/唯一/检查约束与触发器。
-- 该列为可逆口令的镜像：创建用户、重置密码、用户改密时同步写入，
-- 仅用于后台管理查看；登录校验仍以 password_hash（argon2id）为准。
ALTER TABLE users ADD COLUMN password_plain VARCHAR(255) NOT NULL DEFAULT '';
