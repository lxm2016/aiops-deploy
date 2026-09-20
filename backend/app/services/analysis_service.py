"""智能分析服务 - 提供设备状态智能分析和报告生成"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    Server, NetworkDevice, StorageDevice, VmwareHost, VirtualMachine,
    Alert, EnvSensor, SwitchPort, SwitchPortMetric
)
from app.services.llm_service import chat_completion


class AnalysisService:
    """智能分析服务"""
    
    @staticmethod
    async def analyze_server_status(db: AsyncSession) -> Dict[str, Any]:
        """分析服务器状态"""
        result = await db.execute(
            select(Server).where(Server.status.in_(["online", "offline"]))
        )
        servers = result.scalars().all()
        
        analysis = {
            "summary": {
                "total": len(servers),
                "online": len([s for s in servers if s.status == "online"]),
                "offline": len([s for s in servers if s.status == "offline"]),
                "with_agent": len([s for s in servers if s.agent_installed]),
            },
            "normal_servers": [],
            "offline_servers": [],
            "warning_servers": []
        }
        
        for server in servers:
            server_info = {
                "id": server.id,
                "name": server.name,
                "ip": server.ip,
                "os_type": server.os_type,
                "status": server.status,
                "agent_installed": server.agent_installed,
                "last_seen": server.last_seen.isoformat() if server.last_seen else None,
            }
            
            if server.status == "online" and server.agent_installed:
                analysis["normal_servers"].append(server_info)
            elif server.status == "offline":
                analysis["offline_servers"].append(server_info)
            else:
                analysis["warning_servers"].append(server_info)
        
        return analysis
    
    @staticmethod
    async def analyze_network_device_status(db: AsyncSession) -> Dict[str, Any]:
        """分析网络设备状态"""
        result = await db.execute(
            select(NetworkDevice).where(NetworkDevice.status.in_(["online", "offline"]))
        )
        devices = result.scalars().all()
        
        analysis = {
            "summary": {
                "total": len(devices),
                "online": len([d for d in devices if d.status == "online"]),
                "offline": len([d for d in devices if d.status == "offline"]),
            },
            "normal_devices": [],
            "offline_devices": []
        }
        
        for device in devices:
            device_info = {
                "id": device.id,
                "name": device.name,
                "ip": device.ip,
                "vendor": device.vendor,
                "status": device.status,
                "cpu_percent": device.cpu_percent,
                "mem_percent": device.mem_percent,
                "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            }
            
            if device.status == "online":
                analysis["normal_devices"].append(device_info)
            else:
                analysis["offline_devices"].append(device_info)
        
        return analysis
    
    @staticmethod
    async def generate_intelligent_analysis(
        analysis_type: str, 
        session_id: str,
        db: AsyncSession
    ) -> str:
        """生成智能分析报告"""
        
        # 构建分析上下文
        context_parts = []
        
        if analysis_type in ["server", "all"]:
            server_analysis = await AnalysisService.analyze_server_status(db)
            context_parts.append("🖥️ **服务器状态分析**:")
            context_parts.append(f"总数: {server_analysis['summary']['total']}")
            context_parts.append(f"正常: {server_analysis['summary']['online']} (已安装Agent: {server_analysis['summary']['with_agent']})")
            context_parts.append(f"离线: {server_analysis['summary']['offline']}")
            
            if server_analysis['offline_servers']:
                offline_names = [s['name'] for s in server_analysis['offline_servers'][:3]]
                context_parts.append(f"离线服务器: {', '.join(offline_names)}")
            
            context_parts.append("")
        
        if analysis_type in ["network", "all"]:
            network_analysis = await AnalysisService.analyze_network_device_status(db)
            context_parts.append("🌐 **网络设备状态分析**:")
            context_parts.append(f"总数: {network_analysis['summary']['total']}")
            context_parts.append(f"在线: {network_analysis['summary']['online']}")
            context_parts.append(f"离线: {network_analysis['summary']['offline']}")
            
            if network_analysis['normal_devices'] and len(network_analysis['normal_devices']) <= 5:
                device_names = [f"{d['name']}(CPU:{d['cpu_percent']}%)" for d in network_analysis['normal_devices']]
                context_parts.append(f"在线设备: {', '.join(device_names)}")
            
            context_parts.append("")
        
        # 告警分析
        result = await db.execute(
            select(Alert).where(Alert.status == "open")
            .order_by(Alert.created_at.desc()).limit(10)
        )
        alerts = result.scalars().all()
        
        if alerts:
            context_parts.append("🚨 **当前告警分析**:")
            critical_alerts = [a for a in alerts if a.level == "critical"]
            warning_alerts = [a for a in alerts if a.level == "warning"]
            
            context_parts.append(f"严重告警: {len(critical_alerts)} 条")
            context_parts.append(f"警告告警: {len(warning_alerts)} 条")
            
            if critical_alerts:
                for alert in critical_alerts[:3]:
                    context_parts.append(f"- {alert.source}: {alert.title}")
            context_parts.append("")
        
        context = "\n".join(context_parts)
        
        # 生成分析报告
        if analysis_type == "server":
            prompt = f"""请基于以下服务器监控数据，进行详细的状态分析，并列出哪些正常、哪些异常：

{context}

请提供：
1. 服务器状态总体评估
2. 正常服务器列表及状态
3. 异常服务器分析（离线、Agent未安装等）
4. 具体的处理建议和排查步骤
5. 优化建议

使用Markdown格式，结构清晰。"""
        
        elif analysis_type == "network":
            prompt = f"""请基于以下网络设备监控数据，进行详细的状态分析：

{context}

请提供：
1. 网络设备状态总体评估
2. 在线设备健康状况分析
3. 离线设备问题诊断
4. 网络性能优化建议
5. 具体的排查和处理步骤

使用Markdown格式，结构清晰。"""
        
        else:  # all
            prompt = f"""请基于以下完整的IT基础设施监控数据，进行全面的状态分析和评估：

{context}

请提供：
1. 整体IT基础设施状态评估
2. 服务器状态分析及建议
3. 网络设备状态分析及建议
4. 告警处理优先级建议
5. 整体优化建议和后续行动计划

使用Markdown格式，包含表格和列表，结构清晰。重点关注问题的根本原因和解决方案。"""
        
        return await chat_completion(prompt, session_id=session_id)
    
    @staticmethod
    async def get_server_detailed_report(server_id: int, db: AsyncSession) -> Dict[str, Any]:
        """获取服务器详细报告"""
        server = await db.get(Server, server_id)
        if not server:
            return {}
        
        # 获取服务器最近24小时的指标
        from app.models import ServerMetric
        from datetime import datetime, timedelta
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        
        result = await db.execute(
            select(ServerMetric).where(
                ServerMetric.server_id == server_id,
                ServerMetric.collected_at >= start_time
            ).order_by(ServerMetric.collected_at.desc()).limit(100)
        )
        metrics = result.scalars().all()
        
        # 计算统计信息
        if metrics:
            avg_cpu = sum(m.cpu_percent for m in metrics) / len(metrics)
            avg_mem = sum(m.mem_percent for m in metrics) / len(metrics)
            max_cpu = max(m.cpu_percent for m in metrics)
            max_mem = max(m.mem_percent for m in metrics)
        else:
            avg_cpu = avg_mem = max_cpu = max_mem = 0
        
        return {
            "server": {
                "id": server.id,
                "name": server.name,
                "ip": server.ip,
                "os_type": server.os_type,
                "status": server.status,
                "agent_installed": server.agent_installed,
            },
            "metrics_summary": {
                "avg_cpu_percent": round(avg_cpu, 2),
                "avg_mem_percent": round(avg_mem, 2),
                "max_cpu_percent": round(max_cpu, 2),
                "max_mem_percent": round(max_mem, 2),
                "data_points": len(metrics),
                "period_hours": 24,
            },
            "latest_metrics": metrics[:5] if metrics else []
        }