"""Network device / storage / env sensor APIs."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import (
    NetworkDevice, SwitchPort, StorageDevice, EnvSensor, EnvReading,
    SwitchPortMetric, TopologyRelation, RootCauseAnalysis, KnowledgeBase,
    WorkflowDefinition, WorkflowExecution,
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
from app.services.port_traffic_service import PortTrafficService
from app.services.topology_service import TopologyDiscoveryService
from app.services.rca_service import RootCauseAnalysisService
from app.services.knowledge_service import KnowledgeService
from app.services.workflow_service import WorkflowService

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


# ---------- Port traffic history ----------
@router.get("/network/{device_id}/ports/{port_index}/traffic")
async def get_port_traffic_history(
    device_id: int,
    port_index: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    """获取端口流量历史数据"""
    hours = min(max(hours, 1), 24 * 7)  # 最长支持查询7天
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    # 检查端口是否存在
    port_result = await db.execute(
        select(SwitchPort).where(
            SwitchPort.device_id == device_id,
            SwitchPort.port_index == port_index
        )
    )
    port = port_result.scalar_one_or_none()
    if not port:
        raise HTTPException(status_code=404, detail="端口不存在")
    
    # 获取流量历史数据
    history = PortTrafficService.get_port_traffic_history(
        device_id, port_index, start_time, end_time
    )
    
    return {
        "port": {
            "id": port.id,
            "name": port.name,
            "status": port.status,
            "speed_mbps": port.speed_mbps,
        },
        "device_id": device_id,
        "port_index": port_index,
        "period_hours": hours,
        "history": history
    }


@router.get("/network/{device_id}/ports/{port_index}/traffic/summary")
async def get_port_traffic_summary(
    device_id: int,
    port_index: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    """获取端口流量统计摘要"""
    # 检查端口是否存在
    port_result = await db.execute(
        select(SwitchPort).where(
            SwitchPort.device_id == device_id,
            SwitchPort.port_index == port_index
        )
    )
    port = port_result.scalar_one_or_none()
    if not port:
        raise HTTPException(status_code=404, detail="端口不存在")
    
    # 获取流量统计
    summary = PortTrafficService.get_port_traffic_summary(device_id, port_index, hours)
    
    return {
        "port": {
            "id": port.id,
            "name": port.name,
            "status": port.status,
            "speed_mbps": port.speed_mbps,
        },
        "device_id": device_id,
        "port_index": port_index,
        "summary": summary
    }


@router.get("/network/{device_id}/ports/traffic/latest")
async def get_all_ports_latest_traffic(
    device_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取设备所有端口的最新流量数据"""
    # 检查设备是否存在
    device_result = await db.execute(
        select(NetworkDevice).where(NetworkDevice.id == device_id)
    )
    device = device_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    
    # 获取所有端口最新流量数据
    ports_traffic = PortTrafficService.get_all_ports_with_latest_traffic(device_id)
    
    return {
        "device": {
            "id": device.id,
            "name": device.name,
            "ip": device.ip,
            "vendor": device.vendor,
        },
        "ports": ports_traffic
    }


# ---------- Topology Management ----------
@router.post("/topology/discover")
async def discover_topology(db: AsyncSession = Depends(get_db)):
    """自动发现拓扑关系"""
    result = await TopologyDiscoveryService.discover_topology(db)
    return result


@router.get("/topology/graph")
async def get_topology_graph(
    device_type: Optional[str] = None,
    device_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取拓扑关系图"""
    graph = await TopologyDiscoveryService.get_topology_graph(device_type, device_id)
    return graph


@router.get("/topology/{device_type}/{device_id}/blast-radius")
async def get_blast_radius(
    device_type: str,
    device_id: int,
    db: AsyncSession = Depends(get_db)
):
    """计算设备影响面（爆炸半径）"""
    result = await TopologyDiscoveryService.get_blast_radius(device_type, device_id)
    return result


@router.post("/topology/relation")
async def add_topology_relation(
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    relation_type: str,
    strength: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None
):
    """手动添加拓扑关系"""
    result = await TopologyDiscoveryService.manual_add_relation(
        source_type, source_id, target_type, target_id, relation_type, strength, metadata
    )
    return {"success": result}


# ---------- Root Cause Analysis ----------
@router.post("/rca/analyze/{alert_id}")
async def analyze_root_cause(alert_id: int):
    """对告警进行根因分析"""
    result = await RootCauseAnalysisService.analyze_root_cause(alert_id)
    return result


@router.get("/rca/history")
async def get_rca_history(limit: int = 10):
    """获取根因分析历史"""
    history = await RootCauseAnalysisService.get_analysis_history(limit)
    return history


@router.get("/rca/{analysis_id}")
async def get_rca_details(analysis_id: int):
    """获取根因分析详情"""
    result = await RootCauseAnalysisService.get_analysis_details(analysis_id)
    return result


# ---------- Knowledge Base ----------
@router.get("/knowledge/search")
async def search_knowledge(
    query: str,
    category: Optional[str] = None,
    limit: int = 10
):
    """搜索知识库"""
    result = await KnowledgeService.search_knowledge(query, category, None, limit)
    return result


@router.post("/knowledge/learn")
async def add_knowledge(
    title: str,
    content: str,
    category: str,
    tags: Optional[str] = None,
    source: Optional[str] = None
):
    """添加知识库条目"""
    result = await KnowledgeService.add_knowledge(title, content, category, tags, source)
    return result


@router.post("/knowledge/learn-from-incident/{incident_id}")
async def learn_from_incident(incident_id: int):
    """从故障案例中学习"""
    result = await KnowledgeService.learn_from_incident(incident_id)
    return result


@router.get("/knowledge/similar-incidents")
async def get_similar_incidents(
    title: str,
    level: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 5
):
    """查找相似的历史故障案例"""
    current_incident = {
        "title": title,
        "level": level,
        "source": source
    }
    result = await KnowledgeService.get_similar_incidents(current_incident, limit)
    return result


@router.get("/knowledge/solutions")
async def get_solution_recommendations(
    alert_id: int
):
    """获取解决方案建议"""
    # 获取告警信息
    db = AsyncSessionLocal()
    try:
        from app.models import Alert
        result = await db.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        
        if not alert:
            return {"error": "Alert not found"}
        
        result = await KnowledgeService.generate_solution_recommendations(alert)
        return result
    finally:
        await db.close()


@router.get("/knowledge/statistics")
async def get_knowledge_statistics():
    """获取知识库统计信息"""
    result = await KnowledgeService.get_knowledge_statistics()
    return result


# ---------- Workflow Management ----------
@router.get("/workflows")
async def get_workflows():
    """获取工作流列表"""
    db = AsyncSessionLocal()
    try:
        result = await db.execute(
            select(WorkflowDefinition)
            .where(WorkflowDefinition.status == "active")
            .order_by(desc(WorkflowDefinition.created_at))
        )
        workflows = result.scalars().all()
        
        workflow_list = []
        for workflow in workflows:
            workflow_list.append({
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status,
                "created_by": workflow.created_by,
                "created_at": workflow.created_at.isoformat(),
                "updated_at": workflow.updated_at.isoformat()
            })
        
        return {
            "workflows": workflow_list,
            "total": len(workflow_list)
        }
    finally:
        await db.close()


@router.post("/workflows")
async def create_workflow(
    name: str,
    description: str,
    definition: Dict[str, Any]
):
    """创建工作流"""
    result = await WorkflowService.create_workflow(name, description, definition)
    return result


@router.get("/workflows/templates")
async def get_workflow_templates():
    """获取工作流模板"""
    templates = await WorkflowService.get_workflow_templates()
    return {"templates": templates}


@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(workflow_id: int, trigger_data: Optional[Dict[str, Any]] = None):
    """执行工作流"""
    result = await WorkflowService.execute_workflow(workflow_id, trigger_data)
    return result


@router.get("/workflows/{workflow_id}/executions")
async def get_workflow_executions(workflow_id: int, limit: int = 10):
    """获取工作流执行历史"""
    result = await WorkflowService.get_workflow_executions(workflow_id, limit)
    return result


@router.get("/workflows/{workflow_id}/executions/{execution_id}")
async def get_execution_details(workflow_id: int, execution_id: int):
    """获取执行详情"""
    result = await WorkflowService.get_execution_details(execution_id)
    return result


@router.get("/workflows/{workflow_id}/status")
async def get_workflow_status(workflow_id: int):
    """获取工作流状态"""
    db = AsyncSessionLocal()
    try:
        result = await db.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return {"error": "Workflow not found"}
        
        # 获取执行统计
        exec_result = await db.execute(
            select(func.count(WorkflowExecution.id), func.max(WorkflowExecution.started_at))
            .where(WorkflowExecution.workflow_id == workflow_id)
        )
        stats = exec_result.fetchone()
        
        return {
            "workflow": {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status,
                "created_at": workflow.created_at.isoformat()
            },
            "statistics": {
                "total_executions": stats[0] or 0,
                "last_execution": stats[1].isoformat() if stats[1] else None,
                "success_rate": 0.0  # 需要计算成功率
            }
        }
    finally:
        await db.close()
