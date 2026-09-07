# -*- coding: utf-8 -*-
"""Windows 平台采集器。

支持系统: Windows Server 2008 / 2008R2 / 2012 / 2012R2 / 2016 / 2019。
依赖: 仅使用 psutil + 系统自带 sc.exe / 注册表, 无需额外组件。
注意: 建议以管理员权限运行, 否则监听端口-进程映射可能无法获取。
兼容性说明: Windows 2008/2008R2 请安装 Python 3.8(3.8 是官方支持该系统的最后版本)。
"""
import locale
import re
import subprocess
import sys

from .base import BaseCollector

# Windows 内部版本号 -> 产品名映射
_WIN_NAMES = {
    (6, 0): "Windows Server 2008",
    (6, 1): "Windows Server 2008 R2",
    (6, 2): "Windows Server 2012",
    (6, 3): "Windows Server 2012 R2",
    (10, 0): "Windows Server 2016/2019",
}

# 按 build 号细分 Windows 10 内核的服务器版本
_WIN10_BUILDS = [
    (20348, "Windows Server 2022"),
    (17763, "Windows Server 2019"),
    (14393, "Windows Server 2016"),
]


def _run_cmd(cmd, timeout=30):
    """执行命令并按系统编码解码输出, 失败返回空字符串。"""
    try:
        raw = subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, timeout=timeout,
        )
        encoding = locale.getpreferredencoding(False) or "utf-8"
        return raw.decode(encoding, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


class WindowsCollector(BaseCollector):
    """Windows 采集器实现。"""

    os_type = "windows"

    def os_distro(self):
        """发行版名称: Microsoft Windows Server。"""
        return "Microsoft Windows Server"

    def os_version(self):
        """系统版本, 如 '2019 (10.0.17763)'。"""
        w = sys.getwindowsversion()
        version_str = "{}.{}.{}".format(w.major, w.minor, w.build)
        name = _WIN_NAMES.get((w.major, w.minor), "Windows")
        # Windows Server 2016/2019/2022 内核均为 10.0, 按 build 号细分
        if (w.major, w.minor) == (10, 0):
            for build, product in _WIN10_BUILDS:
                if w.build >= build:
                    name = product
                    break
        return "{} ({})".format(name, version_str)

    def cpu_model(self):
        """CPU 型号: 优先读注册表, 失败时回退到 wmic 命令。"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            try:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            finally:
                winreg.CloseKey(key)
        except OSError:
            pass
        out = _run_cmd(["wmic", "cpu", "get", "Name", "/value"])
        m = re.search(r"Name=(.+)", out)
        return m.group(1).strip() if m else "unknown"

    def load_avg(self):
        """Windows 无 Unix 负载概念, 固定返回 0。"""
        return 0.0

    def collect_services(self, limit=500):
        """服务状态列表。

        优先解析 sc.exe 输出(兼容中英文系统、无需 PowerShell),
        失败时回退到 PowerShell Get-Service。
        """
        services = self._services_from_sc(limit)
        if not services:
            services = self._services_from_powershell(limit)
        return services

    def _services_from_sc(self, limit):
        """通过 'sc query' 解析服务状态, 兼容中英文系统输出。"""
        out = _run_cmd(["sc", "query", "type=", "service", "state=", "all"], timeout=60)
        if not out:
            return []
        services = []
        current = None
        for line in out.splitlines():
            # 服务名行: "SERVICE_NAME: xxx" 或中文系统 "服务名称: xxx"
            m = re.match(r"^(?:SERVICE_NAME|服务名称)\s*:\s*(\S+)", line)
            if m:
                current = m.group(1)
                continue
            # 状态行: "STATE : 4 RUNNING" 或中文系统 "状态 : 4 RUNNING"
            m = re.search(r"(?:STATE|状态)\s*:\s*\d+\s+(\S+)", line)
            if m and current:
                raw_state = m.group(1).upper()
                state_map = {
                    "RUNNING": "running",
                    "STOPPED": "stopped",
                    "START_PENDING": "starting",
                    "STOP_PENDING": "stopping",
                    "PAUSED": "paused",
                }
                services.append({
                    "name": current,
                    "status": state_map.get(raw_state, raw_state.lower()),
                })
                current = None
                if len(services) >= limit:
                    break
        return services

    def _services_from_powershell(self, limit):
        """回退方案: 通过 PowerShell 获取服务状态(兼容 PowerShell 2.0)。"""
        out = _run_cmd(
            ["powershell", "-NoProfile", "-Command",
             "Get-Service | ForEach-Object { $_.Name + '|' + $_.Status }"],
            timeout=60,
        )
        services = []
        for line in out.splitlines():
            if "|" not in line:
                continue
            name, status = line.strip().split("|", 1)
            services.append({
                "name": name,
                "status": "running" if status.strip() == "Running" else "stopped",
            })
            if len(services) >= limit:
                break
        return services
