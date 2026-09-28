-- 回填历史账号的初始密码明文。
--
-- 迁移 0017 新增了 password_plain，但历史账号均为 argon2 哈希、无法还原。
-- 系统创建管理员/学员时的默认密码规则为「手机号后 6 位」，此处按该规则为
-- 尚未记录明文的账号回填，使控制台编辑页可回显；已显式改密的账号不受影响
-- （其 password_plain 非空，不会命中 WHERE 条件）。
UPDATE users
SET password_plain = RIGHT(mobile, 6)
WHERE password_plain = ''
  AND mobile IS NOT NULL
  AND CHAR_LENGTH(mobile) >= 6;
