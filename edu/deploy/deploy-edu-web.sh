#!/bin/bash
# 服务器侧：部署前端 dist（在 /srv/edu-api 执行）
# 前置：已将 edu-web.tar.gz（frontend/dist 打包）上传到 /srv/edu-api/
set -e

ROOT=/srv/edu-api
TAR=$ROOT/edu-web.tar.gz
STAMP=$(date +%Y%m%d_%H%M%S)
DIR=/srv/education/frontend-releases/edu-py-$STAMP

if [ ! -f "$TAR" ]; then
  echo "[错误] 未找到 $TAR，请先上传 edu-web.tar.gz"
  exit 1
fi

mkdir -p "$DIR"
tar -xzf "$TAR" -C "$DIR"

# 复用历史 release 中的 logo.png（系统配置 logo=/logo.png）
LOGO=$(find /srv/education/frontend-releases -maxdepth 2 -name 'logo.png' 2>/dev/null | grep -v "$DIR" | head -1)
if [ -n "$LOGO" ]; then
  cp "$LOGO" "$DIR/logo.png"
fi

# 原子切换软链，nginx 无需改动
ln -sfn "$DIR" /srv/education/frontend-current
echo "$DIR" > /tmp/webrel
echo "[完成] 前端已部署到 $DIR（frontend-current 已切换）"
