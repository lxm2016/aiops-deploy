"""Alert engine: evaluates metrics against thresholds and raises alerts.

── 稳定性修复说明 ──────────────────────────────────────────────
原实现每次指标超阈值都无条件新增一条 Alert, 但 Agent 每 5 秒就该指标
上报一次。若某台服务器 CPU 长期高于阈值, 一天就会写入上万条内容完全
相同的重复告警 —— 既撑大 alerts 表, 也让告警中心充满噪音。

现加入去重: 同一来源(source) + 同一指标若已存在未解决(open)的告警,
则不再重复创建; 待原告警被「解决」后才允许再次触发。
────────────────────────────────────────────────────────────────
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert

# Thresholds: (metric, warning, critical)
THRESHOLDS = [
    ("cpu_percent", 80.0, 95.0),
    ("mem_percent", 85.0, 95.0),
    ("disk_percent", 85.0, 95.0),
]


async def evaluate_server_metrics(
    db: AsyncSession, server_name: str, metrics: dict
) -> list:
    """Check metric values against thresholds, create alerts if exceeded.

    Returns list of created Alert objects.
    """
    created = []
    for metric, warn, crit in THRESHOLDS:
        value = metrics.get(metric, 0.0) or 0.0
        if value >= crit:
            level = "critical"
        elif value >= warn:
            level = "warning"
        else:
            continue

        # 去重: 同一服务器同一指标若已有未解决告警, 跳过本次创建
        prefix = f"{server_name} {metric.replace('_percent', '')}使用率"
        dup = await db.execute(
            select(Alert.id)
            .where(
                Alert.status == "open",
                Alert.source == server_name,
                Alert.title.startswith(prefix),
            )
            .limit(1)
        )
        if dup.scalar_one_or_none() is not None:
            continue

        title = f"{prefix} {value:.1f}% 超过阈值"
        alert = Alert(
            level=level,
            category="server",
            source=server_name,
            title=title,
            detail=f"{metric}={value:.1f}%，告警阈值: warning={warn}%, critical={crit}%",
            status="open",
            created_at=datetime.utcnow(),
        )
        db.add(alert)
        created.append(alert)

    if created:
        await db.flush()
    return created


async def evaluate_env_reading(
    db: AsyncSession, sensor_name: str, temperature: float, humidity: float
) -> list:
    """Check temperature/humidity against datacenter thresholds."""
    created = []
    if temperature is not None:
        if temperature >= 35:
            level, title = "critical", f"机房温度过高: {temperature:.1f}°C"
        elif temperature >= 30:
            level, title = "warning", f"机房温度偏高: {temperature:.1f}°C"
        else:
            level, title = None, None
        if level:
            alert = Alert(
                level=level, category="env", source=sensor_name,
                title=title, detail=f"温度={temperature:.1f}°C",
                status="open", created_at=datetime.utcnow(),
            )
            db.add(alert)
            created.append(alert)

    if humidity is not None:
        if humidity >= 80 or humidity <= 20:
            level = "critical"
        elif humidity >= 70 or humidity <= 30:
            level = "warning"
        else:
            level = None
        if level:
            alert = Alert(
                level=level, category="env", source=sensor_name,
                title=f"机房湿度异常: {humidity:.1f}%",
                detail=f"湿度={humidity:.1f}%",
                status="open", created_at=datetime.utcnow(),
            )
            db.add(alert)
            created.append(alert)

    if created:
        await db.flush()
    return created
