"""Storage array collection: SNMP (HOST-RESOURCES) and SMI-S (WBEM/CIM).

不同厂商存储管理方式不同:
- SNMP: 多数存储(华为/H3C/宏杉/EMC等)支持标准HOST-RESOURCES-MIB, 可取容量/磁盘/控制器状态
- SMI-S: 通过pywbem走CIM/WBEM协议(华为OceanStor/EMC等), 可取存储池/卷/磁盘/控制器明细
- 无: 仅手工登记容量
"""
import asyncio
from typing import Optional

from app.services.snmp_service import snmp_walk, _safe_int

# HOST-RESOURCES-MIB
OID_HR_STORAGE_TYPES = "1.3.6.1.2.1.25.2.3.1.2"   # 存储类型OID
OID_HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"   # 描述
OID_HR_STORAGE_AU = "1.3.6.1.2.1.25.2.3.1.4"      # 分配单元大小(字节)
OID_HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"    # 总大小(AU)
OID_HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"    # 已用(AU)

# 固定存储类型OID (hrStorageType)
STORAGE_TYPE_FIXED = "1.3.6.1.2.1.25.2.1.4"

# CIM状态 -> 中文
CIM_STATUS_MAP = {
    0: "未知", 1: "其他", 2: "正常", 3: "降级", 4: "压力",
    5: "预测性故障", 6: "错误", 7: "不可恢复错误",
}

# WBEM端口: http 5988 / https 5989
WBEM_PORTS = (5989, 5988)


async def collect_storage_snmp(ip: str, community: str, version: str = "2c") -> dict:
    """通过HOST-RESOURCES-MIB采集存储容量/磁盘/控制器。"""
    result = {
        "reachable": False,
        "capacity_tb": 0.0,
        "used_tb": 0.0,
        "used_percent": 0.0,
        "details": {"disks": [], "controllers": [], "pools": [], "volumes": []},
    }

    types = await snmp_walk(ip, community, OID_HR_STORAGE_TYPES, version)
    if not types:
        return result
    result["reachable"] = True

    descrs = await snmp_walk(ip, community, OID_HR_STORAGE_DESCR, version)
    aus = await snmp_walk(ip, community, OID_HR_STORAGE_AU, version)
    sizes = await snmp_walk(ip, community, OID_HR_STORAGE_SIZE, version)
    useds = await snmp_walk(ip, community, OID_HR_STORAGE_USED, version)

    total_bytes = 0
    used_bytes = 0
    for suffix, type_oid in types.items():
        if type_oid != STORAGE_TYPE_FIXED:
            continue
        au = _safe_int(aus.get(suffix)) or 0
        size = _safe_int(sizes.get(suffix)) or 0
        used = _safe_int(useds.get(suffix)) or 0
        if size <= 0:
            continue
        total_bytes += size * au
        used_bytes += min(used, size) * au
        result["details"]["disks"].append({
            "name": descrs.get(suffix, f"存储单元{suffix}"),
            "size_tb": round(size * au / (1024 ** 4), 2),
            "used_tb": round(used * au / (1024 ** 4), 2),
            "used_percent": round(used / size * 100, 1) if size else 0,
        })

    if total_bytes:
        result["capacity_tb"] = round(total_bytes / (1024 ** 4), 2)
        result["used_tb"] = round(used_bytes / (1024 ** 4), 2)
        result["used_percent"] = round(used_bytes / total_bytes * 100, 1)

    # 控制器状态: 尝试常见厂商OID (华为/宏杉等实体状态表)
    for oid in ("1.3.6.1.4.1.2011.2.235.1.1.12.1.6", "1.3.6.1.4.1.25506.2.6.1.1.1.1.12"):
        states = await snmp_walk(ip, community, oid, version)
        if states:
            for suffix, val in states.items():
                result["details"]["controllers"].append({
                    "name": f"控制器{suffix}",
                    "status": CIM_STATUS_MAP.get(_safe_int(val), val),
                })
            break

    return result


def _collect_storage_wbem_sync(
    ip: str, username: str, password: str, namespace: str = "root/cimv2"
) -> dict:
    """SMI-S采集 (pywbem, 同步)。枚举 CIM_ComputerSystem/StoragePool/LogicalDisk/PhysicalDisk。"""
    import pywbem

    result = {
        "reachable": False,
        "capacity_tb": 0.0,
        "used_tb": 0.0,
        "used_percent": 0.0,
        "details": {"disks": [], "controllers": [], "pools": [], "volumes": []},
    }

    conn = None
    last_err = None
    for port in WBEM_PORTS:
        url = f"{'https' if port == 5989 else 'http'}://{ip}:{port}"
        try:
            conn = pywbem.WBEMConnection(
                url, (username, password),
                default_namespace=namespace,
                no_verification=True,  # 存储自签证书常见
                timeout=15,
            )
            conn.EnumerateClassNames()  # 触发连接验证
            last_err = None
            break
        except Exception as e:
            last_err = e
            conn = None
    if conn is None:
        if last_err is not None:
            result["error"] = str(last_err)
        return result
    result["reachable"] = True

    def _instances(class_name):
        try:
            return conn.EnumerateInstances(class_name)
        except Exception:
            return []

    def _prop(inst, *names, default=0):
        for n in names:
            if n in inst:
                return inst[n]
        return default

    def _first_status(inst) -> str:
        raw = _prop(inst, "OperationalStatus", default=[0])
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else 0
        return CIM_STATUS_MAP.get(int(raw or 0), "未知")

    # 控制器 (CIM_ComputerSystem)
    for inst in _instances("CIM_ComputerSystem"):
        result["details"]["controllers"].append({
            "name": str(_prop(inst, "ElementName", "Name", default="控制器")),
            "status": _first_status(inst),
        })

    # 存储池
    total_bytes = 0
    used_bytes = 0
    for inst in _instances("CIM_StoragePool"):
        prim = int(_prop(inst, "Primordial", default=0) or 0)
        total = int(_prop(inst, "TotalManagedSpace", default=0) or 0)
        remaining = int(_prop(inst, "RemainingManagedSpace", default=0) or 0)
        used = max(0, total - remaining) if total else 0
        if prim:
            total_bytes += total
            used_bytes += used
        result["details"]["pools"].append({
            "name": str(_prop(inst, "ElementName", "Name", default="存储池")),
            "size_tb": round(total / (1024 ** 4), 2),
            "used_tb": round(used / (1024 ** 4), 2),
            "used_percent": round(used / total * 100, 1) if total else 0,
        })

    # 卷/LUN
    for inst in _instances("CIM_LogicalDisk"):
        size = int(_prop(inst, "MaxBlockSize", default=0) or 0) * int(_prop(inst, "NumberOfBlocks", default=0) or 0)
        result["details"]["volumes"].append({
            "name": str(_prop(inst, "ElementName", "DeviceID", "Name", default="卷")),
            "size_tb": round(size / (1024 ** 4), 2),
        })

    # 物理磁盘
    for inst in _instances("CIM_PhysicalDisk") or _instances("CIM_MediaAccessDevice"):
        cap = int(_prop(inst, "Capacity", default=0) or 0)
        result["details"]["disks"].append({
            "name": str(_prop(inst, "ElementName", "DeviceID", "Name", default="磁盘")),
            "size_tb": round(cap / (1024 ** 4), 2),
            "status": _first_status(inst),
        })

    if total_bytes:
        result["capacity_tb"] = round(total_bytes / (1024 ** 4), 2)
        result["used_tb"] = round(used_bytes / (1024 ** 4), 2)
        result["used_percent"] = round(used_bytes / total_bytes * 100, 1)

    return result


async def collect_storage(
    protocol: str, ip: str,
    snmp_community: str = "public", snmp_version: str = "2c",
    username: str = "", password: str = "",
) -> dict:
    """按协议采集存储, 返回统一结构。protocol: snmp / smi-s / none。"""
    if protocol == "snmp":
        return await collect_storage_snmp(ip, snmp_community, snmp_version)
    if protocol == "smi-s":
        return await asyncio.to_thread(
            _collect_storage_wbem_sync, ip, username, password
        )
    return {"reachable": False, "capacity_tb": 0.0, "used_tb": 0.0,
            "used_percent": 0.0, "details": {}}
