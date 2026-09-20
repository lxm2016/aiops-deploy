"""Rack (机柜) management APIs."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Rack, RackDevice, Server, Alert
from app.schemas.schemas import (
    RackCreate, RackOut,
    RackDeviceCreate, RackDeviceOut,
    RackDeviceImportIn,
)

router = APIRouter(prefix="/api", tags=["racks"])

VALID_TYPES = {"server", "switch", "storage", "security", "other"}
VALID_SIDES = {"front", "back"}


# ============ 设备状态联动 ============
# 机柜设备(RackDevice)本身只有台账信息, 没有状态列。这里把台账与实时监控
# 数据关联起来, 让 3D/2D 视图里的状态灯反映真实情况 —— 否则告警高亮永远是摆设。
#   1) 设备名/IP 匹配 servers 表  -> 在线 / 离线
#   2) 设备名匹配 alerts 表未恢复告警 -> warning / critical

_LEVEL_RANK = {"info": 0, "warning": 1, "critical": 2}
_STATUS_RANK = {"unknown": 0, "online": 1, "offline": 2, "warning": 3, "critical": 4}


async def _build_link_maps(db: AsyncSession):
    """构建 (服务器映射, 未恢复告警映射)。"""
    servers = (await db.execute(select(Server))).scalars().all()
    srv_map: dict = {}
    for s in servers:
        for key in (s.name, s.ip):
            k = str(key).strip().lower() if key else ""
            if k and k not in srv_map:
                srv_map[k] = s
        # 主机名短名(去域名)也建索引, 提高匹配率
        if s.name and "." in s.name:
            short = s.name.split(".")[0].strip().lower()
            if short and short not in srv_map:
                srv_map[short] = s

    alerts = (await db.execute(
        select(Alert).where(Alert.status == "open")
    )).scalars().all()
    alert_map: dict = {}
    for a in alerts:
        key = (a.source or "").strip().lower()
        if not key:
            continue
        lvl = (a.level or "info").lower()
        cur_lvl, cur_cnt = alert_map.get(key, (None, 0))
        if cur_lvl is None or _LEVEL_RANK.get(lvl, 0) > _LEVEL_RANK.get(cur_lvl, 0):
            cur_lvl = lvl
        alert_map[key] = (cur_lvl, cur_cnt + 1)

    return srv_map, alert_map


def _match_alert(alert_map: dict, dev_name: str):
    """告警来源与设备名互为子串即视为命中。返回 (等级, 条数)。"""
    key = (dev_name or "").strip().lower()
    if not key:
        return None, 0
    if key in alert_map:
        return alert_map[key]
    for src, val in alert_map.items():
        if src and (src in key or key in src):
            return val
    return None, 0


def _calc_device_status(dev_name: str, srv_map: dict, alert_map: dict) -> dict:
    """派生设备状态: critical > offline > warning > online > unknown。"""
    key = (dev_name or "").strip().lower()
    srv = srv_map.get(key)
    lvl, cnt = _match_alert(alert_map, dev_name)

    if lvl == "critical":
        status = "critical"
    elif srv is not None and srv.status == "offline":
        status = "offline"
    elif lvl == "warning":
        status = "warning"
    elif srv is not None and srv.status == "online":
        status = "online"
    elif srv is not None:
        status = srv.status or "unknown"
    else:
        status = "unknown"

    return {
        "status": status,
        "ip": srv.ip if srv else None,
        "alert_level": lvl,
        "alert_count": cnt,
    }


def _decorate(device: RackDevice, srv_map: dict, alert_map: dict) -> RackDeviceOut:
    """把 ORM 对象转成带状态的出参模型。"""
    item = RackDeviceOut.model_validate(device)
    for k, v in _calc_device_status(device.name, srv_map, alert_map).items():
        setattr(item, k, v)
    return item


def _rack_status(devices) -> str:
    """机柜整体状态取其中设备的最高等级。"""
    best = "unknown"
    for d in devices:
        s = getattr(d, "status", None) or "unknown"
        if _STATUS_RANK.get(s, 0) > _STATUS_RANK.get(best, 0):
            best = s
    return best


def _check_overlap(db_devices: list, u_start: int, u_size: int, side: str, exclude_id: int = None):
    """同侧U位重叠校验。返回冲突设备名或None。"""
    new_lo, new_hi = u_start, u_start + u_size - 1
    for d in db_devices:
        if d.side != side or (exclude_id and d.id == exclude_id):
            continue
        lo, hi = d.u_start, d.u_start + d.u_size - 1
        if new_lo <= hi and lo <= new_hi:
            return d.name
    return None


# ---------- Racks ----------
@router.get("/racks", response_model=List[RackOut])
async def list_racks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rack).order_by(Rack.row_name, Rack.name))
    return result.scalars().all()


@router.get("/racks/overview")
async def racks_overview(db: AsyncSession = Depends(get_db)):
    """一次返回 机柜列表 + 全量设备 + 统计。

    前端原本要逐柜请求 devices(N+1), 机柜一多明显变慢;
    这里合并为一次请求, 并附带机柜级状态供 3D 总览着色。
    """
    racks = (await db.execute(select(Rack).order_by(Rack.row_name, Rack.name))).scalars().all()
    devices = (await db.execute(select(RackDevice).order_by(RackDevice.u_start))).scalars().all()
    srv_map, alert_map = await _build_link_maps(db)

    by_rack: dict = {}
    for d in devices:
        by_rack.setdefault(d.rack_id, []).append(_decorate(d, srv_map, alert_map))

    rack_out = []
    for r in racks:
        devs = by_rack.get(r.id, [])
        rack_out.append({
            "id": r.id,
            "name": r.name,
            "row_name": r.row_name,
            "u_height": r.u_height,
            "remark": r.remark,
            "device_count": len(devs),
            "used_u": sum(d.u_size for d in devs if d.side == "front"),
            "status": _rack_status(devs),
        })

    flat = [d for arr in by_rack.values() for d in arr]
    cnt = lambda st: sum(1 for d in flat if d.status == st)  # noqa: E731

    return {
        "racks": rack_out,
        "devices": {str(k): v for k, v in by_rack.items()},
        "stats": {
            "rack_count": len(racks),
            "device_count": len(flat),
            "online": cnt("online"),
            "offline": cnt("offline"),
            "warning": cnt("warning"),
            "critical": cnt("critical"),
            "unknown": cnt("unknown"),
        },
    }


@router.post("/racks", response_model=RackOut)
async def create_rack(data: RackCreate, db: AsyncSession = Depends(get_db)):
    if data.u_height < 1 or data.u_height > 60:
        raise HTTPException(status_code=400, detail="U数需在1~60之间")
    result = await db.execute(select(Rack).where(Rack.name == data.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"机柜编号 {data.name} 已存在")
    rack = Rack(**data.model_dump())
    db.add(rack)
    await db.commit()
    await db.refresh(rack)
    return rack


@router.put("/racks/{rack_id}", response_model=RackOut)
async def update_rack(rack_id: int, data: RackCreate, db: AsyncSession = Depends(get_db)):
    rack = await db.get(Rack, rack_id)
    if not rack:
        raise HTTPException(status_code=404, detail="机柜不存在")
    if data.u_height < 1 or data.u_height > 60:
        raise HTTPException(status_code=400, detail="U数需在1~60之间")
    if data.name != rack.name:
        result = await db.execute(select(Rack).where(Rack.name == data.name))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"机柜编号 {data.name} 已存在")
    # 缩小U数时校验已有设备是否越界
    result = await db.execute(select(RackDevice).where(RackDevice.rack_id == rack_id))
    for d in result.scalars().all():
        if d.u_start + d.u_size - 1 > data.u_height:
            raise HTTPException(
                status_code=400,
                detail=f"设备 {d.name} 位于 {d.u_start}~{d.u_start + d.u_size - 1}U, 超出新的U数 {data.u_height}"
            )
    for k, v in data.model_dump().items():
        setattr(rack, k, v)
    await db.commit()
    await db.refresh(rack)
    return rack


@router.delete("/racks/{rack_id}")
async def delete_rack(rack_id: int, db: AsyncSession = Depends(get_db)):
    rack = await db.get(Rack, rack_id)
    if not rack:
        raise HTTPException(status_code=404, detail="机柜不存在")
    await db.execute(delete(RackDevice).where(RackDevice.rack_id == rack_id))
    await db.delete(rack)
    await db.commit()
    return {"ok": True}


# ---------- Rack devices ----------
@router.get("/racks/{rack_id}/devices", response_model=List[RackDeviceOut])
async def list_rack_devices(rack_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RackDevice).where(RackDevice.rack_id == rack_id).order_by(RackDevice.u_start)
    )
    devices = result.scalars().all()
    srv_map, alert_map = await _build_link_maps(db)
    return [_decorate(d, srv_map, alert_map) for d in devices]


@router.post("/racks/{rack_id}/devices", response_model=RackDeviceOut)
async def add_rack_device(rack_id: int, data: RackDeviceCreate, db: AsyncSession = Depends(get_db)):
    rack = await db.get(Rack, rack_id)
    if not rack:
        raise HTTPException(status_code=404, detail="机柜不存在")
    if data.device_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="设备类型无效")
    if data.side not in VALID_SIDES:
        raise HTTPException(status_code=400, detail="放置侧无效")
    if data.u_start < 1 or data.u_start + data.u_size - 1 > rack.u_height:
        raise HTTPException(status_code=400, detail=f"U位超出机柜范围(1~{rack.u_height}U)")

    result = await db.execute(select(RackDevice).where(RackDevice.rack_id == rack_id))
    conflict = _check_overlap(result.scalars().all(), data.u_start, data.u_size, data.side)
    if conflict:
        side_label = "前侧" if data.side == "front" else "后侧"
        raise HTTPException(
            status_code=400,
            detail=f"{side_label}U位与设备 [{conflict}] 重叠"
        )

    device = RackDevice(rack_id=rack_id, **data.model_dump())
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.put("/racks/devices/{device_id}", response_model=RackDeviceOut)
async def update_rack_device(device_id: int, data: RackDeviceCreate, db: AsyncSession = Depends(get_db)):
    device = await db.get(RackDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    rack = await db.get(Rack, device.rack_id)
    if data.device_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="设备类型无效")
    if data.side not in VALID_SIDES:
        raise HTTPException(status_code=400, detail="放置侧无效")
    if data.u_start < 1 or data.u_start + data.u_size - 1 > rack.u_height:
        raise HTTPException(status_code=400, detail=f"U位超出机柜范围(1~{rack.u_height}U)")

    result = await db.execute(select(RackDevice).where(RackDevice.rack_id == device.rack_id))
    conflict = _check_overlap(result.scalars().all(), data.u_start, data.u_size, data.side, exclude_id=device_id)
    if conflict:
        side_label = "前侧" if data.side == "front" else "后侧"
        raise HTTPException(
            status_code=400,
            detail=f"{side_label}U位与设备 [{conflict}] 重叠"
        )

    for k, v in data.model_dump().items():
        setattr(device, k, v)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/racks/devices/{device_id}")
async def delete_rack_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await db.get(RackDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    await db.delete(device)
    await db.commit()
    return {"ok": True}


# ---------- Excel 批量导入 ----------
@router.post("/racks/devices/import")
async def import_rack_devices(data: RackDeviceImportIn, db: AsyncSession = Depends(get_db)):
    """前端解析Excel后批量提交。机柜不存在时自动创建(默认42U)。"""
    success, errors = 0, []

    # 预加载所有机柜
    result = await db.execute(select(Rack))
    racks_by_name = {r.name: r for r in result.scalars().all()}
    # 内存中的设备缓存(含本次新增), 用于重叠校验
    result = await db.execute(select(RackDevice))
    devices_by_rack: dict = {}
    for d in result.scalars().all():
        devices_by_rack.setdefault(d.rack_id, []).append(d)

    for idx, item in enumerate(data.items, start=1):
        row_label = f"第{idx}行"
        try:
            name = (item.name or "").strip()
            rack_name = (item.rack_name or "").strip()
            if not name or not rack_name:
                errors.append(f"{row_label}: 机柜编号/设备名称为空")
                continue
            if item.device_type not in VALID_TYPES:
                errors.append(f"{row_label}: 设备类型 [{item.device_type}] 无效")
                continue
            side = item.side if item.side in VALID_SIDES else "front"
            if item.u_start < 1 or item.u_size < 1:
                errors.append(f"{row_label}: U位/U数无效")
                continue

            rack = racks_by_name.get(rack_name)
            if not rack:
                # 自动创建机柜, 列名取编号前缀字母
                prefix = "".join(c for c in rack_name if c.isalpha()) or "A"
                rack = Rack(name=rack_name, row_name=prefix, u_height=42)
                db.add(rack)
                await db.flush()
                racks_by_name[rack_name] = rack
                devices_by_rack.setdefault(rack.id, [])

            if item.u_start + item.u_size - 1 > rack.u_height:
                errors.append(f"{row_label}: U位超出机柜 {rack_name} 范围({rack.u_height}U)")
                continue

            conflict = _check_overlap(devices_by_rack.get(rack.id, []), item.u_start, item.u_size, side)
            if conflict:
                side_label = "前侧" if side == "front" else "后侧"
                errors.append(f"{row_label}: {rack_name} {side_label}U位与 [{conflict}] 重叠")
                continue

            device = RackDevice(
                rack_id=rack.id, name=name, device_type=item.device_type,
                u_start=item.u_start, u_size=item.u_size, side=side,
                remark=item.remark or ""
            )
            db.add(device)
            await db.flush()
            devices_by_rack.setdefault(rack.id, []).append(device)
            success += 1
        except Exception as e:
            errors.append(f"{row_label}: {e}")

    await db.commit()
    return {"success": success, "errors": errors}
