# -*- coding: utf-8 -*-
"""Linux 平台采集器。

支持发行版: CentOS / openEuler / Rocky Linux / Ubuntu / 龙蜥(Anolis OS) 等。
发行版信息优先从 /etc/os-release 读取, 兼容无 systemd 的旧系统(如 CentOS 6)。
建议以 root 运行, 以获取完整的端口-进程映射与服务状态。
"""
import os
import re
import subprocess

from .base import BaseCollector


def _read_os_release():
    """解析 /etc/os-release, 返回键值字典; 文件不存在时返回空字典。"""
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            data = {}
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    data[key] = value.strip().strip('"').strip("'")
            if data:
                return data
        except OSError:
            continue
    return {}


class LinuxCollector(BaseCollector):
    """Linux 采集器实现。"""

    os_type = "linux"

    def os_distro(self):
        """发行版名称, 如 CentOS Linux / openEuler / Rocky Linux / Ubuntu / Anolis OS。"""
        data = _read_os_release()
        return data.get("NAME") or data.get("ID") or "Linux"

    def os_version(self):
        """发行版版本号, 如 7.9 / 22.04 / 8.8。"""
        data = _read_os_release()
        version = data.get("VERSION_ID", "")
        if not version:
            # 旧系统回退: 从 /etc/redhat-release 中提取版本号
            try:
                with open("/etc/redhat-release", "r", encoding="utf-8") as f:
                    m = re.search(r"(\d+(?:\.\d+)*)", f.read())
                    if m:
                        version = m.group(1)
            except OSError:
                pass
        return version

    def cpu_model(self):
        """CPU 型号: 从 /proc/cpuinfo 解析, 兼容 x86 与 aarch64(鲲鹏等)。"""
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    # x86 为 "model name", 部分 ARM 为 "Hardware" 或 "Processor"
                    for key in ("model name", "Hardware", "Processor"):
                        if line.startswith(key):
                            return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return "unknown"

    def load_avg(self):
        """系统 1 分钟平均负载。"""
        try:
            return round(os.getloadavg()[0], 2)
        except OSError:
            return 0.0

    def collect_services(self, limit=500):
        """服务状态列表。

        优先使用 systemd(systemctl), 失败时回退到 SysVinit(service --status-all)。
        """
        # ---- 方式一: systemd (CentOS 7+/openEuler/Rocky/Ubuntu 16+) ----
        try:
            out = subprocess.check_output(
                ["systemctl", "list-units", "--type=service", "--all",
                 "--no-pager", "--plain", "--no-legend"],
                stderr=subprocess.DEVNULL, timeout=15, universal_newlines=True,
            )
            services = []
            for line in out.splitlines():
                parts = line.split(None, 4)  # UNIT LOAD ACTIVE SUB DESCRIPTION
                if len(parts) < 4:
                    continue
                unit, _load, active, sub = parts[0], parts[1], parts[2], parts[3]
                if active == "active":
                    status = "running"
                elif active == "failed":
                    status = "failed"
                else:
                    status = sub or active  # inactive/dead 等
                services.append({"name": unit, "status": status})
                if len(services) >= limit:
                    break
            return services
        except (OSError, subprocess.SubprocessError):
            pass

        # ---- 方式二: SysVinit 回退 (如 CentOS 6 等无 systemd 系统) ----
        try:
            out = subprocess.check_output(
                ["service", "--status-all"],
                stderr=subprocess.DEVNULL, timeout=30, universal_newlines=True,
            )
            services = []
            for line in out.splitlines():
                # 输出形如: [ + ]  sshd / [ - ]  iptables / [ ? ]  xxx
                m = re.match(r"\s*\[([+\-?])\]\s+(\S+)", line)
                if not m:
                    continue
                flag, name = m.groups()
                status = {"+": "running", "-": "stopped"}.get(flag, "unknown")
                services.append({"name": name, "status": status})
                if len(services) >= limit:
                    break
            return services
        except (OSError, subprocess.SubprocessError):
            return []
