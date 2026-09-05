# 聘安途岗推系统 — 项目说明书

内部岗位信息管理平台。管理员在后台管理岗位、学员、账号，并把岗位推送给学员；学员登录后查看推送给自己的岗位及岗位详情。

---

## 一、技术栈

| 分类 | 技术 |
|------|------|
| 后端框架 | Python 3.8+ / Flask 3.0 |
| ORM | Flask-SQLAlchemy 3.1 / SQLAlchemy |
| 认证 | Flask-Login |
| 数据库 | MySQL 8（生产推荐）或 SQLite（开发） |
| 前端 | Bootstrap 5 + Bootstrap Icons + 原生 JS |
| 日期组件 | Laydate 5.0.9（CDN 引入） |
| Excel 导入 | openpyxl |
| 部署 | Gunicorn / Waitress |

---

## 二、功能模块

### 管理员端（/admin）
- **首页**：岗位数、学员数、推送数、今日推送统计 + 最近推送
- **岗位管理**：列表（分页/筛选）、新增/编辑/删除/批量删除/批量导入、岗位推送
- **学员管理**：列表（筛选/全选/批量删除/状态开关）、新增/编辑/删除、Excel 导入
- **管理员管理**：列表（筛选/状态开关/批量删除）、新增/编辑、导入
- **推送记录**：推送明细（含重复推送记录）
- **校区管理**：校区增删改、状态开关、关联人数
- **角色管理**：角色增删改、状态开关
- **操作日志**：全量操作留痕

### 学员端（/student）
- **我的岗位**：推送给自己的岗位，左侧卡片式列表 + 右侧详情
  - 无限滚动加载、城市/薪资/学历/公司规模筛选、关键字搜索
- **岗位详情**：职位信息、岗位标签、职位描述、工作地点
- **账号信息**：查看并修改个人资料（姓名/邮箱/性别/身份证/学历/专业等）

---

## 三、默认账号与角色

系统初始化自动创建 2 个超级管理员：

| 账号 | 密码 | 角色 |
|------|------|------|
| `admin1` | `admin123` | 超级管理员1 |
| `admin2` | `admin123` | 超级管理员2 |

默认校区：`默认校区`。
默认角色：`校长`、`老师`、`教务主管`、`招生主任`。

> 生产环境请在首次登录后立即修改密码（右上角账号 → 修改密码）。

---

## 四、目录结构

```
job_manager/
├── app/
│   ├── __init__.py          # 应用工厂、默认数据初始化
│   ├── config.py            # 配置（每类环境的 DB / SECRET_KEY）
│   ├── models.py            # 数据模型（Campus/Role/User/Job/PushRecord/OperationLog）
│   ├── permissions.py       # 权限装饰器、权限常量、CSRF、校区过滤
│   ├── auth/                # 登录/登出/改密/个人资料
│   ├── admin/               # 管理员端路由
│   ├── student/             # 学员端路由
│   └── templates/           # Jinja2 模板
├── uploads/                 # Excel/头像上传目录
├── deploy.sh                # 一键部署脚本（Linux systemd）
├── .env.example             # 环境变量模板
├── init_db.py               # MySQL 建库建表初始化脚本（支持环境变量）
├── schema.sql               # MySQL 数据库 DDL 脚本
├── run.py                   # 开发启动入口
├── requirements.txt         # Python 依赖
├── DEPLOY.md                # 部署文档（手动/Windows）
└── README.md                # 本说明书
```

---

## 五、端口与访问

- 默认端口：`5000`
- 管理端登录页：`http://<host>:5000/login`
- 管理员首页：`http://<host>:5000/admin/`
- 学员首页：`http://<host>:5000/student/`

登录后自动按角色跳转到对应首页。

---

## 六、部署说明

### 6.1 环境要求

- Python 3.8+
- pip
- MySQL 8（生产）或 SQLite（开发）
- Nginx（可选，反向代理）
- 内存 2GB+，硬盘 20GB+

### 6.2 获取代码并安装依赖

```bash
cd job_manager
pip install -r requirements.txt
```

### 6.3 配置环境变量

复制 `app/config.py` 中的配置，或通过环境变量覆盖：

```bash
# Linux / macOS
export SECRET_KEY='change-me-to-a-long-random-string'
export DATABASE_URL='mysql+pymysql://jobuser:yourpass@host/job?charset=utf8mb4'

# Windows
set SECRET_KEY=change-me-to-a-long-random-string
set DATABASE_URL=mysql+pymysql://jobuser:yourpass@host/job?charset=utf8mb4
```

> 若不设置 `DATABASE_URL`，默认连接 `app/config.py` 中内置的 MySQL 连接串。
> 若密码含特殊字符（`@ & / :` 等），连接串中必须做 URL 编码：`@`→`%40`、`&`→`%26`、`/`→`%2F`、`:`→`%3A`。

### 6.4 一键部署（推荐，TencentOS/CentOS8+/AlmaLinux/Rocky）

项目内置 `deploy.sh`，自动完成：装依赖 → 创建虚拟环境 → 初始化数据库（建库+建表+默认数据）→ 写 `.env` → 注册 systemd 服务 → 配置日志轮转 → 开放防火墙 → 启动 → 健康检查。

```bash
# 上传项目
scp -r job_manager 用户名@服务器IP:/opt/

# 执行一键部署（密码已内置在 config.py / init_db.py 时无需传 DB_PASSWORD）
ssh 用户名@服务器IP
cd /opt/job_manager
sudo bash deploy.sh
```

可用环境变量覆盖默认值（不传则用内置配置）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_USER` | job_CAIQABiAB | MySQL 用户 |
| `DB_PASSWORD` | （空，用内置） | MySQL 密码，传则覆盖 |
| `DB_HOST` / `DB_PORT` | 127.0.0.1 / 3306 | 数据库地址/端口 |
| `DB_NAME` | job | 库名 |
| `APP_PORT` | 5000 | 服务端口 |
| `SECRET_KEY` | 自动随机 | Flask 密钥 |
| `RUN_AS` | 当前用户 | 服务运行用户 |

示例（指定端口与密码覆盖）：
```bash
sudo DB_PASSWORD='你的密码' APP_PORT=80 bash deploy.sh
```

部署完成后默认账号：`admin1 / admin123`、`admin2 / admin123`。

### 6.5 手动部署

#### 数据库初始化

**方式一：SQLite（开发，零配置）**

不设置 `DATABASE_URL` 且将 config 改为 SQLite，或直接使用默认 MySQL；如需 SQLite：

```python
# config.py 中临时改为
SQLALCHEMY_DATABASE_URI = 'sqlite:///app/app.db'
```

应用启动时会自动建表并写入默认数据（`db.create_all()` + `_create_defaults()`）。

#### 方式二：MySQL（生产推荐）

1. 创建数据库与账号（注意库名默认为 `job`）：

```sql
CREATE DATABASE job CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'jobuser'@'localhost' IDENTIFIED BY 'yourpass';
GRANT ALL PRIVILEGES ON job.* TO 'jobuser'@'localhost';
FLUSH PRIVILEGES;
```

2. （可选）用 `schema.sql` 手动建表（须先 `USE job;`），或直接用脚本：

```bash
python init_db.py   # 会建库、建表并写入默认数据（支持环境变量 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME）
```

3. 启动应用时 Flask 会自动执行 `db.create_all()` 补齐缺失表并写入默认数据。

#### 启动应用

#### 开发环境

```bash
python run.py        # host=0.0.0.0, port=5000, debug=True
```

#### 生产环境

```bash
# Linux / macOS（Gunicorn）
gunicorn -w 4 -b 0.0.0.0:5000 run:app

# Windows（Waitress）
pip install waitress
waitress-serve --port=5000 --threads=4 run:app
```

### 6.7 Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 上传大小限制（与 config MAX_CONTENT_LENGTH 配套）
    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 6.8 数据导入

登录超管后：
- **岗位导入**：岗位管理 → 批量导入（上传 .xlsx）
- **学员导入**：学员管理 → 导入学员
- **管理员导入**：管理员管理 → 批量导入

根目录保留 `admins_import.xlsx`、`students_import.xlsx` 作为导入模板参考。

---

## 七、常见问题

**Q1：端口被占用**
```bash
netstat -ano | findstr :5000     # 找到 PID
taskkill /PID <PID> /F           # 结束进程
```

**Q2：数据库连接失败**
检查 `DATABASE_URL` 是否正确、MySQL 是否已启动、账号密码权限是否到位、库名是否为 `job`。

**Q3：上传失败**
确认 `uploads/` 目录存在并对 Python 进程可写。

**Q4：登录后看到"无权访问"**
确认账号角色正确；管理员(admin) 默认拥有"岗位管理/推送记录/操作日志"入口，其余功能受具体权限字段控制。

---

## 八、安全建议

1. 生产环境务必设置强 `SECRET_KEY`。
2. 首次登录立即修改默认管理员密码。
3. 配置 HTTPS（Nginx SSL）。
4. 定期备份数据库：
   - MySQL：`mysqldump -u jobuser -p job > backup.sql`
   - SQLite：备份 `app/app.db`
