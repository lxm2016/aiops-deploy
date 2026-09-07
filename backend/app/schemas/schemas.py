"""Pydantic schemas for API request/response."""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


# ---------- Auth / Settings ----------
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class LlmConfigIn(BaseModel):
    base_url: str
    model: str
    api_key: str = "EMPTY"


class PortRemarkIn(BaseModel):
    remark: str = ""


# ---------- Server ----------
class ServerCreate(BaseModel):
    name: str
    ip: str
    os_type: str = "linux"
    os_distro: str = ""
    os_version: str = ""
    tags: str = ""


class ServerOut(BaseModel):
    id: int
    name: str
    ip: str
    os_type: str
    os_distro: str
    os_version: str
    cpu_cores: int
    cpu_model: str
    mem_total_gb: float
    status: str
    agent_installed: bool
    last_seen: Optional[datetime]
    tags: str
    created_at: datetime

    class Config:
        from_attributes = True


class MetricReport(BaseModel):
    """Payload the agent POSTs to the platform."""
    ip: str
    hostname: str = ""
    os_type: str = "linux"
    os_distro: str = ""
    os_version: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    mem_total_gb: float = 0.0
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    mem_used_gb: float = 0.0
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    net_rx_mbps: float = 0.0
    net_tx_mbps: float = 0.0
    load_avg: float = 0.0
    process_count: int = 0
    disks: List[Any] = []
    ports: List[Any] = []
    services: List[Any] = []


class ServerMetricOut(BaseModel):
    cpu_percent: float
    mem_percent: float
    mem_used_gb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    net_rx_mbps: float
    net_tx_mbps: float
    load_avg: float
    process_count: int
    collected_at: datetime
    disks: Optional[List[Any]] = None  # 各分区使用率历史 (从raw提取)

    class Config:
        from_attributes = True


# ---------- VMware ----------
class VmwareHostCreate(BaseModel):
    name: str
    host: str
    username: str = ""
    password: str = ""
    port: int = 443


class VmwareHostOut(BaseModel):
    id: int
    name: str
    host: str
    port: int
    status: str
    last_sync: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class VirtualMachineOut(BaseModel):
    id: int
    host_id: int
    name: str
    power_state: str
    guest_os: str
    ip: str
    cpu_cores: int
    mem_mb: int
    cpu_percent: float
    mem_percent: float
    uptime: str
    last_seen: Optional[datetime]

    class Config:
        from_attributes = True


# ---------- Network ----------
class NetworkDeviceCreate(BaseModel):
    name: str
    ip: str
    vendor: str = ""
    device_type: str = "switch"
    model: str = ""
    snmp_community: str = "public"
    snmp_version: str = "2c"


class NetworkDeviceOut(BaseModel):
    id: int
    name: str
    ip: str
    vendor: str
    device_type: str
    model: str
    snmp_community: str
    snmp_version: str
    status: str
    cpu_percent: float
    mem_percent: float
    port_total: int
    port_up: int
    last_seen: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Storage ----------
class StorageDeviceCreate(BaseModel):
    name: str
    ip: str
    vendor: str = ""
    model: str = ""
    protocol: str = "none"  # none/snmp/smi-s
    snmp_community: str = "public"
    snmp_version: str = "2c"
    username: str = ""
    password: str = ""
    capacity_tb: float = 0.0


class StorageDeviceOut(BaseModel):
    id: int
    name: str
    ip: str
    vendor: str
    model: str
    protocol: str
    snmp_community: str
    snmp_version: str
    username: str
    password: str
    capacity_tb: float
    used_tb: float
    used_percent: float
    details: Optional[Any] = None
    status: str
    last_seen: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Env sensor ----------
class EnvSensorCreate(BaseModel):
    name: str
    location: str = ""
    source_url: str = ""


class EnvSensorOut(BaseModel):
    id: int
    name: str
    location: str
    source_url: str
    temperature: Optional[float]
    humidity: Optional[float]
    status: str
    last_seen: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class EnvReadingOut(BaseModel):
    temperature: Optional[float]
    humidity: Optional[float]
    collected_at: datetime

    class Config:
        from_attributes = True


# ---------- Alert ----------
class AlertOut(BaseModel):
    id: int
    level: str
    category: str
    source: str
    title: str
    detail: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


# ---------- Chat ----------
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# ---------- Rack ----------
class RackCreate(BaseModel):
    name: str
    row_name: str = "A"
    u_height: int = 42
    remark: str = ""


class RackOut(BaseModel):
    id: int
    name: str
    row_name: str
    u_height: int
    remark: str
    created_at: datetime

    class Config:
        from_attributes = True


class RackDeviceCreate(BaseModel):
    name: str
    device_type: str = "server"  # server/switch/storage/security/other
    u_start: int
    u_size: int = 1
    side: str = "front"  # front/back
    remark: str = ""


class RackDeviceOut(BaseModel):
    id: int
    rack_id: int
    name: str
    device_type: str
    u_start: int
    u_size: int
    side: str
    remark: str
    created_at: datetime

    class Config:
        from_attributes = True


class RackDeviceImportItem(BaseModel):
    rack_name: str
    name: str
    device_type: str = "server"
    u_start: int
    u_size: int = 1
    side: str = "front"
    remark: str = ""


class RackDeviceImportIn(BaseModel):
    items: List[RackDeviceImportItem]


# ---------- Auth ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str
