"""Application configuration via environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "AIOps Platform"
    app_version: str = "1.0.2"
    debug: bool = True

    # Database (SQLite for easy deploy; switch to MySQL/Postgres in prod)
    database_url: str = "sqlite+aiosqlite:///./aiops.db"

    # Auth
    secret_key: str = "change-me-in-production-aiops-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # Qwen LLM (OpenAI-compatible API, e.g. vLLM / Ollama / Xinference)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "qwen2.5"

    # Agent
    agent_token: str = "aiops-agent-shared-token"

    # ---------------------------------------------------------------
    # 监控数据保留天数 (超过自动清理)。
    # 原值 90 天: Agent 每 5 秒上报一次, 20 台机器约 34.6 万行/天,
    # 90 天即 3100 万行, 数据库可达数十 GB, 是"越用越卡"的主因。
    # 下调为 30 天; 如需更长历史, 可改回, 但务必同步放大磁盘与定期维护。
    # ---------------------------------------------------------------
    metric_retention_days: int = 30

    # 历史指标查询单次最大返回行数 (先按时间倒序截断再抽样)。
    # 防止查询长周期时把上百万行(每行含 raw JSON)一次性载入内存。
    metrics_query_max_rows: int = 20000

    # ---------------------------------------------------------------
    # 端口流量历史采集开关, 默认 False (关闭)。
    # 该功能在每次 SNMP 轮询中按"每个端口"单独建连接并 commit,
    # 且为同步阻塞调用, 一台 48 口交换机即 48 次写库, 每 2 分钟一轮,
    # 会长时间占住事件循环 —— 是页面转圈/超时的直接来源。
    # 当前前端并没有对应的展示页面, 关闭不影响任何可见功能。
    # ---------------------------------------------------------------
    enable_port_traffic_history: bool = False

    # VMware vCenter (optional, configured via UI as well)
    vmware_host: str = ""
    vmware_user: str = ""
    vmware_password: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
