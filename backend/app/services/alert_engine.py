"""Alert engine: evaluates metrics against thresholds and raises alerts."""
from datetime import datetime
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

        title = f"{server_name} {metric.replace('_percent', '')}使用率 {value:.1f}% 超过阈值"
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
