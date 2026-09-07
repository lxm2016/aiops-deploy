"""Alert management API."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Alert
from app.schemas.schemas import AlertOut
from app.services.llm_service import analyze_alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=List[AlertOut])
async def list_alerts(
    status: Optional[str] = None,
    level: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert)
    if status:
        stmt = stmt.where(Alert.status == status)
    if level:
        stmt = stmt.where(Alert.level == level)
    if category:
        stmt = stmt.where(Alert.category == category)
    result = await db.execute(
        stmt.order_by(Alert.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.post("/{alert_id}/ack")
async def ack_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    alert.status = "ack"
    await db.commit()
    return {"ok": True}


@router.post("/{alert_id}/resolve")
async def resolve_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    alert.status = "resolved"
    alert.resolved_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.get("/{alert_id}/analyze")
async def analyze_alert_api(alert_id: int, db: AsyncSession = Depends(get_db)):
    """Use Qwen LLM to analyze an alert and provide troubleshooting advice."""
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    info = (
        f"告警级别: {alert.level}\n"
        f"告警类别: {alert.category}\n"
        f"来源: {alert.source}\n"
        f"标题: {alert.title}\n"
        f"详情: {alert.detail}\n"
        f"时间: {alert.created_at}"
    )
    analysis = await analyze_alert(info)
    return {"alert_id": alert_id, "analysis": analysis}
