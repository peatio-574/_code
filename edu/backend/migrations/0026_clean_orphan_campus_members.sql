-- 清理悬空的校区成员记录：这些成员指向的用户已被删除。
--
-- 背景：校区列表的「管理员数量 / 学员数量」此前直接统计 campus_members，
-- 未校验用户是否仍存在；当用户被带外删除（如脚本直删）后会残留成员记录，
-- 导致计数虚高，且与成员抽屉（INNER JOIN users）显示的数量不一致。
-- 此迁移移除所有 user_id 已不存在于 users 的成员记录。
DELETE cm FROM campus_members cm
LEFT JOIN users u ON u.id = cm.user_id
WHERE u.id IS NULL;
