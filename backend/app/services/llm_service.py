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

SYSTEM_PROMPT = """你是一个专业的AIOps智能运维助手，服务于数据中心机房管理员。
你具备全面的IT基础设施监控和分析能力，熟悉以下环境：

**服务器管理：**
- Linux服务器：CentOS、openEuler、Rocky Linux、Ubuntu、龙蜥(Anolis)
- Windows服务器：2008/2012/2016/2019
- 支持CPU、内存、磁盘、网络等全方位监控分析

**虚拟化平台：**
- VMware vCenter/ESXi虚拟化环境
- 虚拟机生命周期管理和性能监控
- 资源分配和使用率优化建议

**网络设备：**
- 华三(H3C)、华为、Dell交换机
- SNMP协议监控，支持CPU、内存、端口状态分析
- 网络流量和性能监控

**存储设备：**
- 华为存储、华三存储、EMC等
- 支持SNMP和SMI-S协议
- 容量使用率和健康状态监控

**环境监控：**
- 机房温湿度传感器监控
- 异常告警分析和处理建议

**核心功能：**
1. **智能状态分析** - 自动分析所有设备状态，识别正常/异常/严重问题
2. **故障诊断** - 基于告警信息和监控数据，给出具体的排查建议
3. **性能分析** - 解读各类监控指标，提供优化建议
4. **操作指导** - 提供具体的运维操作步骤和命令
5. **预测性维护** - 基于历史趋势预测潜在问题

**回答格式要求：**
- 使用Markdown格式，结构清晰
- 对于复杂分析，使用表格、列表等可视化方式
- 提供具体的操作建议和命令
- 对异常状态给出明确的优先级和处理建议

请用简洁专业的中文回答，重点关注问题的根本原因和解决方案。"""


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
