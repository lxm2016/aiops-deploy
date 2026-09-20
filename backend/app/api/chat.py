"""AI assistant chat API backed by internal Qwen model."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import ChatMessage, Server, Alert, NetworkDevice, EnvSensor, SwitchPort, VmwareHost, VirtualMachine
from app.schemas.schemas import ChatRequest, ChatResponse
from app.services.llm_service import chat_completion
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/api/chat", tags=["chat"])


async def _build_monitoring_context(db: AsyncSession) -> str:
    """Build a comprehensive monitoring context with detailed analysis for the LLM."""
    parts = []

    # Server detailed analysis
    result = await db.execute(
        select(Server).where(Server.status.in_(["online", "offline"])).order_by(Server.name)
    )
    servers = result.scalars().all()
    
    if servers:
        normal_servers = []
        warning_servers = []
        critical_servers = []
        
        for server in servers:
            # 基于服务器状态分类
            if server.status == "online" and server.agent_installed:
                normal_servers.append(server)
            elif server.status == "offline":
                critical_servers.append(server)
            else:
                warning_servers.append(server)
        
        parts.append(f"🖥️ 服务器状态分析 (总数: {len(servers)}):")
        parts.append(f"  ✅ 正常: {len(normal_servers)} 台")
        parts.append(f"  ⚠️  警告: {len(warning_servers)} 台")
        parts.append(f"  ❌ 严重: {len(critical_servers)} 台")
        
        if normal_servers:
            server_names = [s.name for s in normal_servers[:5]]
            parts.append(f"  正常服务器: {', '.join(server_names)}{'...' if len(normal_servers) > 5 else ''}")
        
        if critical_servers:
            server_names = [s.name for s in critical_servers[:3]]
            parts.append(f"  离线服务器: {', '.join(server_names)}{'...' if len(critical_servers) > 3 else ''}")

    # Network devices analysis
    result = await db.execute(
        select(NetworkDevice).where(NetworkDevice.status.in_(["online", "offline"])).order_by(NetworkDevice.name)
    )
    devices = result.scalars().all()
    
    if devices:
        parts.append(f"🌐 网络设备状态 (总数: {len(devices)}):")
        online_devices = [d for d in devices if d.status == "online"]
        offline_devices = [d for d in devices if d.status == "offline"]
        
        parts.append(f"  ✅ 在线: {len(online_devices)} 台")
        parts.append(f"  ❌ 离线: {len(offline_devices)} 台")
        
        if online_devices and len(online_devices) <= 5:
            device_names = [f"{d.name}(CPU:{d.cpu_percent}%, 内存:{d.mem_percent}%)" for d in online_devices]
            parts.append(f"  在线设备: {', '.join(device_names)}")

    # Virtual machines analysis
    result = await db.execute(select(VmwareHost))
    vmware_hosts = result.scalars().all()
    
    if vmware_hosts:
        online_hosts = [h for h in vmware_hosts if h.status == "online"]
        parts.append(f"🔄 VMware主机 (总数: {len(vmware_hosts)}, 在线: {len(online_hosts)})")
        
        # Get VM summary
        total_vms = 0
        powered_on_vms = 0
        for host in online_hosts[:3]:  # Only check first 3 hosts
            vms_result = await db.execute(
                select(VirtualMachine).where(VirtualMachine.host_id == host.id)
            )
            vms = vms_result.scalars().all()
            total_vms += len(vms)
            powered_on_vms += len([vm for vm in vms if vm.power_state == "poweredOn"])
        
        if total_vms > 0:
            parts.append(f"  虚拟机总数: {total_vms}, 运行中: {powered_on_vms}")

    # Open alerts analysis
    result = await db.execute(
        select(Alert).where(Alert.status == "open")
        .order_by(Alert.created_at.desc()).limit(10)
    )
    alerts = result.scalars().all()
    
    if alerts:
        parts.append(f"🚨 当前告警 (共 {len(alerts)} 条):")
        critical_alerts = [a for a in alerts if a.level == "critical"]
        warning_alerts = [a for a in alerts if a.level == "warning"]
        info_alerts = [a for a in alerts if a.level == "info"]
        
        parts.append(f"  🔴 严重: {len(critical_alerts)} 条")
        parts.append(f"  🟡 警告: {len(warning_alerts)} 条")
        parts.append(f"  🔵 信息: {len(info_alerts)} 条")
        
        if critical_alerts:
            for alert in critical_alerts[:3]:
                parts.append(f"    - {alert.source}: {alert.title}")

    # Environment monitoring
    result = await db.execute(select(EnvSensor).where(EnvSensor.status == "online"))
    sensors = result.scalars().all()
    
    if sensors:
        parts.append(f"🌡️ 环境监控 (在线传感器: {len(sensors)}):")
        normal_sensors = []
        alert_sensors = []
        
        for sensor in sensors:
            if sensor.temperature and sensor.humidity:
                if sensor.temperature > 30 or sensor.humidity > 80:
                    alert_sensors.append(sensor)
                else:
                    normal_sensors.append(sensor)
        
        if normal_sensors:
            sensor_names = [f"{s.name}({s.temperature}°C/{s.humidity}%)" for s in normal_sensors[:3]]
            parts.append(f"  正常: {', '.join(sensor_names)}")
        
        if alert_sensors:
            sensor_names = [f"{s.name}({s.temperature}°C/{s.humidity}%)" for s in alert_sensors[:3]]
            parts.append(f"  异常: {', '.join(sensor_names)}")

    # Storage devices analysis
    result = await db.execute(
        select(StorageDevice).where(StorageDevice.status.in_(["online", "offline"]))
    )
    storage_devices = result.scalars().all()
    
    if storage_devices:
        parts.append(f"💾 存储设备 (总数: {len(storage_devices)}):")
        online_storage = [d for d in storage_devices if d.status == "online"]
        offline_storage = [d for d in storage_devices if d.status == "offline"]
        
        parts.append(f"  ✅ 在线: {len(online_storage)} 台")
        parts.append(f"  ❌ 离线: {len(offline_storage)} 台")
        
        if online_storage:
            storage_names = [f"{d.name}(使用率:{d.used_percent}%)" for d in online_storage[:3]]
            parts.append(f"  在线存储: {', '.join(storage_names)}")

    return "\n".join(parts)


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Chat with the AI ops assistant. Injects live monitoring context."""
    # Load history
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == req.session_id)
        .order_by(ChatMessage.id.desc())
        .limit(10)
    )
    history_msgs = list(reversed(result.scalars().all()))
    history = [{"role": m.role, "content": m.content} for m in history_msgs]

    # Save user message
    db.add(ChatMessage(session_id=req.session_id, role="user", content=req.message))

    context = await _build_monitoring_context(db)
    reply = await chat_completion(req.message, history=history, context=context)

    db.add(ChatMessage(session_id=req.session_id, role="assistant", content=reply))
    await db.commit()

    return ChatResponse(reply=reply, session_id=req.session_id)


@router.get("/history/{session_id}")
async def get_history(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    )
    msgs = result.scalars().all()
    return [{"role": m.role, "content": m.content, "time": m.created_at} for m in msgs]


@router.post("/analyze/server")
async def analyze_server_status(session_id: str, db: AsyncSession = Depends(get_db)):
    """分析服务器状态并生成智能报告"""
    analysis = await AnalysisService.analyze_server_status(db)
    report = await AnalysisService.generate_intelligent_analysis("server", session_id, db)
    
    return {
        "analysis": analysis,
        "report": report,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.post("/analyze/network")
async def analyze_network_status(session_id: str, db: AsyncSession = Depends(get_db)):
    """分析网络设备状态并生成智能报告"""
    analysis = await AnalysisService.analyze_network_device_status(db)
    report = await AnalysisService.generate_intelligent_analysis("network", session_id, db)
    
    return {
        "analysis": analysis,
        "report": report,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.post("/analyze/overview")
async def analyze_overview(session_id: str, db: AsyncSession = Depends(get_db)):
    """生成完整的IT基础设施状态分析报告"""
    report = await AnalysisService.generate_intelligent_analysis("all", session_id, db)
    
    return {
        "report": report,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/server/{server_id}/report")
async def get_server_report(server_id: int, db: AsyncSession = Depends(get_db)):
    """获取服务器详细分析报告"""
    report = await AnalysisService.get_server_detailed_report(server_id, db)
    return report
