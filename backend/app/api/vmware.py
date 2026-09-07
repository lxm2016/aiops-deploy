"""VMware monitoring API."""
import asyncio
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import VmwareHost, VirtualMachine
from app.schemas.schemas import VmwareHostCreate, VmwareHostOut, VirtualMachineOut
from app.services.vmware_service import collect_vmware_data

router = APIRouter(prefix="/api/vmware", tags=["vmware"])


@router.get("/hosts", response_model=List[VmwareHostOut])
async def list_hosts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VmwareHost).order_by(VmwareHost.id))
    return result.scalars().all()


@router.post("/hosts", response_model=VmwareHostOut)
async def add_host(data: VmwareHostCreate, db: AsyncSession = Depends(get_db)):
    host = VmwareHost(**data.model_dump())
    db.add(host)
    await db.commit()
    await db.refresh(host)
    return host


@router.delete("/hosts/{host_id}")
async def delete_host(host_id: int, db: AsyncSession = Depends(get_db)):
    host = await db.get(VmwareHost, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="不存在")
    await db.delete(host)
    await db.commit()
    return {"ok": True}


async def upsert_vms(db: AsyncSession, host_id: int, vms: list):
    """Upsert VM records for a host; remove VMs no longer present."""
    result = await db.execute(
        select(VirtualMachine).where(VirtualMachine.host_id == host_id)
    )
    existing = {vm.name: vm for vm in result.scalars().all()}

    for vm_data in vms:
        name = vm_data["name"]
        if name in existing:
            vm = existing.pop(name)
        else:
            vm = VirtualMachine(host_id=host_id, name=name)
            db.add(vm)
        vm.power_state = vm_data.get("power_state", "unknown")
        vm.guest_os = vm_data.get("guest_os", "")
        vm.ip = vm_data.get("ip", "")
        vm.cpu_cores = vm_data.get("cpu_cores", 0)
        vm.mem_mb = vm_data.get("mem_mb", 0)
        vm.cpu_percent = vm_data.get("cpu_percent", 0.0)
        vm.mem_percent = vm_data.get("mem_percent", 0.0)
        vm.uptime = vm_data.get("uptime", "")
        vm.last_seen = datetime.utcnow()

    for vm in existing.values():
        await db.delete(vm)

    await db.commit()


@router.post("/hosts/{host_id}/sync")
async def sync_host(host_id: int, db: AsyncSession = Depends(get_db)):
    """Connect to vCenter/ESXi and refresh VM inventory."""
    host = await db.get(VmwareHost, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="不存在")

    data = await asyncio.to_thread(
        collect_vmware_data, host.host, host.username, host.password, host.port
    )
    if data.get("error") and not data.get("vms"):
        host.status = "error"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"连接失败: {data['error']}")

    host.status = "online"
    host.last_sync = datetime.utcnow()
    await upsert_vms(db, host_id, data.get("vms", []))
    return {"ok": True, "vm_count": len(data.get("vms", [])), "hosts": data.get("hosts", [])}


@router.get("/hosts/{host_id}/vms", response_model=List[VirtualMachineOut])
async def list_vms(host_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VirtualMachine).where(VirtualMachine.host_id == host_id)
        .order_by(VirtualMachine.name)
    )
    return result.scalars().all()


@router.get("/vms", response_model=List[VirtualMachineOut])
async def list_all_vms(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VirtualMachine).order_by(VirtualMachine.name))
    return result.scalars().all()
