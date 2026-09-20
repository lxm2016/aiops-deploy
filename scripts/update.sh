#!/bin/bash
# AIOps平台 更新脚本
# 用法1: bash update.sh <解压后的新包路径> (覆盖式更新)
# 用法2: bash update.sh --git-pull (从GitHub拉取最新源码)
# 用法3: bash update.sh --git-pull --check-version (检查版本信息)
# 自动备份 → 更新代码 → 安装新增依赖 → 重启
set -e

DST="/opt/aiops-deploy"

# 版本信息
VERSION_FILE="version.txt"
GITHUB_REPO="https://github.com/lxm2016/aiops-deploy"

# 备份函数
backup_files() {
  mkdir -p "$DST/backup"
  TS="$(date +%F_%H%M%S)"
  [ -f "$DST/backend/aiops.db" ] && cp -f "$DST/backend/aiops.db" "$DST/backup/aiops_$TS.db" && echo "  已备份: backup/aiops_$TS.db"
  [ -f "$DST/backend/.env" ] && cp -f "$DST/backend/.env" "$DST/backup/env_$TS.bak"
  ls -1t "$DST/backup"/aiops_*.db 2>/dev/null | tail -n +8 | xargs -r rm -f
}

# 获取版本信息
get_version() {
  local version_file="$1/$VERSION_FILE"
  if [ -f "$version_file" ]; then
    cat "$version_file" | head -1 | tr -d '\n\r'
  else
    echo "unknown"
  fi
}

# 检查GitHub最新版本
check_latest_version() {
  if command -v curl >/dev/null 2>&1; then
    local latest_version=$(curl -s "https://raw.githubusercontent.com/lxm2016/aiops-deploy/main/version.txt" 2>/dev/null | head -1 | tr -d '\n\r')
    if [ "$latest_version" != "" ] && [ "$latest_version" != "unknown" ]; then
      echo "$latest_version"
    else
      echo "无法获取最新版本信息"
    fi
  else
    echo "curl命令不可用，跳过版本检查"
  fi
}

# 检查运行环境
[ -d "$DST" ] || { echo "[错误] $DST 不存在, 请先按部署手册完成首次部署"; exit 1; }

# 判断更新方式
if [ "$1" = "--git-pull" ]; then
  if [ "$2" = "--check-version" ]; then
    echo "检查当前版本信息..."
    current_version=$(get_version "$DST")
    latest_version=$(check_latest_version)
    echo "  当前版本: $current_version"
    echo "  最新版本: $latest_version"
    if [ "$current_version" != "unknown" ] && [ "$latest_version" != "unknown" ] && [ "$current_version" != "$latest_version" ]; then
      echo "  [提示] 发现新版本 $latest_version，建议更新"
    elif [ "$current_version" = "$latest_version" ]; then
      echo "  [提示] 已是最新版本"
    fi
    exit 0
  fi
  
  echo " [0/7] 从GitHub拉取最新源码..."
  cd "$DST"
  if [ ! -d ".git" ]; then
    echo "[错误] 当前不是git仓库，请先用 git clone https://github.com/lxm2016/aiops-deploy.git 初始化"
    exit 1
  fi
  
  # 检查版本信息
  current_version=$(get_version "$DST")
  latest_version=$(check_latest_version)
  echo "  当前版本: $current_version"
  echo "  正在拉取最新版本..."
  
  git pull origin main 2>/dev/null || { echo "[错误] git pull 失败，请检查网络连接或GitHub访问权限"; exit 1; }
  SRC="$DST"  # 源码已在本地
else
  SRC="${1:?用法: bash update.sh <解压后的新包路径>  或  bash update.sh --git-pull}  或  bash update.sh --git-pull --check-version}"
  [ -d "$SRC/backend/app" ] || { echo "[错误] $SRC 不是有效的部署包目录"; exit 1; }
  echo " [0/7] 备份数库与配置..."
  backup_files
fi

echo "[1/7] 更新后端代码..."
rm -rf "$DST/backend/app"
cp -r "$SRC/backend/app" "$DST/backend/"
cp -f "$SRC/backend/build_agent_packages.py" "$DST/backend/" 2>/dev/null || true

echo "[2/7] 更新Agent安装包与离线依赖包..."
rm -rf "$DST/backend/packages"
cp -r "$SRC/backend/packages" "$DST/backend/"
rm -rf "$DST/agent"
cp -r "$SRC/agent" "$DST/" 2>/dev/null || true
rm -rf "$DST/packages"
cp -r "$SRC/packages" "$DST/" 2>/dev/null || true

echo "[3/7] 更新前端..."
rm -rf "$DST/frontend-dist"
cp -r "$SRC/frontend-dist" "$DST/"

echo "[4/7] 清理旧字节码缓存..."
find "$DST/backend/app" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "[5/7] 安装新增依赖 (pywbem等, 存储SMI-S采集用)..."
cd "$DST/backend"
if [ -x ./venv/bin/pip ]; then
  ./venv/bin/pip install --no-index --find-links "$SRC/packages/linux" \
    pywbem ply nocasedict more-itertools >/dev/null 2>&1 \
    && echo "  新依赖安装完成" \
    || echo "  [提示] 新依赖安装失败, SMI-S采集不可用(不影响SNMP)"
else
  echo "  [提示] 未找到venv, 跳过依赖安装"
fi

echo "[6/7] 更新版本信息..."
if [ -f "$SRC/$VERSION_FILE" ]; then
  cp -f "$SRC/$VERSION_FILE" "$DST/$VERSION_FILE"
  new_version=$(get_version "$DST")
  echo "  版本已更新至: $new_version"
else
  echo "  [提示] 未找到版本信息文件"
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
if [ "$1" = "--git-pull" ]; then
  echo "  来源: GitHub远程拉取 (git pull)"
  echo "  版本: $new_version"
else
  echo "  来源: 本地包覆盖 ($SRC)"
  if [ -f "$DST/$VERSION_FILE" ]; then
    current_version=$(get_version "$DST")
    echo "  版本: $current_version"
  fi
fi
echo "  浏览器 Ctrl+F5 强刷即可看到新功能"
echo "====================================================="
