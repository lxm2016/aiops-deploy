"""Background scheduler: periodic polling of network devices, offline detection."""
import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, delete

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models import (
    Server, NetworkDevice, ServerMetric, EnvReading, VmwareHost, StorageDevice,
)
from app.services.snmp_service import collect_network_device
from app.services.storage_service import collect_storage
from app.services.vmware_service import collect_vmware_data

scheduler = AsyncIOScheduler()


async def mark_offline_servers():
    """Mark servers offline if agent hasn't reported for 3 minutes."""
    async with AsyncSessionLocal() as db:
        threshold = datetime.utcnow() - timedelta(minutes=3)
        result = await db.execute(
            select(Server).where(
                Server.status == "online",
                (Server.last_seen < threshold) | (Server.last_seen.is_(None)),
            )
        )
        for server in result.scalars().all():
            server.status = "offline"
        await db.commit()


async def poll_all_network_devices():
    """SNMP poll all registered network devices (含端口明细刷新)。"""
    from app.api.devices import upsert_ports  # 延迟导入, 避免循环依赖

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(NetworkDevice))
        devices = result.scalars().all()

    for device in devices:
        try:
            data = await collect_network_device(
                device.ip, device.snmp_community, device.vendor, device.snmp_version
            )
            async with AsyncSessionLocal() as db:
                d = await db.get(NetworkDevice, device.id)
                if d:
                    d.status = "online" if data["reachable"] else "offline"
                    if data["reachable"]:
                        d.cpu_percent = data["cpu_percent"]
                        d.mem_percent = data["mem_percent"]
                        d.port_total = data["port_total"]
                        d.port_up = data["port_up"]
                        d.last_seen = datetime.utcnow()
                        await upsert_ports(db, device.id, data["ports"])
                    await db.commit()
        except Exception:
            pass


async def poll_all_storage():
    """周期采集所有配置了协议的存储设备 (SNMP/SMI-S)。"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StorageDevice))
        devices = result.scalars().all()

    for device in devices:
        if device.protocol not in ("snmp", "smi-s"):
            continue
        try:
            data = await collect_storage(
                device.protocol, device.ip,
                device.snmp_community, device.snmp_version,
                device.username, device.password,
            )
            async with AsyncSessionLocal() as db:
                d = await db.get(StorageDevice, device.id)
                if not d:
                    continue
                if data.get("reachable"):
                    d.status = "online"
                    d.last_seen = datetime.utcnow()
                    if data["capacity_tb"]:
                        d.capacity_tb = data["capacity_tb"]
                        d.used_tb = data["used_tb"]
                        d.used_percent = data["used_percent"]
                    d.details = data["details"]
                else:
                    d.status = "offline"
                await db.commit()
        except Exception:
            pass


async def sync_all_vmware():
    """周期同步所有 vCenter/ESXi 的虚拟机清单与实时使用率。"""
    from app.api.vmware import upsert_vms  # 延迟导入, 避免循环依赖

    async with AsyncSessionLocal() as db:
        hosts = (await db.execute(select(VmwareHost))).scalars().all()
    for host in hosts:
        try:
            data = await asyncio.to_thread(
                collect_vmware_data, host.host, host.username, host.password, host.port
            )
            async with AsyncSessionLocal() as db:
                h = await db.get(VmwareHost, host.id)
                if not h:
                    continue
                if data.get("error") and not data.get("vms"):
                    h.status = "error"
                else:
                    h.status = "online"
                    h.last_sync = datetime.utcnow()
                await db.commit()
                if data.get("vms"):
                    await upsert_vms(db, host.id, data["vms"])
        except Exception:
            pass


async def cleanup_old_metrics():
    """清理超过保留期(默认90天)的历史监控数据, 防止磁盘无限增长。"""
    threshold = datetime.utcnow() - timedelta(days=get_settings().metric_retention_days)
    async with AsyncSessionLocal() as db:
        r1 = await db.execute(delete(ServerMetric).where(ServerMetric.collected_at < threshold))
        r2 = await db.execute(delete(EnvReading).where(EnvReading.collected_at < threshold))
        await db.commit()
        if r1.rowcount or r2.rowcount:
            print(f"[cleanup] 清理过期数据: 服务器指标 {r1.rowcount} 条, 环境读数 {r2.rowcount} 条")


def start_scheduler():
    scheduler.add_job(mark_offline_servers, "interval", minutes=1, id="offline_check")
    scheduler.add_job(poll_all_network_devices, "interval", minutes=2, id="snmp_poll")
    scheduler.add_job(poll_all_storage, "interval", minutes=5, id="storage_poll")
    scheduler.add_job(sync_all_vmware, "interval", minutes=5, id="vmware_sync")
    scheduler.add_job(cleanup_old_metrics, "interval", hours=6, id="metric_cleanup")
    scheduler.start()
