"""Async SQLAlchemy database setup.

── 稳定性修复说明 ──────────────────────────────────────────────
原实现:  engine = create_async_engine(settings.database_url, echo=False, future=True)

问题: SQLite 默认 journal_mode=delete, 任意一次写入都会独占整库,
      期间所有读请求被阻塞。平台里后台采集任务频繁写库(端口流量按端口
      逐条 commit), 于是页面表现为"转圈直到前端 60s 超时"。

修复:  1) 开启 WAL —— 读写可并发, 写入不再阻塞读取
       2) busy_timeout=30s —— 遇到锁时等待而非立刻抛错
       3) pool_pre_ping + pool_recycle —— 长时间空闲后连接不会僵死
       4) 同步引擎(sync_engine)同样启用 WAL, 保证两条链路一致
────────────────────────────────────────────────────────────────
"""
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_IS_SQLITE = settings.database_url.startswith("sqlite")

# ---------- 异步引擎 ----------
_engine_kwargs = dict(echo=False, future=True)
if _IS_SQLITE:
    _engine_kwargs.update(
        pool_pre_ping=True,      # 取用连接前先探活, 自动丢弃失效连接
        pool_recycle=1800,       # 30 分钟回收, 避免长期空闲连接僵死
        connect_args={
            "timeout": 30,             # sqlite3 层等锁 30 秒
            "check_same_thread": False,
        },
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _apply_sqlite_pragmas(dbapi_conn):
    """每个新连接都应用一次的关键 PRAGMA。"""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")      # 核心: 读写并发
        cur.execute("PRAGMA busy_timeout=30000")    # 等锁 30 秒
        cur.execute("PRAGMA synchronous=NORMAL")    # WAL 下兼顾安全与性能
        cur.execute("PRAGMA cache_size=-64000")     # 64MB 页缓存
        cur.execute("PRAGMA temp_store=MEMORY")     # 排序/临时表走内存
    except Exception:
        pass
    finally:
        cur.close()


if _IS_SQLITE:
    @event.listens_for(engine.sync_engine, "connect")
    def _aiops_sqlite_pragma(dbapi_conn, _rec):  # noqa: ANN001
        _apply_sqlite_pragmas(dbapi_conn)


# ---------- 同步引擎 (供 port_traffic_service 等同步服务使用) ----------
_sync_url = settings.database_url.replace("+aiosqlite", "").replace("+asyncpg", "")
_sync_kwargs = dict(echo=False, future=True)
if _sync_url.startswith("sqlite"):
    _sync_kwargs["connect_args"] = {"timeout": 30, "check_same_thread": False}

sync_engine = create_engine(_sync_url, **_sync_kwargs)
SessionLocal = sessionmaker(bind=sync_engine, autoflush=False, expire_on_commit=False)

if _sync_url.startswith("sqlite"):
    @event.listens_for(sync_engine, "connect")
    def _aiops_sqlite_pragma_sync(dbapi_conn, _rec):  # noqa: ANN001
        _apply_sqlite_pragmas(dbapi_conn)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


def _migrate_sqlite():
    """SQLite不支持ALTER COLUMN, 这里对存量库补新增列 (幂等)。"""
    if not _IS_SQLITE:
        return
    db_path = settings.database_url.split("///")[-1]
    # timeout=30: 避免服务启动时恰逢写锁而直接抛 database is locked
    conn = sqlite3.connect(db_path, timeout=30)
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
