#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 Agent 零依赖安装包 (夜莺模式):
- backend/packages/aiops-agent-linux.tar.gz  (内置便携 Python 3.11 + psutil 预装)
- backend/packages/aiops-agent-windows.zip   (内置便携 Python 3.8  + psutil 预装)

目标机器无需预装 Python、无需联网, 安装脚本直接使用包内运行时。
运行: python build_agent_packages.py
"""
import io
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # backend/
AGENT_SRC = ROOT.parent / "agent"
OUT_DIR = ROOT / "packages"
RUNTIME_DIR = OUT_DIR / "runtime"
WHEELS_DIR = OUT_DIR / "wheels"

PY_LINUX_TGZ = RUNTIME_DIR / "python-linux.tar.gz"   # 顶层为 python/ 的便携运行时
PY_WIN_ZIP = RUNTIME_DIR / "python-win.zip"          # 扁平结构 (python.exe 在根)
PSUTIL_LINUX_WHL = WHEELS_DIR / "psutil-linux.whl"
PSUTIL_WIN_WHL = WHEELS_DIR / "psutil-win.whl"

DEFAULT_TOKEN = "aiops-agent-shared-token"
LINUX_SITE_PACKAGES = "python/lib/python3.11/site-packages"


# ============================================================
# 安装脚本模板
# ============================================================
def render_install_sh(default_server: str = "", token: str = DEFAULT_TOKEN) -> str:
    """Linux 零依赖一键安装脚本。用法:
    curl -sSfL 'http://IP/api/agents/install.sh' | sudo bash -s -- --server 'http://IP'
    """
    return f'''#!/bin/bash
# ============================================================
#  AIOps Agent 一键安装脚本 (Linux 零依赖版)
#  安装包内置便携 Python 运行时, 目标机器无需预装 Python
#  用法:
#    curl -sSfL 'http://IP/api/agents/install.sh' | sudo bash -s -- --server 'http://IP'
#    或解压安装包后: sudo bash aiops-agent/install.sh --server 'http://IP'
# ============================================================
set -e

SERVER="{default_server}"
TOKEN="{token}"
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
echo "  采集间隔 : ${{INTERVAL}}s"
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
'''


def render_install_bat(default_server: str = "", token: str = DEFAULT_TOKEN) -> str:
    """Windows 零依赖安装脚本模板 (UTF-8 字符串, 输出时需编码为 GBK + CRLF 行尾)。"""
    return f'''@echo off
setlocal enabledelayedexpansion
title AIOps Agent 安装

REM ============================================================
REM  AIOps Agent 一键安装 (Windows 零依赖版)
REM  内置便携 Python 运行时, 无需预装 Python
REM  解压本压缩包后, 双击运行本文件, 输入平台地址即可
REM ============================================================

set SERVER={default_server}
set TOKEN={token}
set INTERVAL=5
if defined AIOPS_SERVER set SERVER=%AIOPS_SERVER%

echo ============================================================
echo   AIOps Agent 安装 (Windows 零依赖版)
echo ============================================================
echo.
if "!SERVER!"=="" (
    echo   示例平台地址: http://172.16.10.147
    echo.
    set /p SERVER="请输入平台地址: "
)
if "!SERVER!"=="" (
    echo [错误] 平台地址不能为空
    pause
    exit /b 1
)
if /i not "!SERVER:~0,4!"=="http" set SERVER=http://!SERVER!

echo 平台地址: !SERVER!
echo 采集间隔: !INTERVAL!s
echo.

cd /d "%~dp0"
set PY=%~dp0python\\python.exe
set PYW=%~dp0python\\pythonw.exe

REM 检查内置 Python 运行时, 缺失则回退系统 python
if not exist "%PY%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [错误] 内置 Python 运行时缺失, 且系统未安装 Python
        pause
        exit /b 1
    )
    set PY=python
    set PYW=pythonw
    echo [警告] 内置运行时缺失, 回退使用系统 Python
)

for %%I in ("%PY%") do echo [OK] Python 运行时: %%~fI

echo [1/4] 写入配置...
(
echo server:
echo   url: "!SERVER!/api/servers/report"
echo   token: "!TOKEN!"
echo agent:
echo   interval: !INTERVAL!
echo   timeout: 10
) > "%~dp0config.yaml"

echo [2/4] 测试采集并上报一次...
"%PY%" agent.py --once
if errorlevel 1 (
    echo [警告] 测试上报失败, 请检查平台地址与网络, Agent 仍会按配置继续重试
)

echo [3/4] 设置开机自启...
schtasks /delete /tn "AIOpsAgent" /f >nul 2>&1
schtasks /create /tn "AIOpsAgent" /tr "\\"!PYW!\\" \\"%~dp0agent.py\\"" /sc onstart /ru SYSTEM /rl highest /f

echo [4/4] 启动 Agent...
REM 先终止旧 Agent 进程, 避免重复运行
wmic process where "name='pythonw.exe' and commandline like '%%agent.py%%'" call terminate >nul 2>&1
timeout /t 1 /nobreak >nul
start "" "%PYW%" "%~dp0agent.py"

echo.
echo ============================================================
echo   安装完成! Agent 已在后台运行并设置开机自启。
echo   可到平台 "服务器管理" 页面查看本机上线情况。
echo ============================================================
pause
'''


def install_bat_bytes(default_server: str = "", token: str = DEFAULT_TOKEN) -> bytes:
    """生成 .bat 字节: GBK 编码 + CRLF 行尾 (CMD 必需, 否则解析错乱)。"""
    text = render_install_bat(default_server, token)
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")


# ============================================================
# 打包工具函数
# ============================================================
def _reset_owner(member: tarfile.TarInfo) -> tarfile.TarInfo:
    member.uid = member.gid = 0
    member.uname = member.gname = "root"
    return member


def _copy_runtime_linux(out: tarfile.TarFile):
    """把便携 Python (顶层 python/) 流式拷入输出 tar, 保留权限/软链。"""
    with tarfile.open(PY_LINUX_TGZ, "r:gz") as src:
        for member in src:
            arcname = f"aiops-agent/{member.name}"
            if member.isfile():
                f = src.extractfile(member)
                info = tarfile.TarInfo(arcname)
                info.size = member.size
                info.mode = member.mode
                info.mtime = member.mtime
                _reset_owner(info)
                out.addfile(info, f)
            else:
                # 目录/软链等: 手动重建成员信息 (保留类型与链接目标)
                info = tarfile.TarInfo(arcname)
                info.type = member.type
                info.mode = member.mode
                info.mtime = member.mtime
                info.linkname = member.linkname
                info.size = member.size
                _reset_owner(info)
                out.addfile(info)


def _copy_psutil_linux(out: tarfile.TarFile):
    """把 psutil wheel 内容预解压进内置 Python 的 site-packages。"""
    with zipfile.ZipFile(PSUTIL_LINUX_WHL) as whl:
        for item in whl.infolist():
            if item.is_dir():
                continue
            data = whl.read(item.filename)
            info = tarfile.TarInfo(f"aiops-agent/{LINUX_SITE_PACKAGES}/{item.filename}")
            info.size = len(data)
            info.mode = 0o644
            _reset_owner(info)
            out.addfile(info, io.BytesIO(data))


def _copy_agent_files_linux(out: tarfile.TarFile):
    for name in ["agent.py", "config.yaml"]:
        p = AGENT_SRC / name
        if p.exists():
            out.add(p, arcname=f"aiops-agent/{name}")
    for p in sorted((AGENT_SRC / "collectors").glob("*.py")):
        out.add(p, arcname=f"aiops-agent/collectors/{p.name}")
    # 内置安装脚本 (默认地址留空, 运行时由 --server 或交互提供)
    sh = render_install_sh().encode("utf-8")
    info = tarfile.TarInfo("aiops-agent/install.sh")
    info.size = len(sh)
    info.mode = 0o755
    _reset_owner(info)
    out.addfile(info, io.BytesIO(sh))


def build_linux():
    print("[Linux] 构建 aiops-agent-linux.tar.gz (内置便携Python+psutil) ...")
    tar_path = OUT_DIR / "aiops-agent-linux.tar.gz"
    with tarfile.open(tar_path, "w:gz") as out:
        _copy_agent_files_linux(out)
        _copy_runtime_linux(out)
        _copy_psutil_linux(out)
    print(f"  -> {tar_path} ({tar_path.stat().st_size / 1024 / 1024:.1f} MB)")


def build_windows():
    print("[Windows] 构建 aiops-agent-windows.zip (内置便携Python+psutil) ...")
    zip_path = OUT_DIR / "aiops-agent-windows.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Agent 代码
        for name in ["agent.py", "config.yaml"]:
            p = AGENT_SRC / name
            if p.exists():
                zf.write(p, arcname=f"aiops-agent/{name}")
        for p in sorted((AGENT_SRC / "collectors").glob("*.py")):
            zf.write(p, arcname=f"aiops-agent/collectors/{p.name}")
        # 安装脚本 (GBK + CRLF, 避免 CMD 乱码/解析错乱)
        zf.writestr("aiops-agent/install.bat", install_bat_bytes())
        # 便携 Python 运行时 (扁平结构 -> python/ 目录)
        with zipfile.ZipFile(PY_WIN_ZIP) as rt:
            for item in rt.infolist():
                if item.is_dir():
                    continue
                data = rt.read(item.filename)
                if item.filename == "python38._pth":
                    # 嵌入式Python为隔离模式: 需显式声明 site-packages 与 Agent 根目录(..)
                    text = data.decode("utf-8")
                    text = text.replace("#import site", "import site")
                    lines = [l.strip() for l in text.splitlines()]
                    if "Lib\\site-packages" not in lines:
                        text += "\nLib\\site-packages"
                    if ".." not in lines:
                        text += "\n.."
                    if "import site" not in lines:
                        text += "\nimport site"
                    data = text.encode("utf-8")
                zf.writestr(f"aiops-agent/python/{item.filename}", data)
        # psutil 预解压到 python/Lib/site-packages
        with zipfile.ZipFile(PSUTIL_WIN_WHL) as whl:
            for item in whl.infolist():
                if item.is_dir():
                    continue
                zf.writestr(
                    f"aiops-agent/python/Lib/site-packages/{item.filename}",
                    whl.read(item.filename),
                )
    print(f"  -> {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    build_linux()
    build_windows()
    # 同步一份最新安装脚本到 agent/ 源码目录 (install.bat 为 GBK)
    (AGENT_SRC / "install.sh").write_text(render_install_sh(), encoding="utf-8")
    (AGENT_SRC / "install.bat").write_bytes(install_bat_bytes())
    print("\n完成! 重启后端后即可通过 /api/agents/* 分发。")
