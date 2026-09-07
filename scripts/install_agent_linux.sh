#!/bin/bash
# AIOps采集Agent - Linux一键安装脚本 (零依赖版, 安装包内置便携Python)
# 用法: ./install_agent_linux.sh <平台服务器地址>
# 例如: ./install_agent_linux.sh http://192.168.1.100:8080
#       ./install_agent_linux.sh 192.168.1.100        (默认端口8080)

set -e

if [ -z "$1" ]; then
  echo "用法: $0 <平台服务器地址>"
  echo "例如: $0 http://192.168.1.100:8080"
  exit 1
fi

case "$1" in
  http*|https*) SERVER="$1" ;;
  *) SERVER="http://$1:${2:-8080}" ;;
esac

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$DEPLOY_DIR/backend/packages/aiops-agent-linux.tar.gz"
if [ ! -f "$PKG" ]; then
  echo "[错误] 未找到安装包: $PKG"
  exit 1
fi

echo "====================================================="
echo "  AIOps Agent 安装 (零依赖版, 服务端: $SERVER)"
echo "====================================================="

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$PKG" -C "$TMP"
cp "$PKG" "$TMP/aiops-agent/"   # 让 install.sh 走本地包, 离线环境无需联网
bash "$TMP/aiops-agent/install.sh" --server "$SERVER"
