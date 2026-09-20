"""根因分析服务"""
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from sqlalchemy import and_, func, select, or_, desc
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    RootCauseAnalysis, Alert, Server, NetworkDevice, TopologyRelation,
    ServerMetric, SwitchPortMetric, EnvReading
)
from app.services.analysis_service import AnalysisService
from app.services.llm_service import chat_completion


class RootCauseAnalysisService:
    """根因分析服务"""
    
    @staticmethod
    async def analyze_root_cause(alert_id: int) -> Dict[str, Any]:
        """分析告警的根因"""
        db = AsyncSessionLocal()
        
        try:
            # 获取告警信息
            alert_result = await db.execute(select(Alert).where(Alert.id == alert_id))
            alert = alert_result.scalar_one_or_none()
            if not alert:
                return {"error": "Alert not found"}
            
            # 分析类型
            analysis_type = RootCauseAnalysisService._determine_analysis_type(alert)
            
            # 执行对应的根因分析
            if analysis_type == "topology":
                result = await RootCauseAnalysisService._topology_based_analysis(alert, db)
            elif analysis_type == "correlation":
                result = await RootCauseAnalysisService._correlation_analysis(alert, db)
            elif analysis_type == "anomaly":
                result = await RootCauseAnalysisService._anomaly_analysis(alert, db)
            else:
                result = await RootCauseAnalysisService._generic_analysis(alert, db)
            
            # 保存分析结果
            rca_record = RootCauseAnalysis(
                alert_id=alert_id,
                analysis_type=analysis_type,
                analysis_result=result.get("analysis_result", "{}"),
                confidence_score=result.get("confidence_score", 0.0),
                root_cause=result.get("root_cause", ""),
                affected_services=str(result.get("affected_services", [])),
                recommendations=result.get("recommendations", ""),
                status="completed",
                completed_at=datetime.utcnow()
            )
            
            db.add(rca_record)
            await db.commit()
            
            return {
                "analysis_id": rca_record.id,
                "alert_id": alert_id,
                "analysis_type": analysis_type,
                "confidence_score": result.get("confidence_score", 0.0),
                "root_cause": result.get("root_cause", ""),
                "affected_services": result.get("affected_services", []),
                "recommendations": result.get("recommendations", ""),
                "completed_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            return {"error": str(e)}
        finally:
            await db.close()
    
    @staticmethod
    def _determine_analysis_type(alert: Alert) -> str:
        """根据告警类型确定分析方法"""
        alert_title_lower = alert.title.lower()
        
        # 拓扑相关告警
        if any(keyword in alert_title_lower for keyword in ["connection", "network", "port", "link"]):
            return "topology"
        
        # 相关性分析告警
        elif any(keyword in alert_title_lower for keyword in ["cpu", "memory", "disk", "performance", "slow"]):
            return "correlation"
        
        # 异常检测告警
        elif any(keyword in alert_title_lower for keyword in ["anomaly", "unusual", "unexpected"]):
            return "anomaly"
        
        # 默认通用分析
        else:
            return "generic"
    
    @staticmethod
    async def _topology_based_analysis(alert: Alert, db: AsyncSession) -> Dict[str, Any]:
        """基于拓扑的根因分析"""
        
        # 获取相关设备
        affected_devices = await RootCauseAnalysisService._get_affected_devices(alert, db)
        
        # 分析拓扑关系
        impact_analysis = await RootCauseAnalysisService._analyze_impact_path(affected_devices, db)
        
        # 构建分析上下文
        context = f"""
告警信息:
- 源: {alert.source}
- 级别: {alert.level}
- 标题: {alert.title}
- 时间: {alert.created_at}

影响分析:
- 受影响设备: {len(affected_devices)} 台
- 影响范围: {impact_analysis['impact_scope']}
- 潜在根因: {impact_analysis['potential_causes']}

拓扑分析:
- 关键路径: {len(impact_analysis['critical_paths'])} 条
- 依赖设备: {len(impact_analysis['dependent_devices'])} 台
"""
        
        # 使用AI进行根因分析
        prompt = f"""基于告警信息和拓扑分析，请确定可能的根因并提供建议。

{context}

请提供：
1. 最可能的根因（1-3个）
2. 受影响的具体服务和设备
3. 建议的排查步骤
4. 紧急处理建议
5. 长期解决方案

使用Markdown格式，重点突出根因和解决方案。"""
        
        analysis_result = await chat_completion(prompt, session_id=f"rca_{alert.id}")
        
        return {
            "analysis_result": analysis_result,
            "confidence_score": 0.8,
            "root_cause": impact_analysis.get("root_cause", "拓扑依赖关系故障"),
            "affected_services": impact_analysis["affected_services"],
            "recommendations": analysis_result
        }
    
    @staticmethod
    async def _correlation_analysis(alert: Alert, db: AsyncSession) -> Dict[str, Any]:
        """基于相关性的根因分析"""
        
        # 获取告警相关的时间窗口
        time_window = 10  # 分钟
        start_time = alert.created_at - timedelta(minutes=time_window)
        end_time = alert.created_at + timedelta(minutes=time_window)
        
        # 查询相关的性能指标
        performance_data = await RootCauseAnalysisService._query_performance_metrics(
            alert.source, start_time, end_time, db
        )
        
        # 分析相关性
        correlation_results = await RootCauseAnalysisService._analyze_correlations(
            alert, performance_data, db
        )
        
        # 构建分析上下文
        context = f"""
告警信息:
- 源: {alert.source}
- 级别: {alert.level}
- 标题: {alert.title}
- 时间: {alert.created_at}

性能数据:
- CPU异常: {len(correlation_results['cpu_anomalies'])} 个
- 内存异常: {len(correlation_results['memory_anomalies'])} 个
- 磁盘异常: {len(correlation_results['disk_anomalies'])} 个

相关性分析:
- 强相关指标: {len(correlation_results['strong_correlations'])} 个
- 潜在原因: {correlation_results['potential_causes']}
"""
        
        # 使用AI进行根因分析
        prompt = f"""基于性能指标和相关分析，请确定告警的根本原因。

{context}

请提供：
1. 主要性能瓶颈和根因
2. 相关性最强的指标
3. 具体的排查步骤
4. 性能优化建议
5. 预防措施

使用Markdown格式，包含具体的数值和趋势分析。"""
        
        analysis_result = await chat_completion(prompt, session_id=f"rca_{alert.id}")
        
        return {
            "analysis_result": analysis_result,
            "confidence_score": 0.85,
            "root_cause": correlation_results.get("root_cause", "性能资源瓶颈"),
            "affected_services": correlation_results["affected_services"],
            "recommendations": analysis_result
        }
    
    @staticmethod
    async def _anomaly_analysis(alert: Alert, db: AsyncSession) -> Dict[str, Any]:
        """异常检测的根因分析"""
        
        # 分析异常模式
        anomaly_patterns = await RootCauseAnalysisService._analyze_anomaly_patterns(alert, db)
        
        # 历史对比分析
        historical_comparison = await RootCauseAnalysisService._compare_with_history(alert, db)
        
        context = f"""
告警信息:
- 源: {alert.source}
- 级别: {alert.level}
- 标题: {alert.title}
- 时间: {alert.created_at}

异常分析:
- 异常类型: {anomaly_patterns['anomaly_type']}
- 异常程度: {anomaly_patterns['severity']}
- 模式匹配: {len(anomaly_patterns['matched_patterns'])} 个模式

历史对比:
- 同期对比: {historical_comparison['period_comparison']}
- 趋势分析: {historical_comparison['trend_analysis']}
"""
        
        # 使用AI进行根因分析
        prompt = f"""基于异常检测和历史对比分析，请确定异常的根因。

{context}

请提供：
1. 异常的根本原因
2. 与历史数据的对比分析
3. 潜在的风险评估
4. 具体的排查步骤
5. 预防和缓解措施

使用Markdown格式，重点突出异常模式和风险分析。"""
        
        analysis_result = await chat_completion(prompt, session_id=f"rca_{alert.id}")
        
        return {
            "analysis_result": analysis_result,
            "confidence_score": 0.75,
            "root_cause": anomaly_patterns.get("root_cause", "系统异常行为"),
            "affected_services": anomaly_patterns["affected_services"],
            "recommendations": analysis_result
        }
    
    @staticmethod
    async def _generic_analysis(alert: Alert, db: AsyncSession) -> Dict[str, Any]:
        """通用根因分析"""
        
        # 获取系统整体状态
        system_context = await AnalysisService._build_monitoring_context(db)
        
        # 生成通用分析
        context = f"""
告警信息:
- 源: {alert.source}
- 级别: {alert.level}
- 标题: {alert.title}
- 时间: {alert.created_at}

系统状态:
{system_context}
"""
        
        prompt = f"""基于告警信息和系统状态，请进行根因分析。

{context}

请提供：
1. 可能的根因分析
2. 受影响的服务和设备
3. 建议的排查步骤
4. 处理建议和预防措施

使用Markdown格式，结构清晰。"""
        
        analysis_result = await chat_completion(prompt, session_id=f"rca_{alert.id}")
        
        return {
            "analysis_result": analysis_result,
            "confidence_score": 0.7,
            "root_cause": "待进一步分析",
            "affected_services": [],
            "recommendations": analysis_result
        }
    
    @staticmethod
    async def _get_affected_devices(alert: Alert, db: AsyncSession) -> List[Dict[str, Any]]:
        """获取受影响的设备"""
        affected_devices = []
        
        # 根据告警源确定受影响设备
        if alert.source.startswith("server-"):
            # 服务器告警
            server_id = int(alert.source.split("-")[1])
            server_result = await db.execute(select(Server).where(Server.id == server_id))
            server = server_result.scalar_one_or_none()
            if server:
                affected_devices.append({
                    "type": "server",
                    "id": server.id,
                    "name": server.name,
                    "ip": server.ip
                })
        
        elif alert.source.startswith("network-"):
            # 网络设备告警
            device_id = int(alert.source.split("-")[1])
            device_result = await db.execute(select(NetworkDevice).where(NetworkDevice.id == device_id))
            device = device_result.scalar_one_or_none()
            if device:
                affected_devices.append({
                    "type": "network",
                    "id": device.id,
                    "name": device.name,
                    "ip": device.ip
                })
        
        return affected_devices
    
    @staticmethod
    async def _analyze_impact_path(affected_devices: List[Dict], db: AsyncSession) -> Dict[str, Any]:
        """分析影响路径"""
        impact_analysis = {
            "impact_scope": "limited",
            "potential_causes": [],
            "critical_paths": [],
            "dependent_devices": [],
            "affected_services": []
        }
        
        for device in affected_devices:
            # 查找依赖于该设备的其他设备
            dependent_relations = await db.execute(
                select(TopologyRelation).where(
                    and_(
                        TopologyRelation.target_type == device["type"],
                        TopologyRelation.target_id == device["id"]
                    )
                )
            )
            dependents = dependent_relations.scalars().all()
            
            for relation in dependents:
                impact_analysis["dependent_devices"].append({
                    "type": relation.source_type,
                    "id": relation.source_id,
                    "relation": relation.relation_type,
                    "strength": relation.strength
                })
                
                # 关键路径
                if relation.relation_type == "depends_on" and relation.strength > 0.8:
                    impact_analysis["critical_paths"].append({
                        "path": f"{device['type']}_{device['id']} -> {relation.source_type}_{relation.source_id}",
                        "criticality": "high"
                    })
        
        # 计算影响范围
        if len(impact_analysis["dependent_devices"]) > 10:
            impact_analysis["impact_scope"] = "large"
        elif len(impact_analysis["dependent_devices"]) > 5:
            impact_analysis["impact_scope"] = "medium"
        
        impact_analysis["root_cause"] = "设备故障导致服务中断"
        impact_analysis["affected_services"] = [d["id"] for d in impact_analysis["dependent_devices"]]
        
        return impact_analysis
    
    @staticmethod
    async def _query_performance_metrics(
        source: str, start_time: datetime, end_time: datetime, db: AsyncSession
    ) -> Dict[str, Any]:
        """查询性能指标"""
        performance_data = {
            "cpu_anomalies": [],
            "memory_anomalies": [],
            "disk_anomalies": []
        }
        
        # 提取服务器ID
        if source.startswith("server-"):
            server_id = int(source.split("-")[1])
            
            # 查询CPU和内存指标
            metrics_result = await db.execute(
                select(ServerMetric).where(
                    and_(
                        ServerMetric.server_id == server_id,
                        ServerMetric.collected_at >= start_time,
                        ServerMetric.collected_at <= end_time
                    )
                )
            )
            metrics = metrics_result.scalars().all()
            
            # 分析异常
            for metric in metrics:
                if metric.cpu_percent > 80:
                    performance_data["cpu_anomalies"].append({
                        "time": metric.collected_at.isoformat(),
                        "value": metric.cpu_percent,
                        "threshold": 80
                    })
                
                if metric.mem_percent > 85:
                    performance_data["memory_anomalies"].append({
                        "time": metric.collected_at.isoformat(),
                        "value": metric.mem_percent,
                        "threshold": 85
                    })
        
        return performance_data
    
    @staticmethod
    async def _analyze_correlations(alert: Alert, performance_data: Dict, db: AsyncSession) -> Dict[str, Any]:
        """分析相关性"""
        correlations = {
            "strong_correlations": [],
            "potential_causes": [],
            "affected_services": []
        }
        
        # 分析性能异常
        if performance_data["cpu_anomalies"]:
            correlations["strong_correlations"].append({
                "metric": "cpu",
                "correlation": "strong",
                "anomalies": len(performance_data["cpu_anomalies"])
            })
            correlations["potential_causes"].append("CPU资源不足")
        
        if performance_data["memory_anomalies"]:
            correlations["strong_correlations"].append({
                "metric": "memory",
                "correlation": "strong",
                "anomalies": len(performance_data["memory_anomalies"])
            })
            correlations["potential_causes"].append("内存泄漏或不足")
        
        correlations["root_cause"] = "性能资源瓶颈"
        correlations["affected_services"] = [alert.source]
        
        return correlations
    
    @staticmethod
    async def _analyze_anomaly_patterns(alert: Alert, db: AsyncSession) -> Dict[str, Any]:
        """分析异常模式"""
        patterns = {
            "anomaly_type": "unknown",
            "severity": "medium",
            "matched_patterns": [],
            "affected_services": []
        }
        
        # 简化的异常模式分析
        alert_title_lower = alert.title.lower()
        
        if "cpu" in alert_title_lower:
            patterns["anomaly_type"] = "cpu_spike"
            patterns["severity"] = "high"
        elif "memory" in alert_title_lower:
            patterns["anomaly_type"] = "memory_leak"
            patterns["severity"] = "high"
        elif "disk" in alert_title_lower:
            patterns["anomaly_type"] = "disk_full"
            patterns["severity"] = "critical"
        
        patterns["root_cause"] = f"{patterns['anomaly_type']} detected"
        patterns["affected_services"] = [alert.source]
        
        return patterns
    
    @staticmethod
    async def _compare_with_history(alert: Alert, db: AsyncSession) -> Dict[str, Any]:
        """历史对比分析"""
        comparison = {
            "period_comparison": "similar",
            "trend_analysis": "stable"
        }
        
        # 简化的历史对比逻辑
        time_window = 7  # 天
        
        # 查询历史同类型告警
        historical_alerts = await db.execute(
            select(Alert).where(
                and_(
                    Alert.source == alert.source,
                    Alert.created_at < alert.created_at,
                    Alert.created_at >= alert.created_at - timedelta(days=time_window)
                )
            )
        )
        
        historical_count = len(historical_alerts.scalars().all())
        
        if historical_count > 5:
            comparison["period_comparison"] = "frequent"
            comparison["trend_analysis"] = "increasing"
        elif historical_count == 0:
            comparison["period_comparison"] = "unusual"
            comparison["trend_analysis"] = "new_pattern"
        
        return comparison
    
    @staticmethod
    async def get_analysis_history(limit: int = 10) -> List[Dict[str, Any]]:
        """获取分析历史"""
        db = AsyncSessionLocal()
        
        try:
            result = await db.execute(
                select(RootCauseAnalysis)
                .order_by(desc(RootCauseAnalysis.created_at))
                .limit(limit)
            )
            analyses = result.scalars().all()
            
            history = []
            for analysis in analyses:
                history.append({
                    "id": analysis.id,
                    "alert_id": analysis.alert_id,
                    "analysis_type": analysis.analysis_type,
                    "confidence_score": analysis.confidence_score,
                    "root_cause": analysis.root_cause,
                    "status": analysis.status,
                    "created_at": analysis.created_at.isoformat(),
                    "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None
                })
            
            return history
        finally:
            await db.close()
    
    @staticmethod
    async def get_analysis_details(analysis_id: int) -> Dict[str, Any]:
        """获取分析详情"""
        db = AsyncSessionLocal()
        
        try:
            result = await db.execute(
                select(RootCauseAnalysis).where(RootCauseAnalysis.id == analysis_id)
            )
            analysis = result.scalar_one_or_none()
            
            if not analysis:
                return {"error": "Analysis not found"}
            
            return {
                "id": analysis.id,
                "alert_id": analysis.alert_id,
                "analysis_type": analysis.analysis_type,
                "analysis_result": analysis.analysis_result,
                "confidence_score": analysis.confidence_score,
                "root_cause": analysis.root_cause,
                "affected_services": analysis.affected_services,
                "recommendations": analysis.recommendations,
                "status": analysis.status,
                "created_at": analysis.created_at.isoformat(),
                "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None
            }
        finally:
            await db.close()