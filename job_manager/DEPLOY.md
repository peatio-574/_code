# 岗位管理系统 - 部署文档

## 一、系统概述

内部岗位信息管理+学员查看推送岗位Web系统，包含管理员后台和学员前端两套系统。

### 功能模块
- **管理员端**：岗位管理、学员管理、账号管理、推送管理、操作日志
- **学员端**：查看推送岗位、岗位详情

### 默认账号
- 管理员：admin / admin123

---

## 二、环境要求

### 服务器配置
- **操作系统**：Linux (CentOS 7+/Ubuntu 18.04+) 或 Windows Server
- **Python版本**：3.8+
- **内存**：2GB+
- **硬盘**：20GB+

### 必需软件
- Python 3.8+
- pip (Python包管理器)
- Nginx (推荐用于反向代理)
- MySQL (生产环境推荐) 或 SQLite (开发环境)

---

## 三、部署步骤

### 1. 上传项目文件
```bash
# 将 job_manager 目录上传到服务器
scp -r job_manager user@server:/opt/
```

### 2. 安装Python依赖
```bash
cd /opt/job_manager
pip3 install -r requirements.txt
```

### 3. 配置数据库

#### 方式一：使用SQLite（适合小规模）
无需额外配置，系统会自动创建 `app.db` 文件。

#### 方式二：使用MySQL（推荐生产环境）
```bash
# 安装MySQL
sudo yum install mysql-server  # CentOS
sudo apt install mysql-server  # Ubuntu

# 创建数据库
mysql -u root -p
CREATE DATABASE job_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'jobuser'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON job_manager.* TO 'jobuser'@'localhost';
FLUSH PRIVILEGES;
```

修改 `app/config.py` 中的数据库连接：
```python
SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://jobuser:your_password@localhost/job_manager?charset=utf8mb4'
```

### 4. 配置环境变量
创建 `.env` 文件：
```bash
SECRET_KEY=your-secret-key-here
DATABASE_URL=mysql+pymysql://jobuser:your_password@localhost/job_manager?charset=utf8mb4
```

### 5. 启动应用

#### 开发环境
```bash
python run.py
```

#### 生产环境（使用Gunicorn）
```bash
# Linux/Mac
gunicorn -w 4 -b 0.0.0.0:5000 run:app

# Windows (使用waitress)
pip install waitress
waitress-serve --port=5000 run:app
```

### 6. 配置Nginx反向代理
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /opt/job_manager/app/static;
        expires 30d;
    }
}
```

---

## 四、Windows服务器部署

### 1. 安装Python
从官网下载Python 3.8+并安装，勾选"Add Python to PATH"。

### 2. 安装依赖
```cmd
cd D:\job_manager
pip install -r requirements.txt
pip install waitress
```

### 3. 启动服务
```cmd
waitress-serve --port=5000 --threads=4 run:app
```

### 4. 配置为Windows服务（可选）
使用 NSSM (Non-Sucking Service Manager) 将应用注册为系统服务：
```cmd
nssm install JobManager "D:\Python311\python.exe" "D:\job_manager\run.py"
nssm start JobManager
```

---

## 五、安全配置

### 1. 修改默认密码
首次登录后立即修改管理员密码。

### 2. 配置HTTPS
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # ... 其他配置
}
```

### 3. 防火墙配置
```bash
# 开放80和443端口
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## 六、数据备份

### 定期备份SQLite
```bash
# 创建备份脚本
#!/bin/bash
DATE=$(date +%Y%m%d)
cp /opt/job_manager/app/app.db /backup/job_manager_$DATE.db
```

### MySQL备份
```bash
mysqldump -u jobuser -p job_manager > /backup/job_manager_$(date +%Y%m%d).sql
```

---

## 七、常见问题

### Q1: 端口被占用
```bash
# 查找占用端口的进程
netstat -ano | findstr :5000
# 杀掉进程
taskkill /PID <进程ID> /F
```

### Q2: 权限不足
确保Python进程对 `uploads/` 目录有读写权限。

### Q3: 数据库连接失败
检查 `config.py` 中的数据库连接配置是否正确。

---

## 八、项目结构

```
job_manager/
├── app/
│   ├── __init__.py          # 应用初始化
│   ├── config.py            # 配置文件
│   ├── models.py            # 数据模型
│   ├── auth/                # 认证模块
│   ├── admin/               # 管理员模块
│   ├── student/             # 学员模块
│   └── templates/           # HTML模板
├── uploads/                 # 上传文件目录
├── requirements.txt         # 依赖列表
├── run.py                   # 启动入口
└── DEPLOY.md                # 部署文档
```

---

## 九、技术支持

如遇到部署问题，请检查：
1. Python版本是否为3.8+
2. 依赖是否完整安装
3. 端口是否被占用
4. 数据库连接是否正常
5. 文件权限是否正确
