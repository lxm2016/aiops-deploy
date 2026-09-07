"""AI assistant chat API backed by internal Qwen model."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import ChatMessage, Server, Alert, NetworkDevice, EnvSensor
from app.schemas.schemas import ChatRequest, ChatResponse
from app.services.llm_service import chat_completion

router = APIRouter(prefix="/api/chat", tags=["chat"])


async def _build_monitoring_context(db: AsyncSession) -> str:
    """Build a compact snapshot of current platform state for the LLM."""
    parts = []

    # Server summary
    total = (await db.execute(select(func.count(Server.id)))).scalar() or 0
    online = (await db.execute(
        select(func.count(Server.id)).where(Server.status == "online")
    )).scalar() or 0
    parts.append(f"服务器总数: {total}, 在线: {online}, 离线: {total - online}")

    # Open alerts (top 5)
    result = await db.execute(
        select(Alert).where(Alert.status == "open")
        .order_by(Alert.created_at.desc()).limit(5)
    )
    alerts = result.scalars().all()
    if alerts:
        lines = [f"  - [{a.level}] {a.source}: {a.title}" for a in alerts]
        parts.append("当前未处理告警:\n" + "\n".join(lines))
    else:
        parts.append("当前无未处理告警")

    # Env sensors
    result = await db.execute(select(EnvSensor).limit(5))
    sensors = result.scalars().all()
    if sensors:
        lines = [
            f"  - {s.name}({s.location}): 温度={s.temperature}°C, 湿度={s.humidity}%"
            for s in sensors
        ]
        parts.append("机房环境:\n" + "\n".join(lines))

    return "\n".join(parts)


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Chat with the AI ops assistant. Injects live monitoring context."""
    # Load history
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == req.session_id)
        .order_by(ChatMessage.id.desc())
        .limit(10)
    )
    history_msgs = list(reversed(result.scalars().all()))
    history = [{"role": m.role, "content": m.content} for m in history_msgs]

    # Save user message
    db.add(ChatMessage(session_id=req.session_id, role="user", content=req.message))

    context = await _build_monitoring_context(db)
    reply = await chat_completion(req.message, history=history, context=context)

    db.add(ChatMessage(session_id=req.session_id, role="assistant", content=reply))
    await db.commit()

    return ChatResponse(reply=reply, session_id=req.session_id)


@router.get("/history/{session_id}")
async def get_history(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    )
    msgs = result.scalars().all()
    return [{"role": m.role, "content": m.content, "time": m.created_at} for m in msgs]
