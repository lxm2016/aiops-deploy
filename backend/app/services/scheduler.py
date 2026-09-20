"""Background scheduler: periodic polling of network devices, offline detection.

── 稳定性修复说明 ──────────────────────────────────────────────
1) 移除 SNMP 轮询中的端口流量逐条写库:
   原代码在每轮轮询里执行
       for port_data in data["ports"]:
           PortTrafficService.save_port_traffic(device.id, port_data)
   而 save_port_traffic 内部是「新建 SessionLocal 连接 + commit」的同步调用。
   一台 48 口交换机 = 48 次建连 + 48 次提交, 每 2 分钟一轮, 且同步阻塞
   事件循环 —— 期间所有 HTTP 请求全部挂起, 这正是"转圈→60s超时"的来源。
   现改为由 enable_port_traffic_history 开关控制, 默认关闭。

2) cleanup_old_metrics 改为分批删除:
   原实现一次性大 DELETE, 且用的是 ORM 层 delete(), SQLAlchemy 会先把
   匹配对象全部加载进 session 再逐条删除; 数据量大时既吃内存又长时间
   持有写锁。现改为按主键分批删除 + 每批之间让出事件循环。
────────────────────────────────────────────────────────────────
"""
import asyncio
import logging
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

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# 单批删除行数: 分批可避免一次超长事务长时间持有写锁
_CLEANUP_BATCH = 5000


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

    # 端口流量历史按需开启: 关闭时完全不触碰 PortTrafficService
    port_history_on = get_settings().enable_port_traffic_history
    traffic_svc = None
    if port_history_on:
        from app.services.port_traffic_service import PortTrafficService
        traffic_svc = PortTrafficService

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

            # 流量历史写入放到会话之外, 且仅在上方开关开启时执行
            if port_history_on and traffic_svc and data["reachable"]:
                await asyncio.to_thread(
                    _save_ports_bulk, traffic_svc, device.id, data["ports"]
                )
        except Exception as e:
            logger.error(f"[scheduler] 轮询网络设备 {device.ip} 失败: {e}", exc_info=True)


def _save_ports_bulk(traffic_svc, device_id: int, ports: list) -> None:
    """在线程池中批量写入端口流量, 避免阻塞事件循环。"""
    for port_data in ports:
        try:
            traffic_svc.save_port_traffic(device_id, port_data)
        except Exception as e:
            logger.error(f"[scheduler] 保存端口流量失败 device={device_id}: {e}")


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
        except Exception as e:
            logger.error(f"[scheduler] 轮询存储设备 {device.ip} 失败: {e}", exc_info=True)


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
        except Exception as e:
            logger.error(f"[scheduler] 同步VMware {host.host} 失败: {e}", exc_info=True)


async def calculate_port_traffic_rates():
    """计算端口流量速率 (仅在启用端口流量历史时注册)。"""
    from app.services.port_traffic_service import PortTrafficService

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(NetworkDevice))
        devices = result.scalars().all()

    for device in devices:
        try:
            # 同步服务在线程池中执行, 不阻塞事件循环
            await asyncio.to_thread(
                PortTrafficService.calculate_port_traffic_rates, device.id, 24
            )
        except Exception as e:
            logger.error(f"[scheduler] 计算设备 {device.name} 端口流量速率失败: {e}")


async def cleanup_port_traffic_metrics():
    """清理超过保留期的端口流量历史数据。"""
    from app.services.port_traffic_service import PortTrafficService
    try:
        await asyncio.to_thread(PortTrafficService.cleanup_old_data, 30)
    except Exception as e:
        logger.error(f"[scheduler] 清理端口流量历史失败: {e}")


async def _purge_by_batches(model, threshold, label: str) -> int:
    """按主键分批删除早于 threshold 的行, 每批让出事件循环。"""
    total = 0
    while True:
        async with AsyncSessionLocal() as db:
            ids = (await db.execute(
                select(model.id).where(model.collected_at < threshold).limit(_CLEANUP_BATCH)
            )).scalars().all()
            if not ids:
                break
            await db.execute(
                delete(model)
                .where(model.id.in_(ids))
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            total += len(ids)
            if len(ids) < _CLEANUP_BATCH:
                break
        await asyncio.sleep(0.2)  # 让出事件循环, 避免长时间独占
    if total:
        logger.info(f"[cleanup] 已清理过期{label}: {total} 条")
    return total


async def cleanup_old_metrics():
    """分批清理超过保留期的历史监控数据, 防止磁盘无限增长。"""
    threshold = datetime.utcnow() - timedelta(days=get_settings().metric_retention_days)
    try:
        await _purge_by_batches(ServerMetric, threshold, "服务器指标")
        await _purge_by_batches(EnvReading, threshold, "环境读数")
    except Exception as e:
        logger.error(f"[cleanup] 清理历史数据失败: {e}", exc_info=True)


def start_scheduler():
    settings = get_settings()

    scheduler.add_job(mark_offline_servers, "interval", minutes=1, id="offline_check")
    scheduler.add_job(poll_all_network_devices, "interval", minutes=2, id="snmp_poll")
    scheduler.add_job(poll_all_storage, "interval", minutes=5, id="storage_poll")
    scheduler.add_job(sync_all_vmware, "interval", minutes=5, id="vmware_sync")
    scheduler.add_job(cleanup_old_metrics, "interval", hours=6, id="metric_cleanup")

    # 端口流量历史: 默认关闭。开启前请确认前端确有对应页面,
    # 否则只会带来写库压力而无任何可见收益。
    if settings.enable_port_traffic_history:
        scheduler.add_job(calculate_port_traffic_rates, "interval", minutes=5, id="port_rate_calc")
        scheduler.add_job(cleanup_port_traffic_metrics, "interval", hours=6, id="port_traffic_cleanup")

    scheduler.start()
    logger.info(
        "[scheduler] 已启动 | 数据保留 %s 天 | 端口流量历史采集: %s",
        settings.metric_retention_days,
        "开启" if settings.enable_port_traffic_history else "关闭(推荐)",
    )
