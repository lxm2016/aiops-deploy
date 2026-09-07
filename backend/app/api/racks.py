"""Rack (机柜) management APIs."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Rack, RackDevice
from app.schemas.schemas import (
    RackCreate, RackOut,
    RackDeviceCreate, RackDeviceOut,
    RackDeviceImportIn,
)

router = APIRouter(prefix="/api", tags=["racks"])

VALID_TYPES = {"server", "switch", "storage", "security", "other"}
VALID_SIDES = {"front", "back"}


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
    return result.scalars().all()


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
