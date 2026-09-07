"""System settings API: LLM (内网千问大模型) runtime configuration."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import SystemConfig
from app.schemas.schemas import LlmConfigIn
from app.services import llm_service

router = APIRouter(prefix="/api/settings", tags=["settings"])
settings = get_settings()


async def _get_all(db: AsyncSession) -> dict:
    result = await db.execute(select(SystemConfig))
    return {row.key: row.value for row in result.scalars().all()}


async def _set(db: AsyncSession, key: str, value: str):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemConfig(key=key, value=value))


@router.get("/llm")
async def get_llm_config(db: AsyncSession = Depends(get_db)):
    """返回当前生效的LLM配置 (数据库优先, 未配置时回退.env默认值)。"""
    stored = await _get_all(db)
    return {
        "base_url": stored.get("llm_base_url") or settings.llm_base_url,
        "model": stored.get("llm_model") or settings.llm_model,
        "api_key": stored.get("llm_api_key") or settings.llm_api_key,
    }


@router.put("/llm")
async def save_llm_config(data: LlmConfigIn, db: AsyncSession = Depends(get_db)):
    await _set(db, "llm_base_url", data.base_url)
    await _set(db, "llm_model", data.model)
    await _set(db, "llm_api_key", data.api_key)
    await db.commit()
    # 立即刷新内存中的运行时配置
    llm_service.reload_config()
    return {"ok": True}


@router.post("/llm/test")
async def test_llm_config(data: LlmConfigIn):
    """用给定配置实际调用一次模型, 验证连通性。"""
    ok, detail = await llm_service.test_connection(
        data.base_url, data.api_key, data.model
    )
    return {"ok": ok, "detail": detail}
