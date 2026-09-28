#!/bin/bash
# 服务器侧：部署 FastAPI 后端（在 /srv/edu-api 执行）
# 前置：已将 edu-api.tar.gz 上传到 /srv/edu-api/
set -e

ROOT=/srv/edu-api
APP=$ROOT/app
TAR=$ROOT/edu-api.tar.gz

if [ ! -f "$TAR" ]; then
  echo "[错误] 未找到 $TAR，请先上传 edu-api.tar.gz"
  exit 1
fi

# 1) 解包代码（保留 .env，wip：解包会覆盖除 .env 外的文件）
TMP=$(mktemp -d)
tar -xzf "$TAR" -C "$TMP"
if [ -f "$APP/.env" ]; then
  cp "$APP/.env" "$TMP/.env"
fi
rm -rf "$APP"
mkdir -p "$APP"
cp -a "$TMP/." "$APP/"
rm -rf "$TMP"

# 2) 依赖：仅在缺少或 requirements 变化时安装
if [ ! -x "$ROOT/venv/bin/pip" ]; then
  python3 -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/pip" install -q -r "$APP/requirements.txt"

# 3) 权限：运行用户 education 需可读代码、对上传目录可读写
chown -R education:education "$APP"
chmod -R a+rX "$APP" "$ROOT/venv"
chown -R education:education /srv/education/shared/data/uploads 2>/dev/null || true

# 4) 启动/重启（启动时自动执行迁移对账 + RBAC 种子）
systemctl daemon-reload
systemctl restart edu-api.service
sleep 3
systemctl is-active edu-api.service
echo "[完成] 后端已部署，端口 18081"
