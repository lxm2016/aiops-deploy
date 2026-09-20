"""SQLAlchemy ORM models for the AIOps platform."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Server(Base):
    """Physical or virtual server (Linux / Windows)."""
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    ip = Column(String(64), unique=True, nullable=False, index=True)
    os_type = Column(String(32), default="linux")  # linux / windows
    os_distro = Column(String(64), default="")  # centos/ubuntu/openeuler/rocky/anolis/2019...
    os_version = Column(String(64), default="")
    cpu_cores = Column(Integer, default=0)
    cpu_model = Column(String(128), default="")
    mem_total_gb = Column(Float, default=0.0)
    status = Column(String(16), default="unknown")  # online / offline / unknown
    agent_installed = Column(Boolean, default=False)
    last_seen = Column(DateTime, nullable=True)
    tags = Column(String(256), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    metrics = relationship("ServerMetric", back_populates="server", cascade="all, delete-orphan")


class ServerMetric(Base):
    """Time-series metrics reported by the agent."""
    __tablename__ = "server_metrics"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), index=True)
    cpu_percent = Column(Float, default=0.0)
    mem_percent = Column(Float, default=0.0)
    mem_used_gb = Column(Float, default=0.0)
    disk_percent = Column(Float, default=0.0)
    disk_used_gb = Column(Float, default=0.0)
    disk_total_gb = Column(Float, default=0.0)
    net_rx_mbps = Column(Float, default=0.0)
    net_tx_mbps = Column(Float, default=0.0)
    load_avg = Column(Float, default=0.0)
    process_count = Column(Integer, default=0)
    raw = Column(JSON, nullable=True)  # full payload incl. per-disk, ports, services
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)

    server = relationship("Server", back_populates="metrics")


class VmwareHost(Base):
    """VMware vCenter / ESXi connection endpoint."""
    __tablename__ = "vmware_hosts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    host = Column(String(128), nullable=False)
    username = Column(String(128), default="")
    password = Column(String(256), default="")
    port = Column(Integer, default=443)
    status = Column(String(16), default="unknown")
    last_sync = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vms = relationship("VirtualMachine", back_populates="host", cascade="all, delete-orphan")


class VirtualMachine(Base):
    """A VM discovered from VMware."""
    __tablename__ = "virtual_machines"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("vmware_hosts.id"), index=True)
    name = Column(String(128), nullable=False)
    power_state = Column(String(32), default="unknown")  # poweredOn / poweredOff / suspended
    guest_os = Column(String(128), default="")
    ip = Column(String(64), default="")
    cpu_cores = Column(Integer, default=0)
    mem_mb = Column(Integer, default=0)
    cpu_percent = Column(Float, default=0.0)
    mem_percent = Column(Float, default=0.0)
    uptime = Column(String(64), default="")
    last_seen = Column(DateTime, nullable=True)

    host = relationship("VmwareHost", back_populates="vms")


class NetworkDevice(Base):
    """Switch / router / firewall (H3C, Huawei, Dell, ...)."""
    __tablename__ = "network_devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    ip = Column(String(64), unique=True, nullable=False, index=True)
    vendor = Column(String(64), default="")  # h3c / huawei / dell / cisco
    device_type = Column(String(64), default="switch")
    model = Column(String(128), default="")
    snmp_community = Column(String(128), default="public")
    snmp_version = Column(String(8), default="2c")
    status = Column(String(16), default="unknown")
    cpu_percent = Column(Float, default=0.0)
    mem_percent = Column(Float, default=0.0)
    port_total = Column(Integer, default=0)
    port_up = Column(Integer, default=0)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Rack(Base):
    """机房机柜 (按列分组, U数可自定义)。"""
    __tablename__ = "racks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)          # 机柜编号, 如 A01
    row_name = Column(String(64), default="A")         # 列名, 如 A列
    u_height = Column(Integer, default=42)             # 总U数
    remark = Column(String(256), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class RackDevice(Base):
    """机柜内设备 (支持前后侧, 同U位前后侧可各放一台设备)。"""
    __tablename__ = "rack_devices"

    id = Column(Integer, primary_key=True, index=True)
    rack_id = Column(Integer, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    device_type = Column(String(32), default="server")  # server/switch/storage/security/other
    u_start = Column(Integer, nullable=False)           # 起始U位 (从1开始, 1=最底部)
    u_size = Column(Integer, default=1)                 # 占用U数
    side = Column(String(8), default="front")           # front/back
    remark = Column(String(256), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SwitchPort(Base):
    """交换机端口明细 (每次轮询刷新状态, 备注由用户编辑并保留)。"""
    __tablename__ = "switch_ports"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, nullable=False, index=True)
    port_index = Column(Integer, nullable=False)
    name = Column(String(128), default="")
    status = Column(String(16), default="unknown")
    speed_mbps = Column(Integer, default=0)
    physical = Column(Integer, default=1)  # 1=物理口(计入UP/总), 0=VLAN/虚拟口
    alias = Column(String(256), default="")      # 交换机侧 ifAlias
    remark = Column(String(256), default="")     # 用户填写的端口用途备注
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StorageDevice(Base):
    """Storage array (Huawei / H3C / Sangfor / EMC / ...)."""
    __tablename__ = "storage_devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    ip = Column(String(64), unique=True, nullable=False, index=True)
    vendor = Column(String(64), default="")
    model = Column(String(128), default="")
    protocol = Column(String(16), default="none")  # none/snmp/smi-s
    snmp_community = Column(String(64), default="public")
    snmp_version = Column(String(4), default="2c")
    username = Column(String(64), default="")      # SMI-S (WBEM) 账号
    password = Column(String(128), default="")
    capacity_tb = Column(Float, default=0.0)
    used_tb = Column(Float, default=0.0)
    used_percent = Column(Float, default=0.0)
    details = Column(JSON, default=dict)           # 控制器/磁盘/存储池/卷等明细
    status = Column(String(16), default="unknown")
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EnvSensor(Base):
    """Temperature / humidity sensor endpoint."""
    __tablename__ = "env_sensors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    location = Column(String(128), default="")
    source_url = Column(String(256), default="")  # HTTP endpoint or SNMP
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    status = Column(String(16), default="unknown")
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EnvReading(Base):
    """Time-series temperature/humidity readings."""
    __tablename__ = "env_readings"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(Integer, ForeignKey("env_sensors.id"), index=True)
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)


class Alert(Base):
    """Alert raised by the alert engine."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(16), default="info")  # info / warning / critical
    category = Column(String(64), default="")  # server / vmware / network / storage / env
    source = Column(String(128), default="")  # device name / ip
    title = Column(String(256), nullable=False)
    detail = Column(Text, default="")
    status = Column(String(16), default="open")  # open / ack / resolved
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)


class ChatMessage(Base):
    """AI assistant conversation history."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), index=True)
    role = Column(String(16), default="user")  # user / assistant / system
    content = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemConfig(Base):
    """Key-value system settings (LLM config etc.), overrides .env defaults."""
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TopologyRelation(Base):
    """设备拓扑关系表"""
    __tablename__ = "topology_relations"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(32), nullable=False)  # server, network, storage, service
    source_id = Column(Integer, nullable=False)     # 源设备ID
    target_type = Column(String(32), nullable=False)  # server, network, storage, service
    target_id = Column(Integer, nullable=False)     # 目标设备ID
    relation_type = Column(String(32), nullable=False)  # depends_on, connected_to, hosted_on, monitored_by
    strength = Column(Float, default=1.0)          # 关联强度 (0-1)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    extra_info = Column("metadata", Text)          # JSON格式的额外信息 (metadata是SQLAlchemy保留字, 属性名改用extra_info)


class RootCauseAnalysis(Base):
    """根因分析结果表"""
    __tablename__ = "root_cause_analysis"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, nullable=True)        # 关联的告警ID
    analysis_type = Column(String(32), nullable=False)  # topology, correlation, anomaly
    analysis_result = Column(Text)                # 分析结果JSON
    confidence_score = Column(Float, default=0.0)  # 置信度 0-1
    root_cause = Column(Text)                      # 根因描述
    affected_services = Column(Text)               # 受影响的服务列表JSON
    recommendations = Column(Text)                 # 建议的解决方案
    status = Column(String(16), default="pending")  # pending, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class KnowledgeBase(Base):
    """RAG知识库"""
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(64), nullable=False)   # incident, solution, best_practice, manual
    tags = Column(String(512))                     # 标签，逗号分隔
    source = Column(String(128))                   # 知识来源
    relevance_score = Column(Float, default=0.0)   # 相关性评分
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowDefinition(Base):
    """工作流定义"""
    __tablename__ = "workflow_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    definition = Column(Text, nullable=False)       # JSON格式的工作流定义
    status = Column(String(16), default="active")  # active, inactive, draft
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowExecution(Base):
    """工作流执行记录"""
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, nullable=False)
    trigger_type = Column(String(32), nullable=False)  # manual, alert, scheduled
    trigger_data = Column(Text)                        # 触发数据JSON
    status = Column(String(16), default="pending")     # pending, running, completed, failed
    progress = Column(Integer, default=0)              # 进度百分比
    result = Column(Text)                             # 执行结果JSON
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class SwitchPortMetric(Base):
    """Time-series port traffic metrics."""
    __tablename__ = "switch_port_metrics"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, nullable=False, index=True)
    port_index = Column(Integer, nullable=False, index=True)
    in_octets = Column(Integer, default=0)          # 接收字节数
    out_octets = Column(Integer, default=0)         # 发送字节数
    in_errors = Column(Integer, default=0)         # 接收错误数
    out_errors = Column(Integer, default=0)        # 发送错误数
    in_mbps = Column(Float, default=0.0)           # 接收速率(Mbps)
    out_mbps = Column(Float, default=0.0)          # 发送速率(Mbps)
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)


class User(Base):
    """Platform user."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    role = Column(String(32), default="admin")
    created_at = Column(DateTime, default=datetime.utcnow)
