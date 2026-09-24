-- 移除文件管理功能：删除 console.files.manage 权限及其角色授权。
--
-- 项目约定：迁移只追加。文件上传/访问接口仍保留（课程封面、视频、头像等
-- 业务依赖），仅移除控制台的文件管理入口与对应权限项。
DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'console.files.manage');

DELETE FROM permissions WHERE code = 'console.files.manage';
