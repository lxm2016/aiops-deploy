"""Async SQLAlchemy database setup."""
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# 同步会话 (供 port_traffic_service 等同步服务使用)
_sync_url = settings.database_url.replace("+aiosqlite", "").replace("+asyncpg", "")
sync_engine = create_engine(_sync_url, echo=False, future=True, connect_args={"check_same_thread": False} if _sync_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=sync_engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


def _migrate_sqlite():
    """SQLite不支持ALTER COLUMN, 这里对存量库补新增列 (幂等)。"""
    if not settings.database_url.startswith("sqlite"):
        return
    db_path = settings.database_url.split("///")[-1]
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for table, columns in {
            "switch_ports": [("physical", "INTEGER DEFAULT 1")],
            "storage_devices": [
                ("protocol", "TEXT DEFAULT 'none'"),
                ("snmp_community", "TEXT DEFAULT 'public'"),
                ("snmp_version", "TEXT DEFAULT '2c'"),
                ("username", "TEXT DEFAULT ''"),
                ("password", "TEXT DEFAULT ''"),
                ("details", "TEXT DEFAULT '{}'"),
            ],
        }.items():
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cur.fetchone():
                continue  # 新库由create_all建表
            cur.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            for col, ddl in columns:
                if col not in existing:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        conn.commit()
    finally:
        conn.close()


async def init_db():
    from app import models  # noqa: F401 - ensure models registered
    _migrate_sqlite()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
