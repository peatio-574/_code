# 聘书云课堂（Python + Vue 重写版）

视频课程学习、题库练习、仿真冲刺考试平台。后端 FastAPI + SQLAlchemy + MySQL 8，前端 Vue3 + Vite + Element Plus，Nginx 托管静态资源并反向代理 `/api`。

> 数据库沿用服务器现有 `education` 库表，不重建；本地开发完成后生产环境直接读取既有库表。
> 需求与设计见 [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md)。

## 目录结构

```text
edu/
├─ backend/                    FastAPI 服务
│  ├─ app/
│  │  ├─ main.py               应用与路由注册
│  │  ├─ config.py             配置（pydantic-settings）
│  │  ├─ db.py                 引擎/会话/命名锁/迁移
│  │  ├─ models.py             SQLAlchemy 模型
│  │  ├─ security.py           密码/会话/CSRF
│  │  ├─ error.py response.py  统一错误与响应信封
│  │  ├─ admin_guard.py        /api/admin 权限映射
│  │  ├─ seed.py               RBAC 种子
│  │  ├─ domain/               rbac / data_scope / campus / watch
│  │  └─ api/                  各业务路由
│  ├─ migrations/              与现有一致的 SQL 迁移（只读对账）
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/                   Vue3 应用
│  ├─ src/
│  │  ├─ api/                  接口封装
│  │  ├─ layouts/              门户/控制台布局
│  │  ├─ router/               路由与守卫
│  │  ├─ stores/               Pinia
│  │  ├─ lib/                  axios 与权限工具
│  │  └─ views/                门户页与 admin 控制台页
│  └─ vite.config.ts
├─ deploy/nginx.edu.conf       本地 Nginx 配置
├─ start-all.bat               一键启动后端(8000) + Nginx(8081)
└─ stop-all.bat                一键停止全部服务
```

## 一、环境准备

### 后端

```powershell
cd D:\_code\edu\backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` 关键配置：

```text
DATABASE_URL=mysql+pymysql://root:root123@127.0.0.1:3306/education
HOST=127.0.0.1
PORT=8000
```

启动即自动建库（缺失时）、执行迁移对账（与旧库兼容）并幂等写入 RBAC 种子。

### 前端

```powershell
cd D:\_code\edu\frontend
npm ci
npm run build
```

## 二、启动与停止

一键脚本位于项目根目录 `D:\_code\edu`：

| 脚本 | 作用 |
| --- | --- |
| `start-all.bat` | 启动后端(8000) + Nginx(8081)，访问 http://localhost:8081 |
| `stop-all.bat` | 停止 Nginx、后端(8000) 与前端开发服务器(3000) |

使用步骤：

1. 首次先构建前端（`cd frontend && npm run build`）。
2. 双击 `start-all.bat`，等待后端就绪后自动启动 Nginx。
3. 访问 http://localhost:8081。
4. 需要停止时双击 `stop-all.bat`。

> - 前端改动后需重新执行 `npm run build`，Nginx 才会提供最新页面。
> - 端口说明：旧 Rust 后端占用 8080，因此本配置使用 8081。如需 8080，先停止旧后端进程，再把 `deploy/nginx.edu.conf` 的 `listen` 改为 8080。
> - 脚本以 GBK 编码保存，避免中文 Windows 下 cmd 解析乱码。

如需单独调试前端（热更新），可在后端运行后执行：

```powershell
cd D:\_code\edu\frontend
npm run dev
```

访问 http://localhost:3000，`/api` 由 Vite 代理到 127.0.0.1:8000。

## 三、默认账号


| 账号 | 密码 | 角色 |
| --- | --- | --- |
| test_system_admin | Test123! | 超级管理员 |
| test_principal | Test123! | 校长 |
| test_homeroom_teacher | Test123! | 班主任 |
| test_student | Test123! | 学员 |

登录限流：同一「IP+账号」连续失败 5 次锁定 15 分钟。

## 四、主要接口

- 认证：`POST /api/login`、`POST /api/logout`、`GET /api/user/self`、`PUT /api/user/profile`、`POST /api/user/change-password`
- 门户：`GET /api/system/config`、`/api/course/`、`/api/course/{id}`、`/api/question-categories`、`/api/announcements/`
- 学习：`/api/learning/overview`、`/api/learning/watch/*`
- 题库：`/api/questions/*`
- 考试：`/api/exams/*`
- 控制台：`/api/admin/*`（权限码 + 校区范围校验）

统一响应信封：`{ "success": true, "code": "0000", "message": "", "data": {} }`

## 五、权限模型

- 超级管理员：全部页面与数据。
- 管理员（校长/班主任）：可进入控制台，只能看到本校区的数据。
- 学员：看不到控制台入口，直接访问返回 403。

权限码与数据范围（`self/direct/tree/all`）+ 校区范围共同决定可见数据。前端菜单隐藏不替代后端鉴权。

## 六、数据库

沿用现有库表结构（本项目本地默认连接服务器拷贝过来的 `education_rust` 库；如需切换，修改 `backend/.env` 的 `DATABASE_URL` 即可）。迁移文件位于 `backend/migrations/`，与既有 SQL 一致；启动时若检测到库已由旧 SQLx 迁移，会跳过已应用版本，避免重复执行。
