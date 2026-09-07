# -*- coding: utf-8 -*-
"""采集器公共基类与工具函数。"""
import socket
import time
from abc import ABC, abstractmethod

import psutil

GB = 1024 ** 3  # 1GB 的字节数


class BaseCollector(ABC):
    """采集器基类: 定义统一的采集入口与公共指标实现。

    子类需实现: os_distro / os_version / cpu_model / collect_services
    """

    #: 操作系统类型, 与服务端 Server.os_type 字段对应
    os_type = ""

    # ---------------- 公共指标 ----------------
    def hostname(self):
        """获取主机名。"""
        return socket.gethostname()

    def local_ip(self):
        """获取本机出口 IP(不实际发包, 仅利用 UDP 连接的路由选择)。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            # 无外网路由时回退到主机名解析
            try:
                return socket.gethostbyname(socket.gethostname())
            except OSError:
                return "127.0.0.1"
        finally:
            s.close()

    def cpu_percent(self):
        """CPU 使用率(%), 采样 1 秒。"""
        return psutil.cpu_percent(interval=1)

    def cpu_cores(self):
        """CPU 逻辑核数。"""
        return psutil.cpu_count() or 0

    def memory_info(self):
        """内存信息: (总量GB, 已用GB, 使用率%)。"""
        vm = psutil.virtual_memory()
        return (
            round(vm.total / GB, 2),
            round(vm.used / GB, 2),
            round(vm.percent, 1),
        )

    def net_speed(self):
        """网卡流量速率: (接收Mbps, 发送Mbps), 采样 1 秒, 聚合所有网卡。"""
        c1 = psutil.net_io_counters()
        time.sleep(1)
        c2 = psutil.net_io_counters()
        rx_mbps = max(0.0, (c2.bytes_recv - c1.bytes_recv) * 8 / 1e6)
        tx_mbps = max(0.0, (c2.bytes_sent - c1.bytes_sent) * 8 / 1e6)
        return round(rx_mbps, 2), round(tx_mbps, 2)

    def process_count(self):
        """当前进程总数。"""
        return len(psutil.pids())

    def disk_info(self):
        """磁盘信息: (总容量GB, 已用GB, 使用率%, 各分区明细列表)。"""
        total = used = 0
        disks = []
        for part in psutil.disk_partitions(all=False):
            # 跳过只读伪文件系统(如 Linux 的 squashfs 快照挂载)
            if hasattr(part, "opts") and "ro" in part.opts.split(","):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            total += usage.total
            used += usage.used
            disks.append({
                "mount": part.mountpoint,
                "total_gb": round(usage.total / GB, 2),
                "used_gb": round(usage.used / GB, 2),
                "percent": round(usage.percent, 1),
            })
        percent = round(used * 100.0 / total, 1) if total else 0.0
        return round(total / GB, 2), round(used / GB, 2), percent, disks

    def port_info(self, limit=200):
        """监听端口信息: [{port, process, name}], 按端口去重排序。"""
        ports = {}
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError):
            # 权限不足时返回空列表, 不影响其他指标上报
            return []
        for c in conns:
            if c.status != psutil.CONN_LISTEN or not c.laddr:
                continue
            port = c.laddr.port
            if port in ports:
                continue
            proc_name = ""
            if c.pid:
                try:
                    proc_name = psutil.Process(c.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    proc_name = ""
            # 尝试解析知名端口对应的服务名(如 80->http), 解析失败则留空
            svc_name = ""
            try:
                svc_name = socket.getservbyport(port)
            except OSError:
                pass
            ports[port] = {
                "port": port,
                "process": proc_name,
                "name": svc_name,
            }
            if len(ports) >= limit:
                break
        return [ports[p] for p in sorted(ports)]

    # ---------------- 子类实现 ----------------
    @abstractmethod
    def os_distro(self):
        """发行版名称, 如 CentOS / openEuler / Rocky / Ubuntu / Anolis OS / Windows Server"""

    @abstractmethod
    def os_version(self):
        """操作系统版本号。"""

    @abstractmethod
    def cpu_model(self):
        """CPU 型号字符串。"""

    @abstractmethod
    def load_avg(self):
        """系统负载(1分钟); Windows 无负载概念, 返回 0。"""

    @abstractmethod
    def collect_services(self, limit=100):
        """服务列表: [{name, status}]。"""

    # ---------------- 统一采集入口 ----------------
    def collect(self):
        """采集全部指标, 组装为上报 JSON 字典。"""
        mem_total_gb, mem_used_gb, mem_percent = self.memory_info()
        disk_total_gb, disk_used_gb, disk_percent, disks = self.disk_info()
        net_rx, net_tx = self.net_speed()
        return {
            "ip": self.local_ip(),
            "hostname": self.hostname(),
            "os_type": self.os_type,
            "os_distro": self.os_distro(),
            "os_version": self.os_version(),
            "cpu_model": self.cpu_model(),
            "cpu_cores": self.cpu_cores(),
            "mem_total_gb": mem_total_gb,
            "cpu_percent": self.cpu_percent(),
            "mem_percent": mem_percent,
            "mem_used_gb": mem_used_gb,
            "disk_percent": disk_percent,
            "disk_used_gb": disk_used_gb,
            "disk_total_gb": disk_total_gb,
            "net_rx_mbps": net_rx,
            "net_tx_mbps": net_tx,
            "load_avg": self.load_avg(),
            "process_count": self.process_count(),
            "disks": disks,
            "ports": self.port_info(),
            "services": self.collect_services(),
        }
