#!/usr/bin/env python3
"""
添加端口流量历史数据表的数据库迁移脚本
"""
import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from app.core.database import engine, Base
from app.models.models import SwitchPortMetric

async def migrate_database():
    """创建端口流量历史数据表"""
    print("正在创建端口流量历史数据表...")
    
    # 创建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # 创建索引
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_switch_port_metrics_device_id ON switch_port_metrics(device_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_switch_port_metrics_port_index ON switch_port_metrics(port_index)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_switch_port_metrics_collected_at ON switch_port_metrics(collected_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_switch_port_metrics_composite ON switch_port_metrics(device_id, port_index, collected_at)"
        )
    
    print("端口流量历史数据表创建完成!")
    print("表结构:")
    print("- SwitchPortMetric: 端口流量历史数据")
    print("  - device_id: 设备ID")
    print("  - port_index: 端口索引")
    print("  - in_octets: 接收字节数")
    print("  - out_octets: 发送字节数")
    print("  - in_errors: 接收错误数")
    print("  - out_errors: 发送错误数")
    print("  - in_mbps: 接收速率(Mbps)")
    print("  - out_mbps: 发送速率(Mbps)")
    print("  - collected_at: 采集时间")

if __name__ == "__main__":
    asyncio.run(migrate_database())