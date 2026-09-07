"""AIOps Platform - FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db, AsyncSessionLocal
from app.api import auth, servers, vmware, devices, alerts, chat, agents, racks, settings as settings_api
from app.api.auth import ensure_admin_user
from app.services import llm_service
from app.services.scheduler import start_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    async with AsyncSessionLocal() as db:
        await ensure_admin_user(db)
    await llm_service.reload_config()  # 加载界面保存的LLM配置
    start_scheduler()
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AIOps运维监控平台 - 服务器/VMware/网络设备/存储/温湿度监控 + 千问大模型智能分析",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(servers.router)
app.include_router(vmware.router)
app.include_router(devices.router)
app.include_router(alerts.router)
app.include_router(chat.router)
app.include_router(agents.router)
app.include_router(racks.router)
app.include_router(settings_api.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.app_version}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
