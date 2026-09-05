#!/usr/bin/env bash
# ============================================================
# 聘安途岗推系统 - 一键部署脚本 (TencentOS/CentOS8+ / AlmaLinux / Rocky)
# 功能：装依赖 -> 建表 -> 注册systemd服务 -> 日志轮转 -> 防火墙 -> 校验
# 用法：sudo bash deploy.sh
# 可通过环境变量覆盖默认值：
#   DB_USER   DB_PASSWORD   DB_NAME   APP_PORT   SECRET_KEY   RUN_AS
# ============================================================
set -e

# --------------------- 配置区（可用环境变量覆盖）---------------------
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-job_CAIQABiAB}"
# 密码默认留空：脚本会用 init_db.py 内置的密码建库；如需覆盖请传：
#   sudo DB_PASSWORD='你的密码' bash deploy.sh
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-job}"
APP_PORT="${APP_PORT:-5000}"
SECRET_KEY="${SECRET_KEY:-$(cat /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 48)}"
RUN_AS="${RUN_AS:-$(whoami)}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/venv"

# --------------------- 颜色输出 ---------------------
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# 必须 root
if [ "$EUID" -ne 0 ]; then
  error "请使用 root 运行： sudo bash deploy.sh"
  exit 1
fi

echo -e "${GREEN}============================================================${NC}"
info "聘安途岗推系统 部署开始"
info "项目目录 : $APP_DIR"
info "数据库   : $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
info "端口     : $APP_PORT"
info "运行用户 : $RUN_AS"
echo -e "${GREEN}============================================================${NC}"

# --------------------- 1. 安装系统依赖 ---------------------
info "[1/8] 检查并安装系统依赖 (gcc, python-devel)"
if ! command -v dnf >/dev/null 2>&1; then
  warn "未找到 dnf，尝试 yum"
  PM="yum"
else
  PM="dnf"
fi
$PM install -y gcc python3-devel which >/dev/null 2>&1 || \
  warn "部分系统依赖安装失败，继续（venv 可用即可）"

# --------------------- 2. 创建虚拟环境 + 装依赖 ---------------------
info "[2/8] 创建虚拟环境并安装 Python 依赖"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip -q
pip install -r "$APP_DIR/requirements.txt" -q
info "依赖安装完成"

# --------------------- 3. 初始化数据库 ---------------------
info "[3/8] 初始化数据库（建库+建表+默认数据）"
# 仅当显式传入 DB_PASSWORD 时才覆盖，否则让 init_db.py 用内置默认密码
export DB_HOST DB_PORT DB_USER DB_NAME
if [ -n "$DB_PASSWORD" ]; then
  export DB_PASSWORD
else
  unset DB_PASSWORD
fi
python "$APP_DIR/init_db.py" || {
  error "初始化数据库失败，请检查 init_db.py 中的账号密码"
  exit 1
}

# --------------------- 4. 准备日志目录 ---------------------
info "[4/8] 创建日志目录"
mkdir -p "$APP_DIR/logs"
chown -R "$RUN_AS":"$RUN_AS" "$APP_DIR/logs" 2>/dev/null || true

# --------------------- 5. 写入 .env ---------------------
info "[5/8] 写入环境变量文件 (.env)"
if [ -n "$DB_PASSWORD" ]; then
  # 对密码做 URL 编码（@ -> %40, & -> %26 等），避免解析出错
  if command -v python3 >/dev/null 2>&1; then
    ENC_PASS=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$DB_PASSWORD")
  else
    ENC_PASS="$DB_PASSWORD"
  fi
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$SECRET_KEY
DATABASE_URL=mysql+pymysql://$DB_USER:$ENC_PASS@$DB_HOST:$DB_PORT/$DB_NAME?charset=utf8mb4
EOF
else
  # 未传密码：DATABASE_URL 留空，让应用使用 app/config.py 内置的连接串
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$SECRET_KEY
EOF
fi
chown "$RUN_AS":"$RUN_AS" "$APP_DIR/.env" 2>/dev/null || true

# --------------------- 6. 注册 systemd 服务 ---------------------
info "[6/8] 注册 systemd 服务"
SERVICE_NAME="jobmanager"
cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=JobManager Flask App
After=network.target

[Service]
User=$RUN_AS
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/gunicorn -w 4 -b 0.0.0.0:$APP_PORT \
    --access-logfile $APP_DIR/logs/access.log \
    --error-logfile $APP_DIR/logs/error.log \
    run:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable ${SERVICE_NAME} >/dev/null 2>&1

# --------------------- 7. 配置日志轮转 ---------------------
info "[7/8] 配置日志轮转（每天一个文件，保留30天）"
cat > /etc/logrotate.d/${SERVICE_NAME} <<EOF
$APP_DIR/logs/*.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
    copytruncate
    sharedscripts
    postrotate
        systemctl kill -s HUP ${SERVICE_NAME} 2>/dev/null || true
    endscript
}
EOF

# --------------------- 8. 开放防火墙端口 ---------------------
info "[8/8] 开放防火墙端口 $APP_PORT/tcp"
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=${APP_PORT}/tcp >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi

# --------------------- 启动 ---------------------
info "启动服务 ..."
systemctl restart ${SERVICE_NAME}
systemctl enable --now ${SERVICE_NAME} >/dev/null 2>&1

sleep 2
echo -e "${GREEN}============================================================${NC}"
info "部署完成！"
info "服务状态 : $(systemctl is-active ${SERVICE_NAME} 2>/dev/null || echo 未知)"
info "访问地址 : http://<服务器IP>:$APP_PORT/login"
info "默认账号 : admin1 / admin123"
info "          admin2 / admin123"
echo -e "查看日志 : ${YELLOW}tail -f $APP_DIR/logs/error.log${NC}"
echo -e "实时      : ${YELLOW}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "注意      : 控制台安全组需放行 ${APP_PORT} 端口"
echo -e "${GREEN}============================================================${NC}"

# 健康检查
if command -v curl >/dev/null 2>&1; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${APP_PORT}/login || echo 000)
  if [ "$HTTP_CODE" = "200" ]; then
    info "健康检查通过 (HTTP 200)"
  else
    warn "健康检查返回 HTTP $HTTP_CODE，请查看日志： tail -f $APP_DIR/logs/error.log"
  fi
fi
