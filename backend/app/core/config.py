"""Application configuration via environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "AIOps Platform"
    app_version: str = "1.0.0"
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

    # 监控数据保留天数 (超过自动清理)
    metric_retention_days: int = 90

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
