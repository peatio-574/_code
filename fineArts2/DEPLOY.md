# FineArts2 报名管理系统 - 部署文档

本项目由 fineArts 复刻而来，**已移除证书管理与证书查询功能**，仅保留：

- 前台：考试报名（含机构专属报名链接 `/new/apply?i=<code>`）
- 后台：报名管理、机构管理、账号管理、修改密码

数据库使用全新的 `finearts2` 库，与现有 fineArts 数据完全隔离。

---

## 一、访问地址与路由

| 功能 | 路由 |
| --- | --- |
| 前台报名 | `/new/apply` |
| 后台登录 | `/new/manager/login` |
| 后台首页 | `/new/manager` |
| 静态资源 | `/new/static/...` |

本机默认端口：`5001`（现有 fineArts 一般为 `5000`）。

示例（Nginx 反向代理后）：

- 报名：`http://8.130.149.55/new/apply`
- 后台：`http://8.130.149.55/new/manager`

---

## 二、服务器信息

- 服务器：8.130.149.55
- SSH：`root / fineArts@900`
- 现有 fineArts：`/opt/fineArts`，端口 5000
- 新 fineArts2：`/opt/fineArts2`，端口 5001
- 数据库：`finearts2`（独立库、独立用户）

> 如果实际 fineArts 安装目录或端口不同，请按服务器现状调整 Nginx 与 systemd 配置。

---

## 三、本地启动（Windows）

```cmd
cd D:\_code\fineArts2
pip install -r requirements.txt
python init_db.py
python run.py
```

访问：

- 报名：http://127.0.0.1:5001/new/apply
- 后台：http://127.0.0.1:5001/new/manager
- 默认账号：`admin / Caa@Admin2026`

也可直接双击 `run.bat`。

---

## 四、全新数据库

`.env` 默认配置（数据库账号与 fineArts 一致：finearts / Finearts@2026）：

```ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=finearts
DB_PASSWORD=Finearts@2026
DB_NAME=finearts2

SECRET_KEY=caa-finearts2-signup-manager-secret-key-2026
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Caa@Admin2026
ROUTE_PREFIX=/new
```

创建独立数据库并授权给 finearts 账号：

```sql
CREATE DATABASE IF NOT EXISTS finearts2
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

GRANT ALL PRIVILEGES ON finearts2.* TO 'finearts'@'localhost';
GRANT ALL PRIVILEGES ON finearts2.* TO 'finearts'@'127.0.0.1';
FLUSH PRIVILEGES;
```

初始化表与默认管理员：

```bash
cd /opt/fineArts2
source venv/bin/activate
python init_db.py
```

程序启动时也会自动补建缺失的表和字段，但首次部署仍建议执行一次 `init_db.py`。

---

## 五、Linux 部署步骤

### 1. 上传项目

在本地 Windows 执行（把 `D:\_code\fineArts2` 上传到服务器）：

```powershell
scp -r D:\_code\fineArts2 root@8.130.149.55:/opt/fineArts2
```

或打包后上传：

```bash
tar -czf fineArts2.tar.gz fineArts2
scp fineArts2.tar.gz root@8.130.149.55:/opt/
# 服务器上
cd /opt && tar -xzf fineArts2.tar.gz
```

### 2. 安装依赖

```bash
cd /opt/fineArts2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 3. 创建数据库

按本文「四、全新数据库」执行 SQL，并检查 `.env`。

### 4. 初始化数据库

```bash
cd /opt/fineArts2
source venv/bin/activate
python init_db.py
```

### 5. systemd 服务

`/etc/systemd/system/finearts2.service`：

```ini
[Unit]
Description=FineArts2 Signup Manager
After=network.target mysql.service

[Service]
User=root
WorkingDirectory=/opt/fineArts2
Environment="PATH=/opt/fineArts2/venv/bin"
ExecStart=/opt/fineArts2/venv/bin/gunicorn -w 4 -b 127.0.0.1:5001 "app:create_app('production')"
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now finearts2
systemctl status finearts2
```

### 6. Nginx 反向代理

在现有站点 `server { ... }` 中增加以下 location（**不要改动原有 `/` 配置**，否则会影响 fineArts）：

```nginx
# fineArts2 静态资源（可选，性能更好）
location /new/static/ {
    alias /opt/fineArts2/app/static/;
    expires 30d;
}

# fineArts2 应用
location = /new {
    proxy_pass http://127.0.0.1:5001;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /new/ {
    proxy_pass http://127.0.0.1:5001;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

检查并重载：

```bash
nginx -t
systemctl reload nginx
```

> 注意：`location /new/` 必须放在原有 `location /` 之前或依赖 Nginx 最长前缀匹配；Nginx 会自动优先匹配更长的 `/new/`。

---

## 六、验证清单

```bash
curl -I http://127.0.0.1:5001/new/apply
curl -I http://127.0.0.1:5001/new/manager/login
curl -I http://8.130.149.55/new/apply
```

浏览器验证：

1. 打开 `/new/apply`，提交一条报名。
2. 打开 `/new/manager`，使用 `admin / Caa@Admin2026` 登录。
3. 在「报名管理」中应能看到刚提交的数据。
4. 在「机构管理」新建机构，复制生成的报名链接，确认链接为 `/new/apply?i=...`。

---

## 七、与 fineArts 的隔离说明

| 项目 | fineArts | fineArts2 |
| --- | --- | --- |
| 目录 | `/opt/fineArts` | `/opt/fineArts2` |
| 端口 | 5000 | 5001 |
| 数据库 | `finearts` | `finearts2` |
| 前台路由 | `/`、`/index.html`、`/baoming` | `/new/apply` |
| 后台路由 | `/admin` | `/new/manager` |
| 静态资源 | `/static/` | `/new/static/` |

两台应用可同时运行，互不影响。

---

## 八、数据备份

```bash
mysqldump -u finearts2 -p finearts2 > /backup/finearts2_$(date +%Y%m%d).sql
```

---

## 九、常见问题

**Q1：访问 `/new/apply` 出现 404**

- 检查 `systemctl status finearts2` 是否运行。
- 检查 Nginx 是否配置 `location /new/` 并已 reload。
- 检查 `.env` 中 `ROUTE_PREFIX=/new`。

**Q2：静态资源 404**

- 确认 Flask 的静态资源路径为 `/new/static/`。
- 若使用 Nginx `alias`，确认 `/opt/fineArts2/app/static/` 存在。

**Q3：数据库连接失败**

- 确认 MySQL 已启动，`finearts2` 用户可从 `127.0.0.1` 登录。
- 确认 `.env` 中库名、用户名、密码正确。

**Q4：报名链接中的机构编码无效**

- 机构链接由后台「机构管理」生成，格式为 `/new/apply?i=<code>`。
- 机构过期后链接会自动失效，可在后台修改有效期。

**Q5：修改代码后前端未更新**

- 静态资源 URL 带文件修改时间版本号，正常刷新即可；必要时 `Ctrl+F5` 强刷。
