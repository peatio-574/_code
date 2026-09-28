-- 修正演示账号的密码明文回显。
--
-- 迁移 0018 为历史账号统一按「手机号后 6 位」回填 password_plain，但 20k 批量
-- 演示账号（backend/seed_demo.py 创建）实际统一使用密码 Test123!（同一 argon2 哈希）。
-- 这里按该共享哈希精确修正，避免编辑页显示错误密码。
--
-- 注意：不改动 password_hash，登录仍以原哈希校验（Test123!）。
UPDATE users
SET password_plain = 'Test123!'
WHERE password_hash = '$argon2id$v=19$m=65536,t=3,p=4$r+HakboHsuPsrfBhzim91A$y2F3ewUSSkRAZXsqz+JoL1xlWP5z6Q10C0M/pUIUhVk';
