#!/bin/bash
# AIOps平台 一键更新脚本
# 用法: bash update.sh <解压后的新包路径>
# 自动备份 → 覆盖 前端/后端代码/Agent安装包 → 安装新增依赖 → 重启
# 保留 venv、.env、数据库(另有备份), 无需重装依赖
set -e

SRC="${1:?用法: bash update.sh <解压后的新包路径>}"
DST="/opt/aiops-deploy"

[ -d "$SRC/backend/app" ] || { echo "[错误] $SRC 不是有效的部署包目录"; exit 1; }
[ -d "$DST" ] || { echo "[错误] $DST 不存在, 请先按部署手册完成首次部署"; exit 1; }

echo "[1/7] 备份数据库与配置..."
mkdir -p "$DST/backup"
TS="$(date +%F_%H%M%S)"
[ -f "$DST/backend/aiops.db" ] && cp -f "$DST/backend/aiops.db" "$DST/backup/aiops_$TS.db" && echo "  已备份: backup/aiops_$TS.db"
[ -f "$DST/backend/.env" ] && cp -f "$DST/backend/.env" "$DST/backup/env_$TS.bak"
ls -1t "$DST/backup"/aiops_*.db 2>/dev/null | tail -n +8 | xargs -r rm -f

echo "[2/7] 更新后端代码..."
rm -rf "$DST/backend/app"
cp -r "$SRC/backend/app" "$DST/backend/"
cp -f "$SRC/backend/build_agent_packages.py" "$DST/backend/" 2>/dev/null || true

echo "[3/7] 更新Agent安装包与离线依赖包..."
rm -rf "$DST/backend/packages"
cp -r "$SRC/backend/packages" "$DST/backend/"
rm -rf "$DST/agent"
cp -r "$SRC/agent" "$DST/" 2>/dev/null || true
rm -rf "$DST/packages"
cp -r "$SRC/packages" "$DST/" 2>/dev/null || true

echo "[4/7] 更新前端..."
rm -rf "$DST/frontend-dist"
cp -r "$SRC/frontend-dist" "$DST/"

echo "[5/7] 清理旧字节码缓存..."
find "$DST/backend/app" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "[6/7] 安装新增依赖 (pywbem等, 存储SMI-S采集用)..."
cd "$DST/backend"
if [ -x ./venv/bin/pip ]; then
  ./venv/bin/pip install --no-index --find-links "$SRC/packages/linux" \
    pywbem ply nocasedict more-itertools >/dev/null 2>&1 \
    && echo "  新依赖安装完成" \
    || echo "  [提示] 新依赖安装失败, SMI-S采集不可用(不影响SNMP)"
else
  echo "  [提示] 未找到venv, 跳过依赖安装"
fi

echo "[7/7] 重启后端服务..."
if systemctl list-unit-files 2>/dev/null | grep -q aiops-backend; then
    systemctl restart aiops-backend
else
    pkill -f "uvicorn app.main" 2>/dev/null || true
    sleep 2
    cd "$DST/backend"
    nohup ./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 >> /var/log/aiops-backend.log 2>&1 &
fi

sleep 3
curl -s http://127.0.0.1:8080/api/health && echo ""
echo "====================================================="
echo "  更新完成! 数据库与配置已自动备份到 $DST/backup/"
echo "  浏览器 Ctrl+F5 强刷即可看到新功能"
echo "====================================================="
