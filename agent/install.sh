#!/bin/bash
# ============================================================
#  AIOps Agent 一键安装脚本 (Linux 零依赖版)
#  安装包内置便携 Python 运行时, 目标机器无需预装 Python
#  用法:
#    curl -sSfL 'http://IP/api/agents/install.sh' | sudo bash -s -- --server 'http://IP'
#    或解压安装包后: sudo bash aiops-agent/install.sh --server 'http://IP'
# ============================================================
set -e

SERVER=""
TOKEN="aiops-agent-shared-token"
INTERVAL=5
INSTALL_DIR="/opt/aiops-agent"

# ---------- 解析参数 ----------
while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="$2"; shift 2 ;;
    --token)  TOKEN="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# 容错: 平台地址漏写 http:// 时自动补上
case "$SERVER" in
  http://*|https://*) ;;
  *) SERVER="http://$SERVER" ;;
esac

echo "============================================================"
echo "  AIOps Agent 安装 (零依赖版, 内置 Python 运行时)"
echo "  平台地址 : $SERVER"
echo "  采集间隔 : ${INTERVAL}s"
echo "  安装目录 : $INSTALL_DIR"
echo "============================================================"

# ---------- 检查 root ----------
if [ "$(id -u)" != "0" ]; then
  echo "[错误] 请使用 root 或 sudo 运行"; exit 1
fi

# ---------- 获取安装包: 优先同目录/上级目录, 否则从平台下载 ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_PKG=""
for cand in "$SCRIPT_DIR/aiops-agent-linux.tar.gz" "$SCRIPT_DIR/../aiops-agent-linux.tar.gz"; do
  if [ -f "$cand" ]; then TMP_PKG="$cand"; break; fi
done
if [ -n "$TMP_PKG" ]; then
  echo "[1/5] 使用本地安装包: $TMP_PKG"
else
  echo "[1/5] 从平台下载 Agent 安装包..."
  TMP_PKG="/tmp/aiops-agent-linux.tar.gz"
  if command -v curl &> /dev/null; then
    curl -sSfL "$SERVER/api/agents/package/linux" -o "$TMP_PKG"
  elif command -v wget &> /dev/null; then
    wget -q "$SERVER/api/agents/package/linux" -O "$TMP_PKG"
  else
    echo "[错误] 需要 curl 或 wget"; exit 1
  fi
fi

# ---------- 解压 ----------
echo "[2/5] 解压到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
tar -xzf "$TMP_PKG" -C "$INSTALL_DIR" --strip-components=1
if [ "$TMP_PKG" = "/tmp/aiops-agent-linux.tar.gz" ]; then rm -f "$TMP_PKG"; fi

# ---------- 确定 Python 运行时 (内置优先, 系统回退) ----------
PY="$INSTALL_DIR/python/bin/python3.11"
if [ ! -x "$PY" ]; then
  echo "[警告] 内置 Python 运行时不可用, 尝试系统 python3..."
  if command -v python3 &> /dev/null; then
    PY="$(command -v python3)"
    "$PY" -c "import psutil" 2>/dev/null || "$PY" -m pip install psutil 2>/dev/null || true
  else
    echo "[错误] 内置 Python 运行时缺失且系统无 python3"; exit 1
  fi
else
  chmod +x "$PY" 2>/dev/null || true
fi
echo "[OK] Python 运行时: $PY ($("$PY" --version 2>&1))"

# ---------- 写配置 ----------
echo "[3/5] 写入配置..."
cat > "$INSTALL_DIR/config.yaml" << EOF
server:
  url: "$SERVER/api/servers/report"
  token: "$TOKEN"
agent:
  interval: $INTERVAL
  timeout: 10
EOF

# ---------- 注册开机自启并启动 ----------
echo "[4/5] 注册开机自启并启动..."
if command -v systemctl &> /dev/null && [ -d /etc/systemd/system ]; then
  cat > /etc/systemd/system/aiops-agent.service << EOF
[Unit]
Description=AIOps Monitoring Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$PY $INSTALL_DIR/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable aiops-agent
  systemctl restart aiops-agent
else
  echo "[警告] 未检测到 systemd, 使用 nohup 后台启动..."
  pkill -f "$INSTALL_DIR/agent.py" 2>/dev/null || true
  (cd "$INSTALL_DIR" && nohup "$PY" agent.py >/dev/null 2>&1 &)
fi

# ---------- 验证 ----------
echo "[5/5] 验证 Agent 进程..."
sleep 2
if command -v pgrep &> /dev/null && pgrep -f "$INSTALL_DIR/agent.py" > /dev/null 2>&1; then
  echo ""
  echo "============================================================"
  echo "  安装完成! Agent 已启动并设置开机自启。"
  echo "  查看状态: systemctl status aiops-agent"
  echo "  查看日志: journalctl -u aiops-agent -f"
  echo "============================================================"
else
  echo ""
  echo "============================================================"
  echo "  安装流程已执行, 但未检测到 Agent 进程, 请手动检查:"
  echo "  cd $INSTALL_DIR && $PY agent.py --once"
  echo "============================================================"
fi
