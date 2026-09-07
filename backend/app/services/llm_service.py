"""Qwen LLM integration via OpenAI-compatible API (vLLM/Ollama/Xinference).

LLM 配置支持运行时修改: 数据库 system_config 表优先, 未配置时回退 .env 默认值。
前端在 AI 助手页面的"模型配置"中修改, 保存后立即生效, 无需重启服务。
"""
from typing import List, Optional, Tuple

from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()

# 运行时生效的LLM配置 (由 reload_config 从数据库刷新)
_runtime = {
    "base_url": settings.llm_base_url,
    "model": settings.llm_model,
    "api_key": settings.llm_api_key,
}

SYSTEM_PROMPT = """你是一个专业的AIOps运维助手，服务于数据中心机房管理员。
你熟悉以下环境：
- VMware虚拟化平台（vCenter/ESXi）
- Linux服务器：CentOS、openEuler、Rocky Linux、Ubuntu、龙蜥(Anolis)
- Windows服务器：2008/2012/2016/2019
- 网络设备：华三(H3C)、华为、Dell交换机
- 存储设备：华为存储、华三存储
- 机房温湿度监控

你可以帮助用户：
1. 分析告警和故障，给出排查建议
2. 解读监控指标（CPU/内存/磁盘/网络）
3. 提供运维操作建议和命令
4. 回答虚拟化、网络、存储相关问题

请用简洁专业的中文回答。"""


async def reload_config():
    """从数据库加载LLM配置, 覆盖.env默认值。启动时和保存配置后调用。"""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models import SystemConfig

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(SystemConfig))).scalars().all()
    stored = {r.key: r.value for r in rows}
    _runtime["base_url"] = stored.get("llm_base_url") or settings.llm_base_url
    _runtime["model"] = stored.get("llm_model") or settings.llm_model
    _runtime["api_key"] = stored.get("llm_api_key") or settings.llm_api_key


def _get_client(base_url: Optional[str] = None, api_key: Optional[str] = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=base_url or _runtime["base_url"],
        api_key=api_key or _runtime["api_key"],
        timeout=120.0,
    )


async def chat_completion(
    message: str,
    history: Optional[List[dict]] = None,
    context: str = "",
) -> str:
    """Send a chat request to the internal Qwen model.

    Args:
        message: user message
        history: previous messages [{role, content}, ...]
        context: optional monitoring context injected into the prompt
    """
    client = _get_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({
            "role": "system",
            "content": f"以下是当前监控平台的实时数据，供你分析参考：\n{context}",
        })
    if history:
        messages.extend(history[-10:])  # keep last 10 turns
    messages.append({"role": "user", "content": message})

    try:
        resp = await client.chat.completions.create(
            model=_runtime["model"],
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
        )
        return resp.choices[0].message.content or "（模型未返回内容）"
    except Exception as e:
        return f"无法连接内网大模型服务（{_runtime['base_url']}）：{e}\n请确认千问模型服务已启动。"


async def test_connection(base_url: str, api_key: str, model: str) -> Tuple[bool, str]:
    """用指定配置实际调用一次模型, 验证连通性。"""
    try:
        client = AsyncOpenAI(
            base_url=base_url, api_key=api_key or "EMPTY", timeout=30.0
        )
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "你好"}],
            temperature=0.3,
            max_tokens=16,
        )
        return True, f"连接成功，模型 {model} 响应正常"
    except Exception as e:
        return False, f"连接失败: {e}"


async def analyze_alert(alert_info: str) -> str:
    """Ask the LLM to analyze an alert and give troubleshooting advice."""
    return await chat_completion(
        f"请分析以下告警信息，给出可能的原因和排查步骤：\n\n{alert_info}"
    )
