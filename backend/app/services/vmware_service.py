"""VMware vCenter/ESXi data collection via pyvmomi."""
import ssl
from datetime import datetime
from typing import List, Optional

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim


def _connect(host: str, user: str, password: str, port: int = 443):
    """Connect to vCenter/ESXi, ignoring SSL certificate errors."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return SmartConnect(
        host=host, user=user, pwd=password, port=port, sslContext=context
    )


def collect_vmware_data(host: str, user: str, password: str, port: int = 443) -> Optional[dict]:
    """Collect VM list and host summary from vCenter/ESXi.

    Returns dict: {vms: [...], host_summary: {...}} or None on failure.
    """
    try:
        si = _connect(host, user, password, port)
    except Exception as e:
        return {"error": str(e), "vms": []}

    try:
        content = si.RetrieveContent()
        vms = []
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        for vm in container.view:
            try:
                summary = vm.summary
                runtime = summary.runtime
                guest = summary.guest
                qs = summary.quickStats

                # 实时CPU使用率: overallCpuUsage(MHz) / maxCpuUsage(VM上限MHz)
                cpu_percent = 0.0
                try:
                    used_mhz = qs.overallCpuUsage or 0
                    max_mhz = runtime.maxCpuUsage or 0
                    if used_mhz and max_mhz:
                        cpu_percent = round(used_mhz * 100.0 / max_mhz, 1)
                except Exception:
                    cpu_percent = 0.0

                # 实时内存使用率: guestMemoryUsage(客户机内) 或 hostMemoryUsage(主机侧)
                mem_percent = 0.0
                try:
                    mem_total = summary.config.memorySizeMB or 0
                    used = qs.guestMemoryUsage or qs.hostMemoryUsage or 0
                    if used and mem_total:
                        mem_percent = round(used * 100.0 / mem_total, 1)
                except Exception:
                    mem_percent = 0.0

                vms.append({
                    "name": summary.config.name,
                    "power_state": str(runtime.powerState),
                    "guest_os": summary.config.guestFullName or "",
                    "ip": guest.ipAddress or "",
                    "cpu_cores": summary.config.numCpu or 0,
                    "mem_mb": summary.config.memorySizeMB or 0,
                    "cpu_percent": min(cpu_percent, 100.0),
                    "mem_percent": min(mem_percent, 100.0),
                    "uptime": str(runtime.bootTime) if runtime.bootTime else "",
                })
            except Exception:
                continue
        container.Destroy()

        # Host summary
        host_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )
        hosts = []
        for h in host_view.view:
            try:
                hw = h.hardware
                hosts.append({
                    "name": h.name,
                    "cpu_cores": hw.cpuInfo.numCpuCores if hw else 0,
                    "mem_gb": round(hw.memorySize / 1024 ** 3, 1) if hw and hw.memorySize else 0,
                })
            except Exception:
                continue
        host_view.Destroy()

        return {"vms": vms, "hosts": hosts, "collected_at": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"error": str(e), "vms": []}
    finally:
        try:
            Disconnect(si)
        except Exception:
            pass
