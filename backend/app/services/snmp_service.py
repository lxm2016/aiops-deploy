"""SNMP-based collection for network devices (H3C / Huawei / Dell switches).

注意: 所有 get_cmd/next_cmd 必须传 lookupMib=False, 否则 pysnmp7 会尝试
加载本地 MIB 库解析 OID, 离线环境无 MIB 文件将导致 walk 全部失败。
"""
from typing import Optional

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, get_cmd, next_cmd, walk_cmd,
)

# Common OIDs
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"

# ifTable / ifXTable
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"       # 端口名称
OID_IF_OPER = "1.3.6.1.2.1.2.2.1.8"        # 端口运行状态
OID_IF_SPEED = "1.3.6.1.2.1.2.2.1.5"       # 端口速率(bps)
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"   # 端口备注(ifAlias, 交换机上常写对端用途)

# 端口流量统计OID (ifXTable)
OID_IF_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"     # 接收字节数
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"    # 发送字节数
OID_IF_IN_ERRORS = "1.3.6.1.2.1.31.1.1.1.8"     # 接收错误数
OID_IF_OUT_ERRORS = "1.3.6.1.2.1.31.1.1.1.12"   # 发送错误数

# ifOperStatus 数值 -> 中文
PORT_STATUS_MAP = {
    1: "up", 2: "down", 3: "testing",
    4: "unknown", 5: "dormant", 6: "notPresent", 7: "lowerLayerDown",
}

# Vendor-specific CPU/memory OIDs (表类型OID, 需GETNEXT取首行)
VENDOR_OIDS = {
    "huawei": {
        "cpu": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5",   # hwEntityCpuUsage
        "mem": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7",   # hwEntityMemUsage
    },
    "h3c": {
        "cpu": "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",      # hh3cEntityExtCpuUsage
        "mem": "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",      # hh3cEntityExtMemUsage
    },
    # 通用的CPU内存OID (适用于大多数设备)
    "generic": {
        "cpu": "1.3.6.1.4.1.9.9.109.1.1.1.1.7",         # hrSystem. hrProcessorLoad
        "mem": "1.3.6.1.4.1.9.9.48.1.1.1.5",          # hrSystem. hrMemorySize
    },
}


def _community(community: str, version: str) -> CommunityData:
    return CommunityData(community, mpModel=1 if version == "2c" else 0)


async def _target(ip: str) -> UdpTransportTarget:
    return await UdpTransportTarget.create((ip, 161), timeout=5, retries=1)


async def snmp_get(ip: str, community: str, oid: str, version: str = "2c") -> Optional[str]:
    """Perform a single SNMP GET (标量OID)。"""
    try:
        error_indication, error_status, error_index, var_binds = await get_cmd(
            SnmpEngine(),
            _community(community, version),
            await _target(ip),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lookupMib=False,
        )
        if error_indication or error_status:
            return None
        for var_bind in var_binds:
            return str(var_bind[1])
    except Exception:
        return None
    return None


async def snmp_get_next(ip: str, community: str, oid: str, version: str = "2c") -> Optional[str]:
    """GETNEXT并返回目标OID子树下的首个值 (表类型OID用, 如CPU/内存使用率)。

    注意: pysnmp 7.x 的 next_cmd 是普通协程(返回单条结果), 不是异步生成器,
    必须用 await 直接调用, 用 async for 会抛 TypeError。
    """
    try:
        error_indication, error_status, error_index, var_binds = await next_cmd(
            SnmpEngine(),
            _community(community, version),
            await _target(ip),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lookupMib=False,
        )
        if error_indication or error_status:
            return None
        for var_bind in var_binds:
            if str(var_bind[0]).startswith(oid):
                return str(var_bind[1])
    except Exception:
        return None
    return None


async def snmp_walk(ip: str, community: str, oid: str, version: str = "2c") -> dict:
    """Walk指定OID子树, 返回 {实例后缀: 值字符串}。

    使用官方 walk_cmd 异步生成器(内部循环GETNEXT), lexicographicMode=False
    限定在子树内; 不能对 next_cmd 用 async for (7.x 中它不是生成器)。
    """
    out = {}
    try:
        async for (error_indication, error_status, error_index, var_binds) in walk_cmd(
            SnmpEngine(),
            _community(community, version),
            await _target(ip),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
            lookupMib=False,
        ):
            if error_indication or error_status:
                break
            for var_bind in var_binds:
                full_oid = str(var_bind[0])
                if full_oid.startswith(oid + "."):
                    suffix = full_oid[len(oid) + 1:]
                    out[suffix] = str(var_bind[1])
    except Exception:
        pass
    return out


async def walk_ports(ip: str, community: str, version: str = "2c") -> list:
    """采集全部端口明细: 名称/状态/速率/备注(ifAlias)/是否物理口。"""
    descrs = await snmp_walk(ip, community, OID_IF_DESCR, version)
    if not descrs:
        return []
    opers = await snmp_walk(ip, community, OID_IF_OPER, version)
    speeds = await snmp_walk(ip, community, OID_IF_SPEED, version)
    aliases = await snmp_walk(ip, community, OID_IF_ALIAS, version)
    
    # 获取流量统计
    in_octets = await snmp_walk(ip, community, OID_IF_IN_OCTETS, version)
    out_octets = await snmp_walk(ip, community, OID_IF_OUT_OCTETS, version)
    in_errors = await snmp_walk(ip, community, OID_IF_IN_ERRORS, version)
    out_errors = await snmp_walk(ip, community, OID_IF_OUT_ERRORS, version)

    ports = []
    for suffix, name in descrs.items():
        try:
            index = int(suffix)
        except ValueError:
            continue
        oper = _safe_int(opers.get(suffix))
        port_data = {
            "port_index": index,
            "name": name,
            "status": PORT_STATUS_MAP.get(oper, "unknown"),
            "speed_mbps": _to_speed_mbps(speeds.get(suffix)),
            "alias": aliases.get(suffix, "") or "",
            "physical": 1 if is_physical_port(name) else 0,
            # 流量统计
            "in_octets": _safe_int(in_octets.get(suffix)),
            "out_octets": _safe_int(out_octets.get(suffix)),
            "in_errors": _safe_int(in_errors.get(suffix)),
            "out_errors": _safe_int(out_errors.get(suffix)),
        }
        ports.append(port_data)
    ports.sort(key=lambda p: p["port_index"])
    return ports


async def get_port_status(ip: str, community: str, version: str, port_index: int) -> Optional[str]:
    """单端口状态测试: GET ifOperStatus.<index>。"""
    val = await snmp_get(ip, community, f"{OID_IF_OPER}.{port_index}", version)
    if val is None:
        return None
    try:
        return PORT_STATUS_MAP.get(int(val), "unknown")
    except ValueError:
        return "unknown"


def _safe_int(s: Optional[str]) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


def _to_speed_mbps(s: Optional[str]) -> int:
    """ifSpeed值可能是整数bps或浮点字符串, 统一转Mbps。"""
    try:
        return max(0, int(float(str(s).strip()) / 1_000_000))
    except (ValueError, TypeError):
        return 0


# 虚拟接口名前缀: 这些口不计入"端口(UP/总)"统计, 但仍在明细中展示
VIRTUAL_PORT_PREFIXES = (
    "Vlan", "Vlanif", "Vlan-interface", "LoopBack", "Loopback", "NULL", "Null",
    "InLoopBack", "Register", "Tunnel", "Aux", "Route", "Stack", "Virtual", "MEth",
)


def is_physical_port(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    return not n.startswith(VIRTUAL_PORT_PREFIXES)


async def collect_network_device(
    ip: str, community: str = "public", vendor: str = "", version: str = "2c"
) -> dict:
    """Collect basic info + CPU/memory + port status from a network device."""
    result = {
        "ip": ip,
        "reachable": False,
        "sys_name": "",
        "sys_descr": "",
        "cpu_percent": 0.0,
        "mem_percent": 0.0,
        "port_total": 0,
        "port_up": 0,
        "ports": [],
    }

    # Basic reachability via sysName
    sys_name = await snmp_get(ip, community, OID_SYS_NAME, version)
    if sys_name is None:
        return result
    result["reachable"] = True
    result["sys_name"] = sys_name

    descr = await snmp_get(ip, community, OID_SYS_DESCR, version)
    result["sys_descr"] = descr or ""

    # Vendor-specific CPU/mem
    vendor_key = vendor.lower() if vendor else ""
    if not vendor_key:
        descr_lower = (descr or "").lower()
        if "huawei" in descr_lower:
            vendor_key = "huawei"
        elif "h3c" in descr_lower or "hangzhou" in descr_lower:
            vendor_key = "h3c"

    # 优先使用厂商特定OID，如果没有则使用通用OID
    oids_to_try = []
    if vendor_key in VENDOR_OIDS:
        oids_to_try.append(vendor_key)
    oids_to_try.append("generic")  # 尝试通用OID作为备选

    for current_vendor in oids_to_try:
        if current_vendor in VENDOR_OIDS:
            cpu_oid = VENDOR_OIDS[current_vendor]["cpu"]
            mem_oid = VENDOR_OIDS[current_vendor]["mem"]
            
            # 尝试获取CPU数据
            cpu = await snmp_get_next(ip, community, cpu_oid, version)
            if cpu:
                try:
                    result["cpu_percent"] = float(cpu)
                    print(f"[DEBUG] CPU获取成功: {current_vendor} CPU={cpu}%")
                except ValueError:
                    print(f"[DEBUG] CPU数据转换失败: {cpu}")
            else:
                print(f"[DEBUG] CPU获取失败: {current_vendor} {cpu_oid}")
            
            # 尝试获取内存数据
            if current_vendor == "generic":
                # 通用OID中内存是总内存量，需要计算使用率
                mem_total = await snmp_get_next(ip, community, mem_oid, version)
                mem_used = await snmp_get_next(ip, community, "1.3.6.1.4.1.9.9.48.1.1.1.6", version)  # hrMemoryUsed
                if mem_total and mem_used:
                    try:
                        total_bytes = int(float(mem_total)) * 1024  # 转换为字节
                        used_bytes = int(float(mem_used)) * 1024
                        if total_bytes > 0:
                            result["mem_percent"] = (used_bytes / total_bytes) * 100
                            print(f"[DEBUG] 内存使用率计算成功: {current_vendor} 内存={result['mem_percent']}%")
                    except ValueError:
                        print(f"[DEBUG] 内存数据转换失败")
            else:
                # 厂商特定OID直接返回使用率
                mem = await snmp_get_next(ip, community, mem_oid, version)
                if mem:
                    try:
                        result["mem_percent"] = float(mem)
                        print(f"[DEBUG] 内存获取成功: {current_vendor} 内存={mem}%")
                    except ValueError:
                        print(f"[DEBUG] 内存数据转换失败: {mem}")
            
            # 如果获取到了数据就不再尝试其他OID
            if result["cpu_percent"] > 0 or result["mem_percent"] > 0:
                break

    # 端口明细 (名称/状态/速率/备注); UP/总 只统计物理口, 排除VLAN等虚拟口
    ports = await walk_ports(ip, community, version)
    result["ports"] = ports
    physical = [p for p in ports if p["physical"]]
    result["port_total"] = len(physical)
    result["port_up"] = sum(1 for p in physical if p["status"] == "up")

    return result
