"""Network device / storage / env sensor APIs."""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import (
    NetworkDevice, SwitchPort, StorageDevice, EnvSensor, EnvReading,
)
from app.schemas.schemas import (
    NetworkDeviceCreate, NetworkDeviceOut,
    StorageDeviceCreate, StorageDeviceOut,
    EnvSensorCreate, EnvSensorOut, EnvReadingOut,
    PortRemarkIn,
)
from app.services.snmp_service import (
    collect_network_device, get_port_status,
)
from app.services.storage_service import collect_storage
from app.services.alert_engine import evaluate_env_reading

router = APIRouter(prefix="/api", tags=["devices"])


# ---------- Network devices ----------
@router.get("/network", response_model=List[NetworkDeviceOut])
async def list_network_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NetworkDevice).order_by(NetworkDevice.id))
    return result.scalars().all()


@router.post("/network", response_model=NetworkDeviceOut)
async def add_network_device(data: NetworkDeviceCreate, db: AsyncSession = Depends(get_db)):
    device = NetworkDevice(**data.model_dump())
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.put("/network/{device_id}", response_model=NetworkDeviceOut)
async def update_network_device(
    device_id: int, data: NetworkDeviceCreate, db: AsyncSession = Depends(get_db)
):
    device = await db.get(NetworkDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")
    for k, v in data.model_dump().items():
        setattr(device, k, v)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/network/{device_id}")
async def delete_network_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await db.get(NetworkDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")
    await db.delete(device)
    await db.commit()
    return {"ok": True}


@router.post("/network/{device_id}/poll")
async def poll_network_device(device_id: int, db: AsyncSession = Depends(get_db)):
    """SNMP poll a single device, 并刷新端口明细表(保留用户备注)。"""
    device = await db.get(NetworkDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")

    data = await collect_network_device(
        device.ip, device.snmp_community, device.vendor, device.snmp_version
    )
    device.status = "online" if data["reachable"] else "offline"
    if data["reachable"]:
        device.cpu_percent = data["cpu_percent"]
        device.mem_percent = data["mem_percent"]
        device.port_total = data["port_total"]
        device.port_up = data["port_up"]
        if data["sys_name"]:
            device.model = data["sys_descr"][:120] if data["sys_descr"] else device.model
        device.last_seen = datetime.utcnow()
        await upsert_ports(db, device_id, data["ports"])
    await db.commit()
    return data


async def upsert_ports(db: AsyncSession, device_id: int, ports: list):
    """刷新端口明细: 已存在的端口保留用户备注, 新端口插入, 消失的端口删除。"""
    existing = (await db.execute(
        select(SwitchPort).where(SwitchPort.device_id == device_id)
    )).scalars().all()
    remark_map = {p.port_index: p.remark for p in existing}
    seen = set()
    for item in ports:
        seen.add(item["port_index"])
        port = next((p for p in existing if p.port_index == item["port_index"]), None)
        if port:
            port.name = item["name"]
            port.status = item["status"]
            port.speed_mbps = item["speed_mbps"]
            port.alias = item["alias"]
            port.physical = item.get("physical", 1)
        else:
            db.add(SwitchPort(
                device_id=device_id,
                port_index=item["port_index"],
                name=item["name"],
                status=item["status"],
                speed_mbps=item["speed_mbps"],
                physical=item.get("physical", 1),
                alias=item["alias"],
                remark=remark_map.get(item["port_index"], ""),
            ))
    for p in existing:
        if p.port_index not in seen:
            await db.delete(p)


@router.get("/network/{device_id}/ports")
async def list_ports(device_id: int, db: AsyncSession = Depends(get_db)):
    """端口明细列表 (含用户备注)。"""
    result = await db.execute(
        select(SwitchPort)
        .where(SwitchPort.device_id == device_id)
        .order_by(SwitchPort.port_index)
    )
    return [
        {
            "port_index": p.port_index,
            "name": p.name,
            "status": p.status,
            "speed_mbps": p.speed_mbps,
            "physical": p.physical,
            "alias": p.alias,
            "remark": p.remark,
            "updated_at": p.updated_at,
        }
        for p in result.scalars().all()
    ]


@router.post("/network/{device_id}/ports/{port_index}/test")
async def test_port(device_id: int, port_index: int, db: AsyncSession = Depends(get_db)):
    """单端口状态实时测试, 并更新数据库中的状态。"""
    device = await db.get(NetworkDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")

    status = await get_port_status(
        device.ip, device.snmp_community, device.snmp_version, port_index
    )
    if status is None:
        return {"ok": False, "status": None, "detail": "查询失败, 设备不可达或端口不存在"}

    result = await db.execute(
        select(SwitchPort).where(
            SwitchPort.device_id == device_id, SwitchPort.port_index == port_index
        )
    )
    port = result.scalar_one_or_none()
    if port:
        port.status = status
    await db.commit()
    return {"ok": True, "status": status, "detail": f"端口当前状态: {status}"}


@router.put("/network/{device_id}/ports/{port_index}/remark")
async def update_port_remark(
    device_id: int, port_index: int, data: PortRemarkIn,
    db: AsyncSession = Depends(get_db),
):
    """编辑端口备注 (用途/去向)。"""
    result = await db.execute(
        select(SwitchPort).where(
            SwitchPort.device_id == device_id, SwitchPort.port_index == port_index
        )
    )
    port = result.scalar_one_or_none()
    if not port:
        raise HTTPException(status_code=404, detail="端口不存在, 请先SNMP轮询")
    port.remark = data.remark
    await db.commit()
    return {"ok": True}


# ---------- Storage ----------
@router.get("/storage", response_model=List[StorageDeviceOut])
async def list_storage(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDevice).order_by(StorageDevice.id))
    return result.scalars().all()


@router.post("/storage", response_model=StorageDeviceOut)
async def add_storage(data: StorageDeviceCreate, db: AsyncSession = Depends(get_db)):
    device = StorageDevice(**data.model_dump())
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.put("/storage/{device_id}")
async def update_storage(
    device_id: int, data: StorageDeviceCreate, db: AsyncSession = Depends(get_db)
):
    device = await db.get(StorageDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")
    for k, v in data.model_dump().items():
        setattr(device, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/storage/{device_id}")
async def delete_storage(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await db.get(StorageDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")
    await db.delete(device)
    await db.commit()
    return {"ok": True}


@router.post("/storage/{device_id}/poll")
async def poll_storage(device_id: int, db: AsyncSession = Depends(get_db)):
    """按协议(SNMP/SMI-S)采集存储容量与明细。"""
    device = await db.get(StorageDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="不存在")

    data = await collect_storage(
        device.protocol, device.ip,
        device.snmp_community, device.snmp_version,
        device.username, device.password,
    )

    if data.get("reachable"):
        device.status = "online"
        device.last_seen = datetime.utcnow()
        if data["capacity_tb"]:
            device.capacity_tb = data["capacity_tb"]
            device.used_tb = data["used_tb"]
            device.used_percent = data["used_percent"]
        device.details = data["details"]
        await db.commit()
        return {"ok": True, "data": data}

    device.status = "offline"
    await db.commit()
    detail = data.get("error") or "设备不可达或协议/凭据不正确"
    return {"ok": False, "detail": detail}


# ---------- Env sensors ----------
@router.get("/env", response_model=List[EnvSensorOut])
async def list_env_sensors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EnvSensor).order_by(EnvSensor.id))
    return result.scalars().all()


@router.post("/env", response_model=EnvSensorOut)
async def add_env_sensor(data: EnvSensorCreate, db: AsyncSession = Depends(get_db)):
    sensor = EnvSensor(**data.model_dump())
    db.add(sensor)
    await db.commit()
    await db.refresh(sensor)
    return sensor


@router.delete("/env/{sensor_id}")
async def delete_env_sensor(sensor_id: int, db: AsyncSession = Depends(get_db)):
    sensor = await db.get(EnvSensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="不存在")
    await db.delete(sensor)
    await db.commit()
    return {"ok": True}


@router.post("/env/{sensor_id}/push")
async def push_env_reading(
    sensor_id: int,
    temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
):
    """External sensor gateway pushes readings here (or manual entry)."""
    sensor = await db.get(EnvSensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="不存在")

    sensor.temperature = temperature
    sensor.humidity = humidity
    sensor.status = "online"
    sensor.last_seen = datetime.utcnow()

    db.add(EnvReading(
        sensor_id=sensor_id,
        temperature=temperature,
        humidity=humidity,
        collected_at=datetime.utcnow(),
    ))
    await evaluate_env_reading(db, sensor.name, temperature, humidity)
    await db.commit()
    return {"ok": True}


@router.get("/env/{sensor_id}/history", response_model=List[EnvReadingOut])
async def env_history(
    sensor_id: int, hours: int = 24, db: AsyncSession = Depends(get_db)
):
    hours = min(max(hours, 1), 24 * 90)  # 最长支持查询90天
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(EnvReading)
        .where(EnvReading.sensor_id == sensor_id, EnvReading.collected_at >= since)
        .order_by(EnvReading.collected_at)
    )
    rows = result.scalars().all()
    # 长时间范围自动降采样, 最多返回约2000个点
    step = max(1, len(rows) // 2000)
    if step > 1:
        rows = rows[::step] + (rows[-1:] if (len(rows) - 1) % step else [])
    return rows
