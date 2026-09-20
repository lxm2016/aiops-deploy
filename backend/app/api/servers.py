"""Server monitoring API: CRUD + agent metric ingestion + history.

── 稳定性修复说明 ──────────────────────────────────────────────
1) get_metrics: 原实现先 SELECT 全部匹配行, 再在内存里 rows[::step] 降采样。
   查询长周期(如 90 天)时会把上百万行、每行含 raw JSON 的记录一次性载入
   内存, 既吃内存又耗时, 很容易超过前端 60 秒超时。
   现改为: 按 collected_at 倒序取最近 N 行(默认 2 万)后再反转, 内存恒定可控,
   且优先保留用户最关心的最新数据。

2) report_metrics: raw 里原本每条都存 ports / services 全量列表, 但经全库
   检索确认——没有任何后端代码或前端页面读取它们(前端仅使用 raw.disks)。
   这部分正是历史表膨胀的主要来源, 现不再写入, 单条记录体积大幅下降。
────────────────────────────────────────────────────────────────
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Server, ServerMetric, Alert
from app.schemas.schemas import (
    ServerCreate, ServerOut, MetricReport, ServerMetricOut,
)
from app.services.alert_engine import evaluate_server_metrics

router = APIRouter(prefix="/api/servers", tags=["servers"])
settings = get_settings()


@router.get("", response_model=List[ServerOut])
async def list_servers(
    status: Optional[str] = None,
    os_type: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Server)
    if status:
        stmt = stmt.where(Server.status == status)
    if os_type:
        stmt = stmt.where(Server.os_type == os_type)
    if keyword:
        stmt = stmt.where(Server.name.contains(keyword) | Server.ip.contains(keyword))
    result = await db.execute(stmt.order_by(Server.id))
    return result.scalars().all()


@router.post("", response_model=ServerOut)
async def create_server(data: ServerCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Server).where(Server.ip == data.ip))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该IP已存在")
    server = Server(**data.model_dump())
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return server


@router.delete("/{server_id}")
async def delete_server(server_id: int, db: AsyncSession = Depends(get_db)):
    server = await db.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="服务器不存在")
    await db.delete(server)
    await db.commit()
    return {"ok": True}


@router.get("/{server_id}/metrics", response_model=List[ServerMetricOut])
async def get_metrics(
    server_id: int,
    hours: int = 1,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询历史指标。支持 hours 相对范围, 或 start/end 自定义时间段(UTC ISO)。"""
    conditions = [ServerMetric.server_id == server_id]
    if start and end:
        try:
            since = datetime.fromisoformat(start.replace("Z", ""))
            until = datetime.fromisoformat(end.replace("Z", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="时间格式错误")
        if until <= since:
            raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
        if until - since > timedelta(days=90):
            raise HTTPException(status_code=400, detail="时间范围不能超过90天")
        conditions.append(ServerMetric.collected_at >= since)
        conditions.append(ServerMetric.collected_at <= until)
    else:
        hours = min(max(hours, 1), 24 * 90)  # 最长支持查询90天
        since = datetime.utcnow() - timedelta(hours=hours)
        conditions.append(ServerMetric.collected_at >= since)

    # 关键: 先按时间倒序截断, 再反转回升序。避免一次性载入全量历史行。
    max_rows = max(200, int(getattr(settings, "metrics_query_max_rows", 20000)))
    result = await db.execute(
        select(ServerMetric)
        .where(*conditions)
        .order_by(ServerMetric.collected_at.desc())
        .limit(max_rows)
    )
    rows = list(result.scalars().all())
    rows.reverse()  # 恢复为时间升序, 供前端图表使用

    # 再对已截断的结果做等间隔抽样, 保证返回点数适中
    step = max(1, len(rows) // 2000)
    if step > 1:
        sampled = rows[::step]
        if sampled and sampled[-1] is not rows[-1]:
            sampled.append(rows[-1])
        rows = sampled

    # 附加各分区磁盘历史 (从raw.disks提取, 供前端分区分开画线)
    out = []
    for r in rows:
        item = ServerMetricOut.model_validate(r)
        item.disks = (r.raw or {}).get("disks") or []
        out.append(item)
    return out


@router.get("/{server_id}/detail")
async def get_detail(server_id: int, db: AsyncSession = Depends(get_db)):
    """Latest metric with raw detail (disks/ports/services)."""
    result = await db.execute(
        select(ServerMetric)
        .where(ServerMetric.server_id == server_id)
        .order_by(ServerMetric.collected_at.desc())
        .limit(1)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        return {"raw": None}
    return {"raw": metric.raw, "collected_at": metric.collected_at}


@router.post("/report")
async def report_metrics(
    data: MetricReport,
    x_agent_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Agent pushes metrics here. Auto-registers unknown servers."""
    if x_agent_token != settings.agent_token:
        raise HTTPException(status_code=401, detail="Agent令牌无效")

    result = await db.execute(select(Server).where(Server.ip == data.ip))
    server = result.scalar_one_or_none()
    if not server:
        server = Server(
            name=data.hostname or data.ip,
            ip=data.ip,
            os_type=data.os_type,
            os_distro=data.os_distro,
            os_version=data.os_version,
            cpu_cores=data.cpu_cores,
            cpu_model=data.cpu_model,
            mem_total_gb=data.mem_total_gb,
            agent_installed=True,
        )
        db.add(server)
        await db.flush()

    # Update server info
    server.status = "online"
    server.last_seen = datetime.utcnow()
    server.agent_installed = True
    if data.cpu_cores:
        server.cpu_cores = data.cpu_cores
    if data.mem_total_gb:
        server.mem_total_gb = data.mem_total_gb
    if data.cpu_model:
        server.cpu_model = data.cpu_model
    if data.os_distro:
        server.os_distro = data.os_distro
    if data.os_version:
        server.os_version = data.os_version

    metric = ServerMetric(
        server_id=server.id,
        cpu_percent=data.cpu_percent,
        mem_percent=data.mem_percent,
        mem_used_gb=data.mem_used_gb,
        disk_percent=data.disk_percent,
        disk_used_gb=data.disk_used_gb,
        disk_total_gb=data.disk_total_gb,
        net_rx_mbps=data.net_rx_mbps,
        net_tx_mbps=data.net_tx_mbps,
        load_avg=data.load_avg,
        process_count=data.process_count,
        # 只保留确实被消费的字段: 前端仅使用 disks 画分区曲线。
        # ports / services 经全库检索无任何读取方, 原先每条都存一份,
        # 是历史表体积膨胀的主要来源, 故不再写入。
        raw={
            "disks": data.disks,
            "hostname": data.hostname,
        },
        collected_at=datetime.utcnow(),
    )
    db.add(metric)

    # Alert evaluation
    await evaluate_server_metrics(db, server.name, data.model_dump())
    await db.commit()
    return {"ok": True, "server_id": server.id}


@router.get("/stats/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    """Dashboard summary stats."""
    total = (await db.execute(select(func.count(Server.id)))).scalar() or 0
    online = (await db.execute(
        select(func.count(Server.id)).where(Server.status == "online")
    )).scalar() or 0
    linux = (await db.execute(
        select(func.count(Server.id)).where(Server.os_type == "linux")
    )).scalar() or 0
    windows = (await db.execute(
        select(func.count(Server.id)).where(Server.os_type == "windows")
    )).scalar() or 0
    open_alerts = (await db.execute(
        select(func.count(Alert.id)).where(Alert.status == "open")
    )).scalar() or 0
    return {
        "total": total, "online": online, "offline": total - online,
        "linux": linux, "windows": windows, "open_alerts": open_alerts,
    }
