# 服务器部署与数据库复用说明（education_rust）

> 目标服务器：`118.24.15.163`（TencentOS 4 / 内核 6.6，Python 3.11.6，MySQL 8.0.45，Nginx）
> 复用生产库：**`education_rust`**（原 Rust 后端使用），**不重建、不清库**。
> 应用：FastAPI 后端（Python）+ Vue3 前端（Nginx 静态托管），复用现有 Nginx。

---

## 1. 部署架构

```
浏览器 ──http://118.24.15.163/ ──► Nginx :80
                                     ├─ /            → /srv/education/frontend-current（前端 dist，软链）
                                     ├─ /api/        → 127.0.0.1:18081（FastAPI 后端）
                                     ├─ /logo.png、/portal-banner.png 等静态资源 → 同上目录
                                     └─ 其它 SPA 路由 → /index.html
FastAPI :18081 ──► MySQL 127.0.0.1:3306 / education_rust（生产库）
              └─► /srv/education/shared/data/uploads（复用旧后端的上传目录，视频/封面/头像）
```

关键路径与文件：

| 项 | 路径 |
| --- | --- |
| 后端代码 | `/srv/edu-api/app` |
| 后端虚拟环境 | `/srv/edu-api/venv` |
| 后端环境变量 | `/srv/edu-api/app/.env` |
| systemd 服务 | `/etc/systemd/system/edu-api.service` |
| 前端 release | `/srv/education/frontend-releases/edu-py-<时间戳>` |
| 前端当前软链 | `/srv/education/frontend-current` |
| 上传目录 | `/srv/education/shared/data/uploads`（属主 `education:education`） |
| Nginx 站点 | `/etc/nginx/conf.d/pinslive.com.conf` |
| 数据库备份 | `/root/db_backup/education_rust_<时间戳>.sql.gz` |

---

## 2. 数据库复用（核心）

### 2.1 连接账号

- **服务器上 `root/root123` 不可用**（`Access denied`）。
- 生产实际使用**应用账号**（见 `/srv/edu-api/app/.env` 的 `DATABASE_URL`）：
  `edu_rust_app`（2026-10-08 安全加固后由原 `job_CAIQABiAB` 更换而来），仅可访问 `education_rust`。
- 新后端 `.env` 中 `DATABASE_URL` 使用该应用账号（密码做 URL 编码），前缀改为 `mysql+pymysql://`：

  ```
  DATABASE_URL=mysql+pymysql://edu_rust_app:<password>@127.0.0.1:3306/education_rust
  ```

### 2.2 结构与数据差异（本地 vs 生产，结论）

生产 `education_rust` 由旧 Rust（sqlx）维护，仅 `_sqlx_migrations` 1–11；本地在此基线上新增了 12–25 号迁移。

- 生产**没有**、本地多出的表：`announcement_reads`、`exam_campuses`；以及迁移记录表 `py_schema_migrations`。
- 本地多出的列：`users.password_plain`、`announcements.updated_at`、`exam_sections.score`、`exams.end_time`。
- 索引：无差异；生产无本地缺失的表。

即：**本地 education_rust = 生产基线（sqlx 1–11） + 本项目 12–25 号迁移**。因此新后端首次启动时：

1. 检测到 `_sqlx_migrations`，把 1–11 导入 `py_schema_migrations`（跳过，不重复执行）；
2. 依次执行本项目的 12–25 号迁移；
3. 幂等写入 RBAC 种子（角色/权限/矩阵/测试账号）。

> 迁移对账逻辑见 `backend/app/db.py::run_migrations`，策略是**只追加、不重建**。

### 2.3 迁移内容与生产影响

| 版本 | 内容 | 对生产影响 |
| --- | --- | --- |
| 0012 | 移除 teacher 角色 | 无 teacher 数据则无操作 |
| 0013/0019 | 字典名称改为「课程方向 / 练习类型」 | 仅改名 |
| 0014 | 字典项排序归一 | 仅排序 |
| 0015 | 新增 `announcement_reads`、`announcements.updated_at` | 新增表/列，回填 updated_at=created_at |
| 0016 | 删除 `console.files.manage` 权限 | 权限项移除 |
| 0017/0018 | 新增 `users.password_plain` 并回填 | 新增列；按手机号后 6 位回填 |
| 0020 | 新增 `exam_sections.score` | 新增列 |
| 0021 | 新增 `exams.end_time` | 新增列，0 表示回退「开始时间+时长」 |
| 0022 | 新增 `exam_campuses` | 新增表 |
| 0023 | 修正演示账号密码明文 | 生产无对应哈希则无操作 |
| 0024 | 以 `question_categories` 生成 `question_direction` 字典项，并**改写 `questions.category_id` 为字典项 id** | **有影响**，见下 |
| 0025 | 用「题目方向」枚举项重建「课程方向」枚举项 | **有影响**，见下 |

**注意 0024/0025 的设计前提**：新后端统一以字典表维护「题目方向」和「课程方向」；`questions.category_id` 现指向 `dictionary_items.id`（不再是 `question_categories.id`）。因此：
- **请勿同时运行旧 Rust 后端**（它会按旧口径读 `question_categories`，导致方向错乱）。实际部署时旧 `education.service` 已为 `inactive`。
- `question_categories` 表保留但不再被新后端使用（可作历史只读）。

**0025 的遗留值**：重建后「课程方向」枚举项与「题目方向」完全一致（`dir_1..dir_12`、`item_1`、`item_2`）。生产原有 15 门课程 `course_type_code='video'`，其值已不在字典中（孤儿编码），**未自动保留**，需在「控制台 → 课程管理」重新选择课程方向。

已验证部署后数据完整性：`courses=15`（无丢失）、`questions=9402` 且 `category_id` 全部成功映射（`SUM(category_id>0)=9402`）、`users=16`、迁移到 25。

---

## 3. 已完成部署步骤（首次）

1. **备份生产库**（务必）：
   ```bash
   export MYSQL_PWD='<app_password>'
   mysqldump -u edu_rust_app --single-transaction --routines --triggers --events --hex-blob \
     education_rust | gzip > /root/db_backup/education_rust_$(date +%Y%m%d_%H%M%S).sql.gz
   ```
2. **打包并上传**（本地执行）：
   ```powershell
   # 后端（排除 .venv/__pycache__/data/.env）
   tar -czf edu-api.tar.gz -C D:\_code\edu\backend --exclude=.venv --exclude=__pycache__ --exclude=data --exclude=.env --exclude="*.pyc" .
   # 前端（构建产物）
   cd D:\_code\edu\frontend; npm run build
   tar -czf edu-web.tar.gz -C dist .
   # 上传到服务器 /srv/edu-api/
   scp edu-api.tar.gz edu-web.tar.gz root@118.24.15.163:/srv/edu-api/
   ```
3. **服务器初始化**：
   ```bash
   mkdir -p /srv/edu-api/app
   tar -xzf /srv/edu-api/edu-api.tar.gz -C /srv/edu-api/app
   cd /srv/edu-api && python3 -m venv venv
   ./venv/bin/pip install -r app/requirements.txt
   # 写入 app/.env（见 deploy/edu-api.env.example），指向 education_rust + 复用上传目录
   ```
4. **注册服务**：复制 `deploy/edu-api.service` 到 `/etc/systemd/system/`，`daemon-reload`、`enable --now`。
5. **部署前端**：执行 `deploy/deploy-edu-web.sh`（解包到新 release 并原子切换 `frontend-current`，同时复用历史 `logo.png`）。
6. **切换 Nginx**：将 `/etc/nginx/conf.d/pinslive.com.conf` 中 `/api/` 的 `proxy_pass` 由 `127.0.0.1:18080` 改为 `127.0.0.1:18081`，`nginx -t && systemctl reload nginx`。
7. **停用旧 Rust 后端**（避免与新后端争用同一库）：`systemctl stop education.service && systemctl disable education.service`。

---

## 4. 日常更新（重复部署）

1. 本地重新打包后上传 `/srv/edu-api/`；
2. 后端：`bash /srv/edu-api/deploy-edu-api.sh`（保留 `.env`，装依赖，重启并自动跑新迁移）；
3. 前端：`bash /srv/edu-api/deploy-edu-web.sh`（新 release + 原子切换，无需改 Nginx）。

> 脚本源码见仓库 `deploy/deploy-edu-api.sh`、`deploy/deploy-edu-web.sh`。

---

## 5. 验证结果（部署后实测）

| 检查 | 结果 |
| --- | --- |
| `GET /api/health` | `200 {"status":"ok"}` |
| `POST /api/login`（test_system_admin） | 成功，返回角色/权限 |
| `/api/admin/{exams,students,courses,questions,teachers,campuses,users,announcements,dictionary-types,dashboard}` | 全部 200 |
| `/api/{system/config,course/,question-categories,dictionaries/*/items}` | 全部 200 |
| 首页/静态资源 | `index.html` `logo.png` `portal-banner.png` 均 200 |
| 图片 `GET /api/image/<id>` | 200（`image/jpeg`，公开） |
| 视频 Range `GET /api/video/<id>`（带会话） | **206 Partial Content**，`accept-ranges: bytes` |
| 迁移记录 | `py_schema_migrations` 到 **25**（sqlx 1–11 已导入） |
| 数据完整性 | `courses=15`、`questions=9402`（category 全部映射）、`users=16` |

---

## 6. 回滚

- **后端**：`systemctl stop edu-api.service`，将 Nginx `/api/` 改回 `127.0.0.1:18080` 并 `reload`，`systemctl start education.service`（旧 Rust 后端）。
- **前端**：把 `frontend-current` 指回旧 release：
  `ln -sfn /srv/education/frontend-releases/frontend-test-20260921-bdf5065 /srv/education/frontend-current`
- **数据库**：仅在必要时用 `/root/db_backup/` 的备份恢复（注意：会回退 12–25 号迁移的改动）。

---

## 7. 注意事项

- **不要用 `root/root123`** 连服务器数据库；使用应用账号，密码在 `/srv/education/shared/education.env`。
- `admin_guard` 对未知 `/api/admin/*` 资源默认要求 `console.system.manage`；新增控制台资源需同步更新 `backend/app/admin_guard.py`。
- `files.storage_path` 存绝对路径，务必保持 `STORAGE_DIR=/srv/education/shared/data/uploads`，且运行用户 `education` 对该目录可读写。
- 同一库**不可**让旧 Rust 后端与新 FastAPI 后端同时对外服务（0024 后 `category_id` 口径不同）。
- 课程方向重建后原有 `video` 编码成为孤儿，请在控制台重新归置 15 门课程的课程方向。
- 系统配置中 `logo=/logo.png` 为绝对路径，前端已支持绝对路径与文件 id 两种写法（`resolveImageUrl`）。
