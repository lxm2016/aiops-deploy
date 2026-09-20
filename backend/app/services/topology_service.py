"""拓扑发现和关系管理服务"""
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from sqlalchemy import and_, func, select, or_
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    TopologyRelation, NetworkDevice, Server, StorageDevice, SwitchPort,
    VmwareHost, VirtualMachine
)


class TopologyDiscoveryService:
    """拓扑发现服务"""
    
    @staticmethod
    async def discover_topology(db: AsyncSession) -> Dict[str, Any]:
        """自动发现基础设施拓扑关系"""
        discoveries = []
        
        # 1. 发现服务器-网络设备连接关系
        server_network_relations = await TopologyDiscoveryService._discover_server_network_connections(db)
        discoveries.extend(server_network_relations)
        
        # 2. 发现虚拟化关系
        virtualization_relations = await TopologyDiscoveryService._discover_virtualization_relations(db)
        discoveries.extend(virtualization_relations)
        
        # 3. 发现存储连接关系
        storage_relations = await TopologyDiscoveryService._discover_storage_connections(db)
        discoveries.extend(storage_relations)
        
        # 4. 发现网络设备之间的连接关系
        network_device_relations = await TopologyDiscoveryService._discover_network_device_connections(db)
        discoveries.extend(network_device_relations)
        
        # 5. 发现服务依赖关系（基于端口监听）
        service_relations = await TopologyDiscoveryService._discover_service_dependencies(db)
        discoveries.extend(service_relations)
        
        # 6. 保存发现的拓扑关系
        saved_count = 0
        for relation in discoveries:
            # 检查是否已存在相同的关联
            exists = await db.execute(
                select(TopologyRelation).where(
                    and_(
                        TopologyRelation.source_type == relation['source_type'],
                        TopologyRelation.source_id == relation['source_id'],
                        TopologyRelation.target_type == relation['target_type'],
                        TopologyRelation.target_id == relation['target_id'],
                        TopologyRelation.relation_type == relation['relation_type']
                    )
                )
            )
            if not exists.scalar_one_or_none():
                new_relation = TopologyRelation(**relation)
                db.add(new_relation)
                saved_count += 1
        
        await db.commit()
        
        return {
            "total_discovered": len(discoveries),
            "saved_relations": saved_count,
            "discovery_time": datetime.utcnow().isoformat(),
            "categories": list(set([d['relation_type'] for d in discoveries]))
        }
    
    @staticmethod
    async def _discover_server_network_connections(db: AsyncSession) -> List[Dict[str, Any]]:
        """发现服务器与网络设备的连接关系"""
        relations = []
        
        # 获取所有服务器
        servers_result = await db.execute(select(Server).where(Server.status == "online"))
        servers = servers_result.scalars().all()
        
        # 获取所有网络设备
        devices_result = await db.execute(select(NetworkDevice).where(NetworkDevice.status == "online"))
        devices = devices_result.scalars().all()
        
        for server in servers:
            for device in devices:
                # 基于IP段推断连接关系（简化逻辑）
                if TopologyDiscoveryService._is_same_network_segment(server.ip, device.ip):
                    relations.append({
                        "source_type": "server",
                        "source_id": server.id,
                        "target_type": "network",
                        "target_id": device.id,
                        "relation_type": "connected_to",
                        "strength": 0.8,
                        "metadata": {
                            "server_ip": server.ip,
                            "device_ip": device.ip,
                            "inference_method": "network_segment"
                        }
                    })
        
        return relations
    
    @staticmethod
    async def _discover_virtualization_relations(db: AsyncSession) -> List[Dict[str, Any]]:
        """发现虚拟化关系（主机-虚拟机）"""
        relations = []
        
        # 获取VMware主机
        hosts_result = await db.execute(select(VmwareHost).where(VmwareHost.status == "online"))
        hosts = hosts_result.scalars().all()
        
        for host in hosts:
            # 获取该主机上的虚拟机
            vms_result = await db.execute(
                select(VirtualMachine).where(VirtualMachine.host_id == host.id)
            )
            vms = vms_result.scalars().all()
            
            for vm in vms:
                relations.append({
                    "source_type": "host",
                    "source_id": host.id,
                    "target_type": "vm",
                    "target_id": vm.id,
                    "relation_type": "hosted_on",
                    "strength": 1.0,
                    "metadata": {
                        "host_name": host.name,
                        "vm_name": vm.name,
                        "power_state": vm.power_state
                    }
                })
        
        return relations
    
    @staticmethod
    async def _discover_storage_connections(db: AsyncSession) -> List[Dict[str, Any]]:
        """发现存储设备连接关系"""
        relations = []
        
        # 获取在线服务器
        servers_result = await db.execute(select(Server).where(Server.status == "online"))
        servers = servers_result.scalars().all()
        
        # 获取存储设备
        storage_result = await db.execute(select(StorageDevice).where(StorageDevice.status == "online"))
        storage_devices = storage_result.scalars().all()
        
        for server in servers:
            for storage in storage_devices:
                # 简化的存储连接推断
                if server.ip and storage.ip:
                    if TopologyDiscoveryService._is_same_network_segment(server.ip, storage.ip):
                        relations.append({
                            "source_type": "server",
                            "source_id": server.id,
                            "target_type": "storage",
                            "target_id": storage.id,
                            "relation_type": "connected_to",
                            "strength": 0.7,
                            "metadata": {
                                "server_ip": server.ip,
                                "storage_ip": storage.ip,
                                "inference_method": "network_segment"
                            }
                        })
        
        return relations
    
    @staticmethod
    async def _discover_network_device_connections(db: AsyncSession) -> List[Dict[str, Any]]:
        """发现网络设备之间的连接关系"""
        relations = []
        
        # 获取所有网络设备
        devices_result = await db.execute(select(NetworkDevice).where(NetworkDevice.status == "online"))
        devices = devices_result.scalars().all()
        
        for device1 in devices:
            for device2 in devices:
                if device1.id != device2.id:
                    # 基于IP段推断网络设备之间的连接
                    if TopologyDiscoveryService._is_same_network_segment(device1.ip, device2.ip):
                        relations.append({
                            "source_type": "network",
                            "source_id": device1.id,
                            "target_type": "network",
                            "target_id": device2.id,
                            "relation_type": "connected_to",
                            "strength": 0.6,
                            "metadata": {
                                "device1_ip": device1.ip,
                                "device2_ip": device2.ip,
                                "inference_method": "network_segment"
                            }
                        })
        
        return relations
    
    @staticmethod
    async def _discover_service_dependencies(db: AsyncSession) -> List[Dict[str, Any]]:
        """发现服务依赖关系（基于端口监听）"""
        relations = []
        
        # 获取在线服务器
        servers_result = await db.execute(select(Server).where(Server.status == "online"))
        servers = servers_result.scalars().all()
        
        # 定义常见的服务端口映射
        service_ports = {
            "80": "web",
            "443": "web_ssl",
            "3306": "mysql",
            "5432": "postgresql",
            "6379": "redis",
            "8080": "web_proxy"
        }
        
        for server in servers:
            # 模拟端口扫描（实际环境中应该通过agent或SSH获取）
            simulated_ports = [80, 8080, 3306]  # 模拟发现的端口
            
            for port in simulated_ports:
                if port in service_ports:
                    relations.append({
                        "source_type": "server",
                        "source_id": server.id,
                        "target_type": "service",
                        "target_id": f"service_{service_ports[port]}",
                        "relation_type": "provides",
                        "strength": 0.9,
                        "metadata": {
                            "service_type": service_ports[port],
                            "port": port,
                            "server_ip": server.ip,
                            "inference_method": "simulated_port_scan"
                        }
                    })
        
        return relations
    
    @staticmethod
    def _is_same_network_segment(ip1: str, ip2: str) -> bool:
        """判断两个IP是否在同一网段（简化判断）"""
        try:
            # 简单的前三个字节匹配判断
            ip1_parts = ip1.split('.')
            ip2_parts = ip2.split('.')
            
            # 至少前两个字节相同视为同一网段
            if len(ip1_parts) >= 2 and len(ip2_parts) >= 2:
                return ip1_parts[0] == ip2_parts[0] and ip1_parts[1] == ip2_parts[1]
        except:
            pass
        return False
    
    @staticmethod
    async def get_topology_graph(device_type: Optional[str] = None, device_id: Optional[int] = None) -> Dict[str, Any]:
        """获取拓扑关系图"""
        db = AsyncSessionLocal()
        
        try:
            # 构建查询条件
            conditions = []
            if device_type and device_id:
                conditions.append(
                    or_(
                        and_(
                            TopologyRelation.source_type == device_type,
                            TopologyRelation.source_id == device_id
                        ),
                        and_(
                            TopologyRelation.target_type == device_type,
                            TopologyRelation.target_id == device_id
                        )
                    )
                )
            
            # 查询拓扑关系
            if conditions:
                query = select(TopologyRelation).where(or_(*conditions))
            else:
                query = select(TopologyRelation)
            
            result = await db.execute(query)
            relations = result.scalars().all()
            
            # 构建图数据
            nodes = {}
            edges = []
            
            for relation in relations:
                # 添加源节点
                source_key = f"{relation.source_type}_{relation.source_id}"
                if source_key not in nodes:
                    nodes[source_key] = {
                        "id": source_key,
                        "type": relation.source_type,
                        "label": f"{relation.source_type}_{relation.source_id}",
                        "group": relation.source_type
                    }
                
                # 添加目标节点
                target_key = f"{relation.target_type}_{relation.target_id}"
                if target_key not in nodes:
                    nodes[target_key] = {
                        "id": target_key,
                        "type": relation.target_type,
                        "label": f"{relation.target_type}_{relation.target_id}",
                        "group": relation.target_type
                    }
                
                # 添加边
                edges.append({
                    "from": source_key,
                    "to": target_key,
                    "label": relation.relation_type,
                    "strength": relation.strength
                })
            
            return {
                "nodes": list(nodes.values()),
                "edges": edges,
                "relations": len(relations),
                "generated_at": datetime.utcnow().isoformat()
            }
        finally:
            await db.close()
    
    @staticmethod
    async def get_blast_radius(device_type: str, device_id: int) -> Dict[str, Any]:
        """计算影响面（爆炸半径）"""
        db = AsyncSessionLocal()
        
        try:
            # 查找所有依赖于该设备的服务
            dependent_relations = await db.execute(
                select(TopologyRelation).where(
                    and_(
                        TopologyRelation.target_type == device_type,
                        TopologyRelation.target_id == device_id,
                        TopologyRelation.relation_type.in_(["depends_on", "connected_to"])
                    )
                )
            )
            dependents = dependent_relations.scalars().all()
            
            # 查找该设备依赖的服务
            dependency_relations = await db.execute(
                select(TopologyRelation).where(
                    and_(
                        TopologyRelation.source_type == device_type,
                        TopologyRelation.source_id == device_id,
                        TopologyRelation.relation_type.in_(["depends_on", "connected_to"])
                    )
                )
            )
            dependencies = dependency_relations.scalars().all()
            
            # 构建影响面分析结果
            affected_services = []
            critical_paths = []
            
            for dependent in dependents:
                affected_services.append({
                    "device_type": dependent.source_type,
                    "device_id": dependent.source_id,
                    "relation": dependent.relation_type,
                    "strength": dependent.strength
                })
                
                # 检查是否为关键路径
                if dependent.relation_type == "depends_on" and dependent.strength > 0.8:
                    critical_paths.append({
                        "path": f"{device_type}_{device_id} -> {dependent.source_type}_{dependent.source_id}",
                        "criticality": "high"
                    })
            
            return {
                "center_device": {
                    "type": device_type,
                    "id": device_id
                },
                "affected_services": affected_services,
                "dependencies": len(dependencies),
                "dependents": len(dependents),
                "critical_paths": critical_paths,
                "impact_score": len(dependents) * 0.7 + len(dependencies) * 0.3,
                "analysis_time": datetime.utcnow().isoformat()
            }
        finally:
            await db.close()
    
    @staticmethod
    async def manual_add_relation(
        source_type: str,
        source_id: int,
        target_type: str,
        target_id: int,
        relation_type: str,
        strength: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """手动添加拓扑关系"""
        db = AsyncSessionLocal()
        
        try:
            relation = TopologyRelation(
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
                relation_type=relation_type,
                strength=strength,
                extra_info=str(metadata) if metadata else "{}"
            )
            
            db.add(relation)
            await db.commit()
            return True
        except Exception as e:
            await db.rollback()
            return False
        finally:
            await db.close()
    
    @staticmethod
    async def cleanup_expired_relations(days: int = 90) -> int:
        """清理过期的拓扑关系"""
        db = AsyncSessionLocal()
        
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # 删除超过指定天数的拓扑关系
            result = await db.execute(
                delete(TopologyRelation).where(TopologyRelation.discovered_at < cutoff_date)
            )
            
            deleted_count = result.rowcount
            await db.commit()
            
            return deleted_count
        finally:
            await db.close()