#!/bin/bash
# AIOps平台 - Linux后端 一键安装脚本（增强版，已处理常见坑）
# 适用: CentOS 7/8/9, openEuler, Rocky Linux, Ubuntu, 龙蜥(Anolis)
# 支持 Python 3.9 ~ 3.13
set -e

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$DEPLOY_DIR/backend"
PKG_DIR="$DEPLOY_DIR/packages/linux"

echo "====================================================="
echo "  AIOps平台 - Linux后端 一键安装"
echo "====================================================="

# ---------- 坑1: 检查Python3 ----------
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到python3，请先安装："
    echo "  CentOS/Rocky/openEuler/龙蜥: yum install -y python3 python3-pip"
    echo "  Ubuntu/Debian: apt install -y python3 python3-venv python3-pip"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "检测到 Python $PY_VER"

PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MINOR" -lt 9 ] || [ "$PY_MINOR" -gt 13 ]; then
    echo "[警告] 离线依赖包支持 Python 3.9~3.13，当前为 $PY_VER，可能安装失败"
    echo "建议安装 python3.11: yum install -y python3.11 或 apt install -y python3.11"
    read -p "是否继续? (y/N) " -n 1 -r; echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

# ---------- 坑2: Ubuntu需要python3-venv ----------
echo "[1/5] 创建虚拟环境..."
cd "$BACKEND_DIR"
rm -rf venv
if ! python3 -m venv venv 2>/dev/null; then
    echo "[错误] 创建虚拟环境失败。"
    echo "  Ubuntu/Debian 请先执行: apt install -y python3-venv"
    echo "  CentOS/openEuler 请先执行: yum install -y python3-pip"
    exit 1
fi

# ---------- 坑3: venv里可能没有pip，用离线包引导 ----------
echo "[2/5] 准备pip..."
if [ ! -f venv/bin/pip ]; then
    echo "  venv缺少pip，从离线包引导..."
    python3 -m venv --without-pip venv 2>/dev/null || true
    ./venv/bin/python -m ensurepip 2>/dev/null || \
    ./venv/bin/python -c "import zipfile,glob,sys; \
whl=[f for f in glob.glob('$PKG_DIR/pip-*.whl')][0]; \
zipfile.ZipFile(whl).extractall('/tmp/_pipboot'); \
import subprocess; subprocess.run([sys.executable,'/tmp/_pipboot/pip','install','--no-index','--find-links=$PKG_DIR','pip','setuptools','wheel'])"
fi

# ---------- 坑4: 先离线升级pip/setuptools/wheel，避免老pip不认识新wheel标签 ----------
echo "[3/5] 离线升级 pip/setuptools/wheel..."
./venv/bin/python -m pip install --no-index --find-links="$PKG_DIR" \
    --upgrade pip setuptools wheel 2>/dev/null || true

# ---------- 坑5: 离线安装依赖（含pyvmomi源码包，构建依赖已就位） ----------
echo "[4/5] 离线安装后端依赖..."
./venv/bin/pip install --no-index --find-links="$PKG_DIR" -r requirements.txt

# ---------- 注册systemd服务 ----------
echo "[5/5] 创建systemd服务..."
cat > /etc/systemd/system/aiops-backend.service << EOF
[Unit]
Description=AIOps Backend Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$BACKEND_DIR
ExecStart=$BACKEND_DIR/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aiops-backend

echo ""
echo "====================================================="
echo "  安装完成!"
echo "  启动服务:  systemctl start aiops-backend"
echo "  查看状态:  systemctl status aiops-backend"
echo "  查看日志:  journalctl -u aiops-backend -f"
echo ""
echo "  别忘了配置: cp $BACKEND_DIR/.env.example $BACKEND_DIR/.env"
echo "====================================================="
