# 聘书云课堂 · 完整需求与设计文档（V4）

> 版本：4.0
> 日期：2026-09-23
> 依据：用户需求 + `D:\_code\job_manager` 实现 + 现有 `D:\code\edu` 库表（Rust/React/MySQL）
> 技术实现：Python(FastAPI) + Vue3 + MySQL + Nginx
> 数据库策略：**沿用服务器现有库表**，本地开发完成后生产环境直接读取既有库表，不重建

---

## 0. 目录

1. 具体需求细节
2. 技术栈要求
3. 系统架构与部署
4. 库表关系
5. 加密与验证机制
6. API 设计
7. 权限与数据隔离
8. 业务逻辑（处理流程）
9. 非功能需求
10. 待确认事项
11. 实施阶段

---

## 1. 具体需求细节

### 1.0 命名与对齐口径

| 本系统 | job_manager | 说明 |
| --- | --- | --- |
| 超级管理员 | `super_admin` | 全平台 |
| 管理员 | `admin` | 归属校区；校长/班主任/自定义角色 |
| 学员 | `student` | 归属校区与上级管理员 |
| 姓名 | `real_name` | |
| 手机号 | `phone` | 同时作为登录账号 `username` |

保留 job_manager 核心管理逻辑：超管专属模块、管理员/学员按校区隔离、手机号即账号、默认密码规则、删除二次确认、批量删除、状态开关、分页 20/50/100、手机号脱敏、导入导出。

### 1.1 前端页面总览

| 页面 | 路由 | 可见角色 |
| --- | --- | --- |
| 首页 | `/` | 全部 |
| 课程中心 | `/courses` | 登录用户 |
| 题库练习 | `/question` | 登录用户 |
| 冲刺考试 | `/exams` | 登录用户 |
| 个人中心 | `/profile` | 登录用户 |
| 控制台 | `/admin/*` | 超级管理员、管理员 |

- 学员看不到「控制台」入口；直接访问控制台路由返回 403 并跳回首页。
- 管理员/超管显示控制台入口，进入独立管理壳层（左侧导航）。

### 1.2 登录（具体）

**页面**：登录页 UI 保持不变。

**流程**：

1. 输入账号（手机号/用户名）与密码。
2. 限流键 = `客户端IP + 账号`。
3. 若该键已锁定且未到期 → 提示「登录失败次数过多，请稍后重试」，拒绝。
4. 查询用户；不存在或密码错误 → 记一次失败：连续失败 +1；达到 **5 次** 锁定 **15 分钟**；提示「用户名或密码错误」。
5. 账号被禁用 → 提示「账号已被禁用」。
6. 登录成功 → 清零失败计数 → 写登录日志 → 建立会话。
7. 跳转：管理员 → 控制台总览；学员 → 首页。

**提示文案（固定）**：

| 场景 | 文案 |
| --- | --- |
| 账号或密码为空 | 请输入账号和密码 |
| 账号或密码错误 | 用户名或密码错误 |
| 连续失败达 5 次 | 登录失败次数过多，请稍后重试 |
| 账号被禁用 | 账号已被禁用 |
| 成功 | 登录成功 |

**验收**：

- 连续 5 次错误密码后，第 6 次被拒绝并提示稍后重试。
- 锁定期内即使密码正确也拒绝；锁定期过后恢复。
- 登录成功后计数清零。

### 1.3 首页

- **背景轮询**：多张背景图自动轮播，带科幻感；后台可配置图片与切换间隔；移动端适配。
- 内容区：Banner、最新课程、快捷入口，后台可配置。
- **底部友情链接**：后台配置多条（名称、链接、排序、启用状态）；展示为友好的文字/图标链接，hover 反馈，移动端换行；未配置则不显示。
- 登录后展示会话级公告弹窗一次。

### 1.4 课程中心

- 筛选：**课程类型**，下拉多选，枚举来自后台字典「课程类型」。
- 列表单条：封面图、课程名称、教师头像、教师名称、章节数、`new` 标签（后台可配置）。
- 分页：每页 **20 / 50 / 100**，支持跳页，显示总数。
- 支持按课程名称搜索。
- 课程详情：课程概述、开始学习按钮、封面图、课程介绍、章节、课程总时长、学习总时长、章节列表。
- 章节列表每行：章节号、章节标题、视频时长 / 当前学习时长、学习按钮。
- 视频学习页：记录上次进度，再次进入从上次位置继续；右侧章节列表可切换章节；观看会话 + 心跳上报，完成状态服务端判定。

### 1.5 题库练习

- 概览：总题目数、已练习题目数、正确数、错误数；「错题列表」「错题重练」入口。
- 错题列表：进入后展示错题数据；点击详情展示错题、用户答案、正确答案。
- 错题重练：进入后重新作答；**不计入正确数与首次统计**。
- 筛选：练习类型（多选，后台字典配置）、题型（多选，后台字典配置,固定为六类：单选题、多选题、判断题、填空题、问答题、综合答题）。
- 题目区：一次一题，提供「上一题 / 下一题」；存在未做题时明确提示；即时判分并展示正确答案与解析。
- 续做：优先「已领取未答」，否则随机未做题；首次有效作答是进度与正确率唯一口径。

### 1.6 冲刺考试

- 模拟考试：按钮进入模拟考试页；一次显示所有题目，支持跳转，标识已答/未答；题目分类、题型、数量由控制台配置。
- 考试统计：已参加考试次数（**不含模拟**）、平均得分、合格次数。
- 可参加考试：列表展示，点击进入；支持断点恢复、自动保存、倒计时、交卷。
- 成绩：成绩列表，点击查看考试详情（逐题正误、得分）。

### 1.7 个人中心

- 修改资料：姓名、手机号、头像。手机号 11 位且唯一；学员手机号即账号，同步更新 `username`；头像上传校验类型与大小。
- 修改密码：校验原密码、两次一致、长度 ≥6；成功后其他会话失效。

### 1.8 控制台模块

> 通用：分页 20/50/100；列表默认按更新时间倒序；所有写操作记录操作日志；非超管数据限于本校区。

#### 1.8.1 总览

- 指标：活跃学员数、已发布课程数、已发布考试数。
- 近七天学习人员情况（按天活跃学员数）。
- 待处理内容：未发布的课程、考试、公告；点击跳转对应页面。
- 范围：超管全平台；管理员本校区。

#### 1.8.2 课程管理

- 权限码 `console.courses.manage`；支持课程类型配置。
- 筛选：课程名称、授课教师。
- 操作：搜索、重置、添加、编辑、批量删除。
- 列表字段：课程名称、授课教师、课程类型、状态（按钮启停）、价格、更新时间、操作（编辑、管理章节、删除）。
- 新增/编辑：课程名称、课程概述、授课教师（多选）、有效时间（开始/结束）、价格、课程类型（多选）、封面图、描述图片（多张）、课程详情、状态（开关，默认启用）。
- 管理章节：添加/删除/编辑；字段：标题、简介、排序、教师、上传视频、视频时长（上传后自动解析）。
- 权限：仅超管可见

#### 1.8.3 题库管理

- 权限码 `console.questions.manage`；支持练习类型配置。
- 筛选：题目名称、练习类型、题型。
- 操作：搜索、重置、添加、编辑、批量删除、导入。
- 列表字段：标题、题型、练习类型、分值、答案、更新时间、状态（按钮启停）、操作（编辑、删除）。
- 新增/编辑：题型、标题、练习类型、分值、题目内容（按题型自适应）、答案、状态（按钮启停）。
- 综合答题支持子题。
- 权限：管理员仅可查看，不可编辑

#### 1.8.4 考试管理

- 权限：考试权限集。
- 筛选：试卷标题。
- 操作：搜索、重置、添加、编辑、批量删除。
- 列表字段：试卷名称、有效时间、更新时间、试卷状态、操作（试卷详情、编辑、考试结果、删除）。
- 试卷状态（按时间推导）：未开考（now < 开始时间）、已开考（开始 ≤ now ≤ 结束）、已结束（now > 结束时间）。
- 新增/编辑：试卷名称、开始时间、结束时间、时长（分钟）、总分、合格线、题目配置（按题型 + 题目标题搜索并勾选组卷）、状态（开关，默认启用）。
- 考试结果：查看学员成绩与明细。
- 模拟考试参数（分类/题型/数量/时长）在系统配置维护。
- 权限：管理员仅可查看、操作自己校区数据

#### 1.8.5 教师管理

- 权限码 `console.teachers.manage`。
- 筛选：教师名称/简介、状态。
- 操作：搜索、重置、添加、编辑、批量删除。
- 列表字段：头像、教师姓名、简介、更新时间、状态（按钮启停）、操作（编辑、删除）。
- 新增/编辑：教师姓名、简介、头像（上传）、状态。教师不设登录账号。
- 权限：仅超管可见

#### 1.8.6 校区管理（仅超管）

- 权限码 `console.campuses.manage`，仅超管。
- 筛选：校区名称、状态。
- 操作：搜索、重置、添加、编辑、批量删除。
- 列表字段：校区名称、校区地址、负责人、联系方式、管理员数量、学员数量、状态、更新时间、操作（编辑、删除）。
- 新增/编辑：校区名称（唯一）、校区地址、负责人、联系方式、状态。
- **状态联动**：停用校区时联动停用该校区下所有管理员与学员；启用时联动启用。
- 删除：批量/单个；删除前校验并处理成员关联。

#### 1.8.7 管理员管理（仅超管）

- 权限码 `console.administrators.manage`，仅超管。
- 筛选：姓名/账号、校区、角色、状态。
- 操作：搜索、重置、添加、编辑、批量删除、状态开关、重置密码。
- 新增字段：姓名、手机号（=账号，11 位唯一）、所属校区、角色（下拉）、密码（默认手机号后 6 位）、状态。
- 编辑字段：同上（密码可重置）。
- 列表字段：账号、姓名、所属校区、角色、手机号（脱敏）、状态、更新时间、操作。
- 删除：不可删除自己；单个删除需二次确认姓名 + 手机号；批量删除自动跳过自己并返回「成功 N 个，跳过 1 个（不能删除自己）」。
- 角色/状态/密码变更后使目标会话失效。

#### 1.8.8 学员管理

- 权限码 `console.students.manage`。
- 筛选：姓名/账号/手机号、校区、学历、状态、创建人（上级管理员）。
- 操作：搜索、重置、添加、编辑、批量删除、状态开关、Excel 导入、下载模板。
- 新增字段：姓名、手机号（=账号，唯一）、身份证号（18 位，唯一）、意向城市、学历、专业、政治面貌、第一/二/三意向、证书、备注、毕业时间、生源地、头像、所属校区（取操作者校区）、密码（默认身份证后 6 位）。
- 身份证解析：自动得出性别与出生日期。
- 数据归属：`campus_id = 操作者校区`，`created_by = 操作者`。
- 编辑：管理员只能编辑本校区/本人创建的学员（对象级校区校验）。
- 列表字段：姓名、账号、校区、上级管理员、手机号（脱敏）、学历、状态、更新时间、操作。
- 删除：单个删除需二次确认姓名 + 手机号；批量删除对越权对象自动跳过。
- - 权限：管理员仅可查看、操作自己校区数据，且仅校长可操作班主任，班主任仅可查看、操作自己及名下学员

#### 1.8.9 角色管理（仅超管）

- 权限码 `console.roles.manage`，仅超管。
- 默认角色：校长、班主任。
- 操作：新增、编辑、删除、状态开关、配置权限。
- 列表字段：角色名称、用户数、状态、更新时间、操作。
- 新增/编辑：角色名称（唯一）、状态、权限勾选（按模块）。
- 删除前校验：仍有用户使用该角色则拒绝。

#### 1.8.10 通知公告

- 权限码 `console.announcements.manage`。
- 操作：新增、编辑、删除、发布/撤回、置顶/取消置顶。
- 列表字段：标题、状态、置顶、创建时间、发布时间、操作。
- 新增/编辑：标题、内容（富文本）、状态。
- 门户：仅已发布公告对所有人可见；登录后会话级弹窗一次。

#### 1.8.11 系统配置

- 权限码 `console.system.manage`。
- 基础信息：系统名称、Logo、页脚。
- 首页配置：背景图轮播、Banner、首页内容、友情链接。
- 隐私政策、用户协议。
- 自动组卷/模拟考试：启用、标题、题目分类、题型比例、题目数量、时长、合格线。

#### 1.8.12 字典管理（仅超管）

- 权限码 `console.dictionaries.manage`。
- 管理字典类型与字典项（编码、名称、排序、状态）。
- 业务字典：课程类型、练习类型。
- 字典项：类型内键自增、显示名、枚举值、排序、状态。
- 内置项不可删除，可停用；禁用项不出现在业务下拉；被业务引用的字典项删除前拒绝。

---

## 2. 技术栈要求

### 2.1 后端

| 组件 | 版本/要求 | 用途 |
| --- | --- | --- |
| Python | ≥ 3.11 | 运行环境 |
| FastAPI | 0.115.x | Web 框架 |
| Uvicorn | 0.34.x | ASGI 服务器 |
| Gunicorn | 23.x | 进程管理（UvicornWorker） |
| SQLAlchemy | 2.0.x | ORM |
| PyMySQL | 1.1.x | MySQL 驱动 |
| Alembic | 1.14.x（可选） | 迁移（若追加变更） |
| argon2-cffi | 23.1.x | 密码哈希 Argon2id |
| bcrypt | 4.2.x | 旧密码哈希兼容校验 |
| Pydantic | 2.10.x | 数据校验 |
| pydantic-settings | 2.7.x | 配置加载 |
| python-multipart | 0.0.20 | 文件上传 |
| openpyxl | 3.1.x | Excel 导入导出 |
| Pillow | 11.x | 图片处理（头像、封面） |
| itsdangerous / secrets | 标准库 | 令牌生成 |

可选存储适配：`boto3`（OSS 兼容 S3）、`oss2`、`cos-python-sdk-v5`。

### 2.2 前端

| 组件 | 版本/要求 | 用途 |
| --- | --- | --- |
| Node.js | 20.20.2（nvm 管理） | 构建环境 |
| Vue | 3.5.x | 框架 |
| Vite | 6.x | 构建工具 |
| TypeScript | 5.7.x | 类型 |
| Element Plus | 2.9.x | UI 组件库 |
| Pinia | 2.3.x | 状态管理 |
| Vue Router | 4.5.x | 路由 |
| Axios | 1.7.x | HTTP 客户端 |
| dayjs | 1.11.x | 时间处理 |
| ECharts + vue-echarts | 5.x | 看板图表 |
| @vueuse/core | 最新兼容 | 工具集 |

### 2.3 数据库与中间件

| 组件 | 版本/要求 |
| --- | --- |
| MySQL | 8.0（现有 `education` 库） |
| 字符集/排序 | utf8mb4 / utf8mb4_0900_ai_ci |
| 存储引擎 | InnoDB |
| Nginx | 1.23+（静态资源 + 反向代理 + TLS） |
| 进程守护 | systemd |
| 日志 | 应用日志文件 + journald；Nginx access/error |

### 2.4 代码目录结构

```text
backend/
├─ app/
│  ├─ main.py               # FastAPI 应用与路由注册
│  ├─ config.py             # 配置（pydantic-settings）
│  ├─ db.py                 # 引擎/会话/命名锁
│  ├─ models.py             # SQLAlchemy 模型（对应现有表）
│  ├─ security.py           # 密码、会话、CSRF
│  ├─ error.py              # 业务异常
│  ├─ response.py           # 统一响应信封
│  ├─ admin_guard.py        # /api/admin 权限中间件映射
│  ├─ domain/               # 领域规则（rbac/data_scope/campus/watch）
│  ├─ api/                  # 路由处理
│  │  ├─ auth.py  users.py  campuses.py  roles.py
│  │  ├─ courses.py  questions.py  exams.py  teachers.py
│  │  ├─ announcements.py  dictionaries.py  system_config.py
│  │  ├─ learning.py  dashboard.py  files.py
│  ├─ schemas/              # Pydantic 请求/响应模型
│  └─ services/             # 业务服务与事务编排
├─ migrations/              # SQL 迁移（沿用现有 0001–0012）
├─ requirements.txt
├─ .env.example
└─ run.py

frontend/
├─ src/
│  ├─ api/                  # 接口封装
│  ├─ components/           # 通用组件
│  ├─ layouts/              # 公共/学员/管理壳层
│  ├─ router/               # 路由与守卫
│  ├─ stores/               # Pinia
│  ├─ views/
│  │  ├─ home/  courses/  questions/  exams/  profile/
│  │  └─ admin/             # 控制台各模块
│  ├─ types/
│  └─ main.ts
├─ package.json
└─ vite.config.ts

deploy/
├─ nginx.conf
├─ edu.service              # systemd
└─ deploy.sh
```

### 2.5 依赖原则

- 前端不假设存在未声明的依赖；新增依赖需明确版本。
- 后端固定 `requirements.txt` 精确版本。
- 不使用数据库外键/唯一约束/触发器（见第 4 章）。

---

## 3. 系统架构与部署

### 3.1 架构

```text
浏览器 → Nginx(80/443, TLS)
           ├── /            → Vue3 构建产物 dist/
           └── /api/        → Gunicorn+Uvicorn(127.0.0.1:8000) → FastAPI → MySQL 8(127.0.0.1:3306)
                                                                     └→ 本地文件存储（uploads）
```

### 3.2 端口与环境

| 项 | 开发 | 生产 |
| --- | --- | --- |
| 前端 | Vite 3000（代理 `/api` 到 8000） | Nginx 80/443 |
| 后端 | Uvicorn 8000 | Gunicorn 127.0.0.1:8000 |
| 数据库 | 127.0.0.1:3306 | 127.0.0.1:3306 |
| 上传目录 | backend/data/uploads | /opt/edu/data/uploads |

### 3.3 环境变量

```text
HOST / PORT
DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/education
SECRET_KEY=<至少32位随机串>
CORS_ALLOW_ORIGINS=http://localhost:3000
COOKIE_SECURE=false(dev)/true(prod)
SESSION_MAX_AGE_SECONDS=604800
LOGIN_MAX_FAILURES=5
LOGIN_LOCKOUT_SECONDS=900
STORAGE_DIR=data/uploads
```

### 3.4 Nginx 要点

- 80 → 443 强制跳转；启用 TLS 与 HSTS。
- 静态资源缓存（`dist/assets` 长缓存，`index.html` 不缓存）。
- `/api/` 反向代理到 127.0.0.1:8000，传递 `Host`、`X-Real-IP`、`X-Forwarded-For`、`X-Forwarded-Proto`。
- 上传体积 `client_max_body_size` 与后端一致。
- SPA 路由回退 `try_files $uri $uri/ /index.html`。

### 3.5 生产部署流程

1. 服务器建库/复用现有 `education` 库（已存在）。
2. 部署后端，`pip install -r requirements.txt`，配置 `.env`。
3. 运行迁移对账（仅校验，不重建）。
4. 前端 `npm ci && npm run build`，产物交给 Nginx。
5. 注册 systemd 服务并启动，健康检查 `/api/health`。
6. 验证四类账号（超管、校长、班主任、学员）与校区隔离。

---

## 4. 库表关系

### 4.1 设计原则

- 沿用服务器现有 `education` 库表，不重建。
- **不使用外键、级联、唯一约束、CHECK、触发器**；仅主键与非唯一查询索引。
- 业务唯一性、关联有效性、级联删除由应用代码在事务 / MySQL 命名锁内实现。
- 审计时间为 Unix 秒 `BIGINT`。
- 主键：业务表 `BIGINT AUTO_INCREMENT`；`files.id` 与 `file_uploads.id` 为 `VARCHAR(36)` UUID；`auth_sessions.token_hash`、`login_throttles.throttle_key` 为字符串主键。

### 4.2 表清单（29 张基线 + 增量）

`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`auth_sessions`、`login_throttles`、`login_logs`、`sys_config`、`teachers`、`categories`、`courses`、`course_teachers`、`course_chapters`、`announcements`、`question_categories`、`questions`、`exams`、`exam_sections`、`exam_section_questions`、`exam_attempts`、`exam_answers`、`files`、`learning_progress`、`course_notes`、`note_likes`、`question_records`、`dictionary_types`、`dictionary_items`、`course_watch_progress`、`course_watch_sessions`、`file_uploads`、`file_upload_parts`、`question_first_answers`、`question_retry_attempts`、`question_retry_answers`、`campuses`、`campus_members`。

### 4.3 关系图（逻辑，无数据库外键）

```text
users ──< user_roles >── roles ──< role_permissions >── permissions
  │                        │
  │                        └── campuses（默认角色用于管理员）
  ├──< auth_sessions（token_hash）
  ├──< campus_members >── campuses
  ├── users.manager_id ──> users.id（自关联：学员→管理员）
  └── users.created_by ──> users.id（创建人/归属）

courses ──< course_teachers >── teachers
   │
   └──< course_chapters ──> teachers（授课教师，可空）
   └──< learning_progress >── users
   └──< course_notes ──< note_likes >── users

question_categories ──< questions ──(parent_id 自关联：题组)
questions ──< question_records >── users
questions ──< question_first_answers >── users
question_retry_attempts ──< question_retry_answers >── questions / users

exams ──< exam_sections ──< exam_section_questions >── questions
exams ──< exam_attempts >── users ──< exam_answers >── questions

users ──< course_watch_progress（user+course+chapter）
users ──< course_watch_sessions
files ──(被引用) courses.cover / courses.description_image / course_chapters.file / teachers.avatar
file_uploads ──< file_upload_parts
dictionary_types ──< dictionary_items
```

### 4.4 核心表字段（与现有结构一致）

**users**

```text
id BIGINT PK AUTO_INCREMENT
username VARCHAR(100)         登录账号（学员=手机号）
password_hash VARCHAR(255)    Argon2id / 兼容 bcrypt
avatar VARCHAR(512) DEFAULT ''
email VARCHAR(255) NULL
mobile VARCHAR(32) NULL
display_name VARCHAR(100) DEFAULT ''
status TINYINT DEFAULT 1      1 启用 / 0 禁用
session_epoch INT DEFAULT 0   会话代次
manager_id BIGINT NULL        直属上级
created_by BIGINT NULL        创建人
updated_by BIGINT NULL
created_at BIGINT DEFAULT 0
updated_at BIGINT DEFAULT 0
索引：manager_id / created_by / status
```

**roles**

```text
id BIGINT PK；code VARCHAR(50)；name VARCHAR(100)；description VARCHAR(255) NULL
data_scope VARCHAR(20) DEFAULT 'self'（self/direct/tree/all）
level INT DEFAULT 100；built_in TINYINT DEFAULT 0；status TINYINT DEFAULT 1
created_at / updated_at BIGINT
索引：code / status
```

**permissions**

```text
id BIGINT PK；code VARCHAR(100)；name VARCHAR(100)；description VARCHAR(255) NULL
module VARCHAR(50) DEFAULT ''；built_in TINYINT DEFAULT 0；status TINYINT DEFAULT 1
created_at / updated_at BIGINT
索引：code / module / status
```

**user_roles / role_permissions**

```text
user_roles(id, user_id, role_id, created_at)
role_permissions(id, role_id, permission_id, created_at)
索引：user_id / role_id / permission_id
```

**auth_sessions**

```text
token_hash VARCHAR(64) PK       sha256(原始令牌) 十六进制
user_id BIGINT
session_epoch INT
csrf_token VARCHAR(64)
login_log_id BIGINT NULL
created_at / last_seen_at / expires_at BIGINT
client_ip VARCHAR(64) DEFAULT ''
user_agent VARCHAR(512) DEFAULT ''
索引：user_id / expires_at
```

**login_throttles**

```text
throttle_key VARCHAR(64) PK      sha256(IP|账号)
failure_count INT DEFAULT 0
locked_until BIGINT NULL
updated_at BIGINT
```

**login_logs**

```text
id PK；user_id BIGINT NULL；attempted_identity VARCHAR(255)
success TINYINT；failure_reason VARCHAR(255) NULL
client_ip VARCHAR(64)；user_agent VARCHAR(512)
login_at BIGINT；logout_at BIGINT NULL
索引：login_at / user_id
```

**sys_config**

```text
id PK；`key` VARCHAR(100)；value MEDIUMTEXT；type INT DEFAULT 1
created_at / created_by / updated_at / updated_by
索引：`key`
```

**campuses / campus_members**

```text
campuses(id, code, name, address, contact_name, contact_mobile, status,
         created_by, updated_by, created_at, updated_at)  索引 code/status
campus_members(id, campus_id, user_id, member_type, is_primary, status,
               joined_at, left_at NULL, created_by, created_at)
   member_type: principal / homeroom_teacher / student（teacher 已移除）
   索引：campus_id / user_id / member_type / status
```

**teachers**

```text
id PK；name VARCHAR(100)；description TEXT；avatar VARCHAR(512) DEFAULT ''
status TINYINT DEFAULT 1；created_by / updated_by / created_at / updated_at
索引：status
```

**courses / course_teachers / course_chapters**

```text
courses(id, name, description TEXT, short_description, category_id, cover, price DECIMAL(12,2),
        duration DECIMAL(10,2), status TINYINT DEFAULT 2, published_at, description_image,
        course_type_code, campus_id NULL, created_at/by, updated_at/by)
        status: 0 下架 / 1 发布 / 2 草稿
        索引：status / category_id / course_type_code / campus_id
course_teachers(course_id, teacher_id)  复合 PK；索引 teacher_id
course_chapters(id, course_id, title, description, file, duration DECIMAL(10,2),
                teacher_id, sort_order, created_at, updated_at)  索引 course_id
```

**announcements**

```text
id PK；title VARCHAR(200)；content MEDIUMTEXT；status TINYINT DEFAULT 0
top TINYINT DEFAULT 0；created_at；created_user；published_at；campus_id NULL
索引：(status, top, created_at) / campus_id
```

**question_categories / questions**

```text
question_categories(id, name, parent_id, sort_order, status, created_at, updated_at)  索引 parent_id
questions(id, type VARCHAR(20), title TEXT, options VARCHAR(4000), answer VARCHAR(4000),
          explanation TEXT NULL, status TINYINT DEFAULT 1, category_id, parent_id,
          sort_order, score INT DEFAULT 1, created_at, updated_at)
          type: single/multiple/true_false/fill/qa/group
          索引：parent_id / category_id / (type,status,parent_id)
```

**exams / exam_sections / exam_section_questions / exam_attempts / exam_answers**

```text
exams(id, title, code, exam_time, duration, status TINYINT DEFAULT 1, is_mock,
      created_by, pass_score INT DEFAULT 60, published_at, created_at, updated_at, campus_id NULL)
      status: 0 草稿 / 1 发布 / 2 撤回
      索引：code / is_mock / (created_by,status,is_mock) / campus_id
exam_sections(id, exam_id, type, description, sort_order)  索引 exam_id
exam_section_questions(id, exam_section_id, question_id, sort_order)
      索引：exam_section_id / question_id
exam_attempts(id, user_id, exam_id, start_time, end_time, status, submitted_at,
              total_score, created_at, updated_at, campus_id NULL)
              status: 0 进行中 / 1 已交卷
              索引：exam_id / (user_id,exam_id) / campus_id
exam_answers(id, attempt_id, question_id, answer, is_correct, score, updated_at)
      索引：(attempt_id, question_id)
```

**files / file_uploads / file_upload_parts**

```text
files(id VARCHAR(36) PK, name, mime_type, size, md5, status, storage_path,
      created_by, created_at, updated_at)  索引 md5
file_uploads(id VARCHAR(36) PK, name, mime_type, expected_size, md5, provider VARCHAR(16),
             status, created_by, created_at, updated_at)  索引 (status,updated_at)
file_upload_parts(id PK, upload_id, part_number, size, etag, storage_path, created_at)
      索引：(upload_id,part_number)
```

**learning_progress / course_notes / note_likes**

```text
learning_progress(id, course_id, chapter_id, user_id, progress DECIMAL(7,4),
                  created_at, updated_at, campus_id NULL)
                  索引 user_id / (course_id,user_id) / campus_id
course_notes(id, course_id, user_id, comment TEXT, created_time, attachments TEXT,
             parent_id, like_count)  索引 (course_id,created_time) / user_id
note_likes(id, comment_id, user_id, created_at)  索引 comment_id / user_id
```

**course_watch_progress / course_watch_sessions**

```text
course_watch_progress(id, user_id, course_id, chapter_id, first_watched_at, last_watched_at,
   last_position_seconds, video_duration_seconds, watched_seconds, completed,
   last_report_sequence, created_at, updated_at, campus_id NULL)
   索引：(user_id,course_id,chapter_id) / (user_id,updated_at) / (course_id,updated_at) /
        (course_id,completed,updated_at) / campus_id
course_watch_sessions(id, user_id, course_id, chapter_id, client_session_id,
   started_at, last_reported_at, ended_at NULL, start_position_seconds, last_position_seconds,
   watched_seconds, last_sequence, status, created_at, updated_at, campus_id NULL)
   status: 0 进行中 / 1 结束 / 2 超时
   索引：(user_id,client_session_id) / (user_id,last_reported_at) / campus_id
```

**question_records / question_first_answers / question_retry_attempts / question_retry_answers**

```text
question_records(id, user_id, question_id, answer, is_correct, answered, created_at, updated_at)
   索引：(user_id,answered) / (user_id,question_id) / question_id
question_first_answers(id, user_id, question_id, answer, is_correct, answered_at)
   索引：(user_id,question_id) / (user_id,is_correct)
question_retry_attempts(id, user_id, status, question_count, started_at, completed_at NULL)
   索引：(user_id,started_at)
question_retry_answers(id, attempt_id, user_id, question_id, answer, is_correct, answered_at)
   索引：(attempt_id,question_id) / (user_id,question_id)
```

**dictionary_types / dictionary_items**

```text
dictionary_types(id, code VARCHAR(64), name, description, status, sort_order, built_in,
                 created_by, updated_by, created_at, updated_at)
                 索引 code / (status,sort_order,id)
dictionary_items(id, type_id, code VARCHAR(64), name, description, status, sort_order,
                 built_in, created_by, updated_by, created_at, updated_at)
                 索引 (type_id,code) / (type_id,status,sort_order,id)
```

### 4.5 迁移清单（已执行，不可修改）

| 版本 | 内容 |
| --- | --- |
| 0001 | 初始基线 29 表 |
| 0002 | courses.description 默认空；内置角色；course_type 字典 |
| 0003 | course_watch_progress / course_watch_sessions |
| 0004 | 内置内容类型字典 course_type(video)、question_type(六类) |
| 0005 | exams.pass_score / published_at + 索引 |
| 0006 | file_uploads / file_upload_parts |
| 0007 | question_first_answers / question_retry_attempts / question_retry_answers（回填首次作答） |
| 0008 | questions.explanation |
| 0009 | file_uploads.provider |
| 0010 | campuses / campus_members |
| 0011 | courses/announcements/exam_attempts/learning_progress/course_watch_progress/course_watch_sessions 增加 campus_id |
| 0012 | 移除 teacher 角色及其关联 |

### 4.6 job_manager → 现有库表 映射

| job_manager 字段 | 现有库表落点 | 说明 |
| --- | --- | --- |
| `users.user_type` | `user_roles` + `roles.code` | super_admin/admin/student 映射角色 |
| `users.role`（字符串） | `user_roles` → `roles.name` | 管理员角色 |
| `users.campus_id` | `campus_members`（`is_primary=1`） | 主校区即数据范围依据 |
| `users.created_by` | `users.created_by` | 学员归属 |
| `users.is_active` | `users.status`（1/0） | 启停 |
| `users.is_deleted` | 硬删除 + 关联清理 | 现有库无软删列；行为等价 |
| `users.password_plain` | **不落库** | 改为重置密码 |
| `roles.name` | `roles.name` | 角色 |
| `campuses.*` | `campuses.*` | 校区 |
| `dict_types/dict_items` | `dictionary_types/dictionary_items` | 字典 |
| `operation_logs` | `login_logs` + 业务日志 | 操作审计 |
| 布尔权限字段 | `role_permissions` | 权限矩阵 |

---

## 5. 加密与验证机制

### 5.1 密码存储与校验

| 项 | 规则 |
| --- | --- |
| 算法 | Argon2id（Rust 端 `Argon2::default()`：v19，m=19456 KiB，t=2，p=1） |
| 哈希格式 | `$argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>`，存 `users.password_hash` |
| 兼容校验 | 以 `$argon2` 开头 → Argon2 校验；以 `$2` 开头 → bcrypt 校验 |
| 自动升级 | bcrypt 校验通过后，用 Argon2 重新哈希并更新，同时 `session_epoch + 1` |
| 强度校验（注册） | 8–128 位，须含大写、小写、数字、特殊字符 |
| 长度校验（后台创建） | 8–20 位 |
| 明文 | **绝不落库、不返回、不写日志** |

```python
# 伪代码
def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$argon2"):
        return argon2_hasher.verify(stored, password)  # 按哈希内参数
    if stored.startswith("$2"):
        return bcrypt.checkpw(password.encode(), stored.encode())
    return False
```

### 5.2 会话令牌

| 项 | 规则 |
| --- | --- |
| 生成 | 32 随机字节 → URL-safe Base64（无填充），约 43 字符 |
| 存储 | 仅存 `sha256(原始令牌)` 十六进制（64 字符）到 `auth_sessions.token_hash` 主键 |
| Cookie 名 | `edu_session` |
| Cookie 属性 | `HttpOnly`、`SameSite=Lax`、`Path=/`、`Secure`（生产 true）、`Max-Age=604800` |
| 校验 | cookie 原始值 → sha256 → 查 `auth_sessions`；校验 `users.status=1`、`session_epoch` 一致、`expires_at > now` |
| 续期 | 每次访问更新 `last_seen_at`；过期或不合法即删除会话并返回 401 |

### 5.3 CSRF 防护

| 项 | 规则 |
| --- | --- |
| Cookie 名 | `XSRF-TOKEN`（**非 HttpOnly**，供前端读取） |
| 值 | 每次登录生成随机 `secrets.token_urlsafe(32)`，存 `auth_sessions.csrf_token` |
| 提交 | 写请求头 `x-csrf-token` 或 `x-xsrf-token` |
| 校验 | 与 `session.csrf_token` 做**常量时间比较**（`hmac.compare_digest`），失败 403 |
| 作用范围 | 非 `GET/HEAD/OPTIONS` 的请求 |

前端 Axios 拦截器从 `XSRF-TOKEN` cookie 读取并写入请求头。

### 5.4 会话失效（session_epoch）

以下任一变更使目标用户的 `users.session_epoch + 1`，旧会话下一次请求即失效：

1. 用户角色变更（`user_roles` 替换）。
2. 角色权限变更（`role_permissions` 替换）。
3. 密码重置或修改。
4. 用户状态启停。
5. 直属上级（`manager_id`）变更。
6. 校区成员关系增删改。

### 5.5 登录限流

| 项 | 规则 |
| --- | --- |
| 限流键 | `throttle_key = sha256(f"{client_ip}|{identity.lower()}")` 十六进制 |
| 存储 | `login_throttles.failure_count`、`locked_until`（Unix 秒） |
| 阈值 | `LOGIN_MAX_FAILURES=5` |
| 锁定 | `LOGIN_LOCKOUT_SECONDS=900`（15 分钟） |
| 成功 | 删除该键记录（清零） |
| 失败 | 写 `login_logs`（`success=0`, `failure_reason='invalid_credentials'`） |
| 并发 | 命名锁 `login_throttle:{key}` 串行化读写 |

### 5.6 传输与部署安全

- 生产启用 HTTPS/TLS；Nginx 80 → 443 跳转并启用 HSTS。
- FastAPI 仅监听 `127.0.0.1`，对外只经 Nginx。
- 反向代理传递 `X-Real-IP` / `X-Forwarded-For` / `X-Forwarded-Proto`，限流取真实 IP。
- 密钥、数据库密码仅存 `.env`，不入库、不入 Git。

### 5.7 其他安全约束

- 富文本（公告、课程详情）输出过滤，防 XSS。
- 文件上传：类型白名单、大小限制、路径只取 basename、鉴权访问。
- 视频支持 Range 请求；云存储返回短时签名 URL。
- 统一响应错误不泄露内部细节；数据库异常只记录日志、对外返回 `internal_error`。
- 所有 `/api/admin/*` 统一鉴权兜底，未知资源默认 `console.system.manage`。

### 5.8 验证清单（验收）

| 项 | 验证方式 |
| --- | --- |
| 密码哈希 | 数据库中 `password_hash` 不以明文出现；Argon2 前缀 |
| bcrypt 兼容 | 用旧 bcrypt 账号登录成功且哈希被升级为 Argon2 |
| 会话令牌 | 数据库中只存 sha256；篡改 cookie 返回 401 |
| CSRF | 缺失/错误 CSRF 头的写请求返回 403 |
| 限流 | 连续 5 次错误后锁定并提示稍后重试 |
| 会话失效 | 角色/权限/密码/状态变更后旧 cookie 请求返回 401 |
| 越权 | 管理员访问非本校对象返回 403 |
| 学员提权 | 学员访问 `/api/admin/*` 返回 403 |

---

## 6. API 设计

统一 `/api` 前缀；响应信封 `{success, code, message, data}`。

错误码：`unauthorized`(401)、`login_failed`(401)、`forbidden`(403)、`validation_error`(422)、`conflict`(409)、`not_found`(404)、`login_rate_limited`(429)、`internal_error`(500)。

### 6.1 认证与个人

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/login` | 登录；5 次失败锁定 15 分钟 |
| POST | `/api/logout` | 登出 |
| GET | `/api/user/self` | 当前用户（类型/角色/权限/校区/数据范围） |
| PUT | `/api/user/profile` | 姓名/手机号/头像 |
| POST | `/api/user/change-password` | 修改密码 |

### 6.2 公开端

`/api/system/config`、`/api/course/`、`/api/course/{id}`、`/api/course/{id}/chapter/`、`/api/dictionaries/{code}/items`、`/api/announcements/`、`/api/announcements/{id}`。

### 6.3 学习

`/api/learning/overview`、`/api/learning/start`、`/api/learning/watch/start|progress|finish`、`/api/learning/progress`、`/api/course/{id}/notes...`。

### 6.4 题库

`/api/question-categories`、`/api/questions/random`、`/api/questions/answer`、`/api/questions/statistics`、`/api/questions/wrong`、`/api/questions/wrong/{id}`、`/api/questions/wrong/retry/start|answer`。

### 6.5 考试

`/api/exams/available`、`/api/exams/{id}/attempt`、`/api/exams/attempt`、`/api/exams/answers`、`/api/exams/submit`、`/api/exams/mock`、`/api/exams/statistics`、`/api/exams/history`、`/api/exams/result`。

### 6.6 控制台

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| GET | `/api/admin/dashboard` | dashboard.view |
| GET/POST/PUT/DELETE | `/api/admin/courses...` | courses.manage |
| GET/POST/PUT/DELETE | `/api/admin/questions...` | questions.manage |
| GET/POST/PUT/DELETE | `/api/admin/exams...` | exams.* |
| GET/POST/PUT/DELETE | `/api/admin/teachers...` | teachers.manage |
| GET/POST/PUT/DELETE | `/api/admin/campuses...` | campuses.manage（超管） |
| GET/POST/PUT/DELETE | `/api/admin/users...` | administrators.manage（超管） |
| GET/POST/PUT/DELETE | `/api/admin/students...` | students.manage |
| GET/POST/PUT/DELETE | `/api/admin/roles...` | roles.manage（超管） |
| GET/POST/PUT/DELETE | `/api/admin/announcements...` | announcements.manage |
| GET/PUT | `/api/admin/system/config` | system.manage |
| GET/POST/PUT/DELETE | `/api/admin/dictionary-types`、`/api/admin/dictionary-items` | dictionaries.manage |

控制台写接口通用规则：校验权限码；非超管叠加本校区；对象级写校验 `目标.campus_id == 操作者.campus_id`；删除支持 `verify_name`+`verify_phone`；批量删除返回 `{deleted_count, skipped_count, message}`。

---

## 7. 权限与数据隔离

### 7.1 权限码

```text
console.dashboard.view           总览
console.courses.manage           课程管理
console.questions.manage         题库管理
console.exams.manage             考试管理
console.teachers.manage          教师管理
console.campuses.manage          校区管理（超管）
console.administrators.manage    管理员管理（超管）
console.students.manage          学员管理
console.roles.manage             角色管理（超管）
console.announcements.manage     通知公告
console.system.manage            系统配置（超管）
console.dictionaries.manage      字典管理（超管）
learning.use                     学习功能
```

### 7.2 默认角色权限

| 模块 | 校长 | 班主任 |
| --- | :-: | :-: |
| 总览 | ✅ | ✅ |
| 课程管理 | ✅ | |
| 题库管理 | ✅ | |
| 考试管理 | ✅ | ✅ |
| 教师管理 | ✅ | |
| 学员管理 | ✅ | ✅ |
| 通知公告 | | |
| 校区/管理员/角色/系统/字典 | | |

### 7.3 数据隔离矩阵

| 功能 | 学员 | 班主任 | 校长 | 超管 |
| --- | :-: | :-: | :-: | :-: |
| 首页/课程/题库/考试/个人中心 | ✅ | ✅ | ✅ | ✅ |
| 控制台入口 | ❌ | ✅ | ✅ | ✅ |
| 总览 | ❌ | 本校 | 本校 | 全部 |
| 课程/题库/考试/教师 | ❌ | 按权限（本校） | 按权限（本校） | 全部 |
| 通知公告 | ❌ | 按权限 | 按权限 | ✅ |
| 校区/管理员/角色/系统/字典 | ❌ | ❌ | ❌ | ✅ |
| 学员管理 | ❌ | 名下 | 本校区 | ✅ |

### 7.4 数据范围谓词

```text
超管（all）    ：1=1
校长（tree）   ：本人 + created_by=本人 + manager_id 递归下级
班主任（direct）：本人 + manager_id=本人 + created_by=本人
学员（self）   ：id=本人
校区范围       ：与操作者共享启用校区（campus_members + campuses.status=1）
最终谓词       ：用户关系谓词 AND 校区谓词
```

---

## 8. 业务逻辑（处理流程）

> 本章描述各模块的详细处理逻辑、校验顺序与事务边界，作为编码依据。所有数据库写入必须显式指定字段与时间戳，不使用数据库默认行为承担业务。

### 8.1 通用约定

- **时间**：统一由应用生成 Unix 秒写入 `created_at`/`updated_at`。
- **分页**：`p`（默认 1，最小 1）、`page_size`（默认 20，仅允许 20/50/100）。返回 `{items, total, page, page_size}`。
- **列表排序**：默认 `id DESC` 或 `updated_at DESC`，按模块指定。
- **手机号脱敏**：`138****0000`（保留前 3 后 4）。
- **命名锁**：以下业务在 `SELECT GET_LOCK(name,10)` 保护下「检查 + 写入」：
  - `users:identity`（账号/邮箱/手机唯一）
  - `login_throttle:{key}`（登录限流）
  - `roles:codes`、`permissions:codes`（RBAC 编码唯一）
  - `campuses:codes`（校区编码/名称唯一）
  - `dictionary:codes`（字典编码唯一）
  - `sys_config:upsert`（配置写入）
  - `watch:{user_id}`（观看会话与进度）
  - `practice:{user_id}`（练习取题与领取）
  - `exams:code`（试卷编码）
  - `exam_attempt:{user_id}:{exam_id}`（考试开始）
  - `exam_save:{attempt_id}`（答案保存/交卷）
  - `note_like:{note_id}`（点赞计数）
- **事务**：涉及多表写入必须在同一事务内完成；删除父对象按「子表 → 父表」顺序显式清理。
- **rows_affected**：更新/删除后必须检查影响行数判断对象是否存在。

### 8.2 请求鉴权流程

```text
请求进入
 ├─ 路径以 /api/admin/ 开头？
 │   ├─ 是：
 │   │   1. 解析 edu_session Cookie
 │   │   2. 无会话 → 401 unauthorized
 │   │   3. 校验会话（status=1、session_epoch 一致、未过期）；失效 → 删除会话并 401
 │   │   4. 非 GET/HEAD/OPTIONS → 校验 CSRF 头；失败 → 403
 │   │   5. 解析资源 → 所需权限码集合；查询用户有效权限
 │   │   6. 无任一权限 → 403 forbidden
 │   │   7. 放行到 handler
 │   └─ 否：按路由自身要求处理（公开接口不校验）
 └─ handler 内二次校验角色/数据范围（防御纵深）
```

### 8.3 登录逻辑

```text
POST /api/login(username, password)
1. identity = username 去空格小写；为空 → 422
2. client_ip = 真实 IP（优先 X-Real-IP）；user_agent 截断 512
3. key = sha256(f"{client_ip}|{identity}")
4. named_lock("login_throttle:{key}"):
   a. 查 login_throttles：若 locked_until > now → 429（稍后重试）
   b. 查用户（username/email/mobile 任一匹配）
   c. 若用户存在且 status=1 → verify_password
      否则 → 用 dummy_hash 执行一次校验（恒定耗时，防时序侧信道）
   d. 失败或无用户：
        failure_count = (未锁定 ? +1 : 1)
        locked_until = (failure_count >= 5 ? now+900 : NULL)
        upsert login_throttles
        insert login_logs(success=0, failure_reason='invalid_credentials')
        → 401 login_failed
   e. 成功：
        删除 login_throttles（清零）
        bcrypt 旧哈希 → 升级 Argon2，session_epoch+1
        生成 raw_token(32B) 与 csrf_token
        insert login_logs(success=1)
        insert auth_sessions(token_hash=sha256(raw), csrf_token, expires_at=now+604800)
5. 设置 Cookie：edu_session(HttpOnly) + XSRF-TOKEN(非 HttpOnly)
6. 返回 UserData（角色/权限/数据范围/校区）
7. 前端跳转：管理员 → /admin/dashboard；学员 → /
```

### 8.4 用户/管理员/学员 CRUD 逻辑

**创建（超管创建管理员 / 管理员创建学员）**

```text
1. 校验操作者权限（administrators.manage 或 students.manage）
2. 校验手机号 11 位；唯一（named_lock users:identity 内查 username/mobile）
3. 学员额外：身份证 18 位且唯一；解析性别与出生日期
4. 密码规则：
   - 管理员：默认手机号后 6 位
   - 学员：默认身份证后 6 位
   - 或显式传入 8–20 位
5. campus_id 归属：
   - 超管：使用表单选定校区
   - 管理员：强制本人校区（忽略并覆盖请求值）
6. 事务：
   insert users(username=phone, password_hash, display_name, status=1, manager_id?, created_by=操作者)
   insert user_roles(默认角色：管理员=所选角色，学员=student)
   if 校区：insert campus_members(campus_id, user_id, member_type=角色, is_primary=1, status=1)
7. 返回用户详情
```

**更新**

```text
1. 校验权限
2. 加载目标（不存在 404）
3. 对象级校区校验：非超管时 目标.campus_id == 操作者.campus_id，否则 403「无权操作其他校区数据」
4. 更新字段（不允许直接改 username；改手机号需查重）
5. 若状态/角色/密码/上级发生变化 → session_epoch+1
```

**启用/禁用**

```text
1. 校验权限 + 对象校区
2. 若禁用的是超管且剩余启用超管 ≤ 1 → 409「必须保留至少一名超级管理员」
3. 不可禁用自己
4. update users.status；session_epoch+1
```

**删除**

```text
1. 校验权限 + 对象校区
2. 不可删除自己
3. 末位超管保护
4. 若目标仍管理下属（users.manager_id=目标）→ 409，要求先转移
5. 事务级联清理（按依赖顺序）：
   note_likes → course_notes → learning_progress → question_records →
   question_first_answers → question_retry_answers →
   exam_answers→exam_attempts → auth_sessions → campus_members →
   user_roles → users
6. 单个删除：请求需带 verify_name + verify_phone 与目标一致，否则拒绝
7. 批量删除：接收 ids[]；对无权限/自己的对象跳过；返回 {deleted_count, skipped_count}
```

**重置密码**

```text
1. 校验权限 + 对象校区
2. 不可重置自己（走个人中心）
3. 校验新密码 8–20 位
4. update password_hash, session_epoch+1（原子）
```

**Excel 导入**

```text
1. 校验权限；读取文件表头，逐行校验（手机号/身份证/必填）
2. 每行在事务内创建用户；已存在手机号 → 跳过并记录
3. 返回 {imported, skipped, errors:[{row, reason}]}
```

### 8.5 校区逻辑

```text
新增：名称非空且唯一（named_lock campuses:codes）；insert status=1
编辑：名称唯一（排除自身）；更新地址/负责人/联系方式/名称
启停（状态联动）：
   campus.status = 1 - campus.status
   事务内同步更新该校区的所有管理员与学员 users.status = campus.status
   session_epoch+1（被影响用户）
删除：
   单个/批量软删或硬删；删除前校验：
   - 若仍有成员 → 拒绝或要求先迁移（按确认策略）
   批量：对越权对象跳过
```

### 8.6 角色与权限逻辑

```text
角色：名称唯一；内置角色不可删除；删除前校验无用户使用
配置权限（替换式）：
1. 校验权限（roles.manage）
2. 校验角色存在且非 system_admin
3. 事务：delete role_permissions where role_id；批量 insert 新权限
4. 对该角色下所有用户 session_epoch+1
用户角色变更：
1. 至少一个角色
2. 若移除超管且导致启用超管 ≤ 1 → 403
3. 事务：delete user_roles；insert 新角色；session_epoch+1
```

### 8.7 课程逻辑

```text
创建/编辑：
1. 校验权限 + 对象校区
2. 课程类型必须为启用字典项（course_type）
3. 保存课程（新建默认 status=2 草稿；写 campus_id=操作者主校区）
4. 授课教师：校验存在后，delete course_teachers + 批量 insert
章节管理：
1. 上传视频得到 files.id 与时长（前端解析或服务端探测）
2. 新增/编辑/删除 course_chapters（标题、简介、排序、teacher_id、file、duration）
状态启停：
   status: 0 下架 / 1 发布 / 2 草稿；转 1 时写 published_at=now
删除：
   事务级联清理：note_likes → course_notes → learning_progress →
   course_watch_progress → course_watch_sessions → course_chapters →
   course_teachers → courses
```

### 8.8 视频观看逻辑（可信计时）

```text
常量：REPORT_INTERVAL=15s，MAX_SINGLE=30s，IDLE_TIMEOUT=300s，位置 95% / 时长 90% 判完成

watch/start(course, chapter, client_session_id)：
1. 校验章节属于 status=1 课程
2. named_lock watch:{user_id}：
   a. 关闭本人超过 300s 未上报的进行中会话（status=2）
   b. 同 client_session_id 已存在 → 复用
   c. 否则 insert course_watch_sessions；resume_seconds 取 course_watch_progress
3. 返回 {watch_session_id, resume_seconds, video_duration_seconds, completed, report_interval}

watch/progress(seq, position, duration, event)：
1. 校验会话属于本人、status=0
2. valid_duration(0<d<=86400)、valid_position(0<=p<=d+5)
3. 若 seq <= last_sequence → 幂等成功（不累计）
4. event=seek → 只更新位置，不累计
5. 否则 effective = min(now - last_reported_at, max(position-last_position,0), 30)
6. 更新会话与进度（watched_seconds 累加、last_sequence、last_position）
7. completed 单调置位；返回 {accepted, watched_seconds, completed}

watch/finish：做最后一次累计，status=1、ended_at=now

course_progress(course_id)：逐章进度 + 完成章节数/视频章节总数 + 完成比例 + 续播位置
```

### 8.9 题库练习逻辑

```text
取题（random，支持题型/练习类型多选）：
1. named_lock practice:{user_id}
2. 优先选「已领取未答」question_records.answered=0
3. 否则随机选未做过的题
4. 领取即写/更新 question_records（answered=0）
5. 返回题目（不含答案）

作答（answer）：
1. 校验题目存在且启用
2. 判分：多选=字母集合相等；单选/判断=去尾点小写；填空/问答=空白折叠小写
3. update question_records（answered=1, is_correct, answer）
4. 首次有效作答：insert question_first_answers（若不存在），作为进度与正确率唯一口径
5. 返回 {correct, correct_answer, explanation, stats, next_question}

统计：基于 question_first_answers 计算 总/已练/正确/错误/正确率/进度

错题列表：question_first_answers where is_correct=0（分页）
错题详情：题目 + 用户答案 + 正确答案

错题重练：
1. start：收集错题，insert question_retry_attempts(status=0)
2. answer：insert question_retry_answers（独立记录）
3. 全部作答 → attempts.status=1
4. 重练结果不写 question_first_answers，不影响正确率
```

### 8.10 考试逻辑

```text
组卷（创建试卷）：
1. 校验权限；题目分组（题型）+ 题目 id 列表
2. named_lock exams:code
3. 事务：insert exams → 逐分组 insert exam_sections → 校验题目题型匹配 → insert exam_section_questions
4. 分组不得为空；题目去重

状态：
   0 草稿 / 1 发布 / 2 撤回
   展示状态按时间推导：未开考 / 已开考 / 已结束
发布：须有题目；published_at=now
撤回：status=2
编辑：已有考试记录 → 409 不可改
删除：事务级联 exam_answers → exam_attempts → exam_section_questions → exam_sections → exams

开始考试：
1. 登录 + CSRF；考试已发布；now >= exam_time
2. 资格：学员 manager_id == 创建人 或 创建人为超管
3. 计算 end_time = now + duration*60
4. named_lock exam_attempt:{user}:{exam}：复用进行中 attempt，否则 insert
5. 返回题目（不含答案）与剩余时间

保存答案 / 交卷：
1. 校验 attempt 属于本人
2. named_lock exam_save:{attempt_id}
3. 逐题校验属于本试卷 → 判分 → upsert exam_answers
4. 未到时间：仅保存
5. 到时间或手动交卷：status=1、submitted_at、total_score=SUM(score)
6. 已交卷的重复提交返回既有分数（幂等）

模拟考试：
1. 读取 sys_config：auto_exam_* 优先，否则 mock_exam_*
2. 按题型比例（最大余数法）分配题数
3. 从启用题库按分类随机抽题
4. 事务：insert exams(is_mock=1) + 分组题目 + exam_attempts(status=0)
5. 返回 attempt 与题目

统计：不含模拟（is_mock=0）的已参加次数、平均分、合格次数
成绩：exam_attempts + exams 列表；结果详情含逐题正误与得分
```

### 8.11 文件上传逻辑

```text
单文件上传：
1. 校验 provider（local/oss/cos，云存储需已配置）
2. 校验大小 <= MAX_UPLOAD_SIZE_MB（默认 30）
3. 文件名取 basename 防路径穿越
4. 本地写 STORAGE_DIR/{uuid}；云端写 objects/{uuid}
5. insert files(status=1, md5)；DB 失败则删除已写对象

分片上传：
1. init：清理过期（>TTL 且 status=0）；md5+size 去重返回 exist；否则 insert file_uploads(status=0)
2. chunk：校验归属；写 staging/{id}/{part_number}；etag=分片 md5；替换 file_upload_parts
3. complete：校验分片序号 1..N 连续、etag 匹配、总大小一致；合并/流式写入；
   校验可选 md5；insert files(status=1)；标记 file_uploads.status=1；删除 staging

访问：
   /api/image 公开；/api/video、/api/file 需登录；仅 status=1
   本地支持 Range；云存储 302 到短时签名 URL
删除：被 courses.cover / description_image / course_chapters.file / teachers.avatar 引用时拒绝
```

### 8.12 公告逻辑

```text
状态：0 未发布 / 1 已发布；top 0/1 置顶
创建/编辑：标题与内容非空；状态合法
   → status 由非 1 变为 1 时写 published_at=now
发布/撤回、置顶/取消：切换字段并写操作日志
门户：公开列表强制 status=1；登录后弹窗取最新一条，会话内关闭一次
删除：硬删除
```

### 8.13 字典逻辑

```text
类型/字典项：
1. 编码规则 ^[a-z0-9_]{1,64}$；名称非空
2. 同类型内编码唯一（named_lock dictionary:codes）
3. 字典项 key 在类型内自增、排序可调
保护：
   - built_in 类型/项不可删除，可停用
   - 类型被业务引用（如 course_type）不可删除
   - 字典项被业务引用（如 courses.course_type_code）不可删除
业务下拉：仅返回 status=1 的字典项
```

### 8.14 首页与系统配置逻辑

```text
系统配置读写：
1. 读取：一次性查 sys_config 已知键，组装 camelCase 对象
2. 写入（system.manage + CSRF + 超管）：
   named_lock sys_config:upsert，事务内逐键 upsert，记录 created_by/updated_by
首页配置：
   - home_backgrounds：JSON 数组 [{url, sort, status}]，前台按 sort 轮播
   - friend_links：JSON 数组 [{name, url, sort, status}]，前台仅渲染 status=1
   - home_page_content / homepage_banner / Banner 列表
   - 未配置时前台显示默认内容或不显示该区块
```

### 8.15 会话失效触发点汇总

| 触发 | 递增对象 |
| --- | --- |
| 用户角色变更 | 目标用户 |
| 角色权限变更 | 该角色下所有用户 |
| 密码重置/修改 | 目标用户 |
| 用户状态启停 | 目标用户 |
| 直属上级变更 | 目标用户 |
| 校区成员增删改 | 目标用户 |
| 校区启停联动 | 该校区全部用户 |

### 8.16 删除与级联清理约定

- 不使用数据库外键；删除父对象时按依赖顺序显式清理子表。
- 清理必须放在同一事务，任一步失败整体回滚。
- 对仍被引用且不应删除的对象（如仍管理下属的用户、被引用的文件/字典项）返回 `409 conflict`。

---

## 9. 非功能需求

- 安全：见第 5 章。
- 兼容：直连现有库；接口路径与响应信封与旧系统一致。
- 性能：列表分页；视频 Range；Nginx 静态缓存；数据库索引覆盖高频查询。
- 可用性：骨架加载、空状态、错误重试、防重复提交；320px 起无横向溢出。
- 可维护性：迁移只追加、不修改；文档与代码同变更。
- 测试：后端单元/集成（pytest）；前端类型检查、Lint、构建；越权与会话失效用例。

---

## 10. 待确认事项

1. 明文密码：job_manager 列表展示明文；本方案不落库、改为「重置密码」，是否接受。
2. 软删除：是否新增 `is_deleted` 列以完全对齐（否则采用硬删 + 关联清理）。
3. 用户类型存储：用现有 RBAC 角色映射 `user_type`，是否接受。
4. `new` 标签：按发布时间阈值自动判定，还是后台手动。
5. 校区多归属：是否限制单校区。
6. 导入文件：管理员/学员 Excel 列定义与模板。
7. 权限模型：保留 job_manager 布尔权限，还是统一为角色权限矩阵。
8. 明文手机号展示：列表是否始终脱敏。

---

## 11. 实施阶段

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| 1 底座 | 骨架、模型、登录限流、会话/CSRF、RBAC 种子、权限中间件 | 登录 + 权限可运行 |
| 2 组织 | 校区、管理员、学员、角色、数据范围、导入导出 | 管理员仅见本校 |
| 3 内容 | 课程、章节、教师、字典、文件、公告 | 课程 CRUD + 章节 + 上传 |
| 4 学习 | 视频观看、续播、学习概览、笔记 | 断点续播 |
| 5 题库 | 题库、练习类型、练习、统计、错题重练 | 练习/错题闭环 |
| 6 考试 | 组卷、发布、考试、模拟、成绩 | 考试全流程 |
| 7 前端 | Vue 页面逐模块对齐、首页轮播/友情链接、个人中心、控制台 | 全站联调 |
| 8 上线 | Nginx + Gunicorn + systemd、现有库直连、回归验收 | 生产可用 |
