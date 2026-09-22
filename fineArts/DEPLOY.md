# 中国美术学院社会美术水平考级证书查询系统 - 部署文档



阿里云服务器续费地址：https://ecs.console.aliyun.com/home
服务器：8.130.149.65
账号密码：root/Root1234

数据库：finearts    3306端口
账号 finearts / Finearts@2026

前端地址：
http://kjzxcaaedu.cn/index.html

后端地址：
http://kjzxcaaedu.cn/admin

网站登录账号
admin / Caa@Admin2026




## 一、系统概述

证书查询系统，含前台查询与后台管理。

- **前台**：证书查询（姓名 + 证件号/证书编号，中文算术图片验证码）、证书详情、首页跳转
- **后台**：证书管理（列表/搜索/分页/批量删除/勾选导出）、新增、编辑（弹窗）、导入、模板下载、修改密码

默认账号：`admin / admin123`（可在 `.env` 中修改）

---

## 二、环境要求

- 操作系统：Linux（推荐）/ Windows
- Python 3.8+
- MySQL 5.6+
- （生产推荐）Nginx 反向代理

---

## 三、项目结构

```
fineArts/
├── app/
│   ├── __init__.py          # create_app 应用工厂
│   ├── config.py            # 配置（读取 .env）
│   ├── models.py            # 数据模型（db / Admin / Certificate）
│   ├── api.py               # 统一 JSON 响应
│   ├── captcha.py           # 中文算术验证码
│   ├── excel_utils.py       # Excel 模板生成与导入解析
│   ├── public/              # 前台蓝图
│   ├── admin/               # 后台蓝图
│   ├── templates/           # HTML 模板
│   └── static/              # 静态资源
├── .env                     # 数据库/密钥（不入库）
├── .env.example             # 配置示例
├── requirements.txt
├── run.py                   # 启动入口
├── init_db.py               # 初始化数据库/表/管理员
├── seed.py                  # 写入一条示例证书（可选）
├── generate_data.py         # 生成测试数据（可选）
└── DEPLOY.md
```

---

## 四、部署步骤（Linux）

### 1. 安装依赖
```bash
sudo yum install python3 python3-pip mysql-server nginx   # CentOS
# 或 sudo apt install python3 python3-pip mysql-server nginx

cd /opt/fineArts
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 2. 创建数据库与配置
```bash
mysql -u root -p
CREATE DATABASE finearts DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER 'finearts'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON finearts.* TO 'finearts'@'localhost';
FLUSH PRIVILEGES;
```

复制并编辑 `.env`：
```ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=finearts
DB_PASSWORD=your_password
DB_NAME=finearts
SECRET_KEY=请改成随机字符串
ADMIN_USERNAME=admin
ADMIN_PASSWORD=改成强密码
```

> 数据库不存在时程序也会自动创建（`ensure_mysql_database`）。

### 3. 初始化数据库
```bash
python init_db.py
```

### 4. 启动（生产：Gunicorn）
```bash
gunicorn -w 4 -b 127.0.0.1:5000 "app:create_app('production')"
```

### 5. 配置 systemd 服务
`/etc/systemd/system/finearts.service`：
```ini
[Unit]
Description=FineArts Certificate Query
After=network.target mysql.service

[Service]
User=www-data
WorkingDirectory=/opt/fineArts
Environment="PATH=/opt/fineArts/venv/bin"
ExecStart=/opt/fineArts/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 "app:create_app('production')"
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now finearts
```

### 6. Nginx 反向代理
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /static/ {
        alias /opt/fineArts/app/static/;
        expires 30d;
    }
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 五、部署步骤（Windows）

```cmd
cd D:\fineArts
pip install -r requirements.txt
pip install waitress
python init_db.py
waitress-serve --port=5000 --threads=8 "app:create_app('production')"
```
也可直接双击 `run.bat`（`run.py` 使用 Flask 自带服务器，适合内网/小规模）。

用 NSSM 注册为服务：
```cmd
nssm install FineArts "D:\Python38\python.exe" "D:\fineArts\run.py"
nssm start FineArts
```

---

## 六、安全建议

1. 修改 `.env` 中的 `SECRET_KEY` 与管理员密码（`ADMIN_PASSWORD` 仅首次初始化生效，之后请在后台「修改密码」）。
2. 生产环境不要用 `run.py`（其 `debug=True`），应使用 gunicorn/waitress。
3. 建议开启 HTTPS，并对 `/admin` 做访问限制。
4. 当前后台写操作未启用 CSRF Token，若暴露公网建议在 Nginx 层做访问控制或后续补充 CSRF。

---

## 七、数据备份

```bash
mysqldump -u finearts -p finearts > /backup/finearts_$(date +%Y%m%d).sql
```

---

## 八、常见问题

**Q1: 数据库连接失败** — 检查 `.env` 的 `DB_*` 配置与 MySQL 是否启动。

**Q2: 端口被占用**
```bash
netstat -ano | findstr :5000
taskkill /PID <进程ID> /F
```

**Q3: 静态资源更新不生效** — 静态资源带版本号（`?v=文件修改时间`），改动文件后 `Ctrl+F5` 强刷即可。

**Q4: 验证码看不清** — 验证码为中文单数字算术（如 `4 加 五 = ?`），字体优先使用系统中文字体（微软雅黑/黑体/宋体）。
