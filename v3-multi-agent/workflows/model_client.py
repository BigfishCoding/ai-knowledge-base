"""LLM 模型客户端封装。

统一封装 OpenAI SDK 调用，对外暴露两个高层接口：

- ``chat()``: 单轮对话，返回 ``(text, usage)`` 元组
- ``chat_json()``: 要求模型返回 JSON，解析后返回字典

模型配置全部来自环境变量（红线：禁止硬编码 API Key）：

- ``LLM_API_KEY``: API Key，必填
- ``LLM_BASE_URL``: Base URL，默认 DeepSeek 官方地址
- ``LLM_MODEL``: 模型名，默认 ``deepseek-chat``
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

ENV_API_KEY = "LLM_API_KEY"
ENV_BASE_URL = "LLM_BASE_URL"
ENV_MODEL = "LLM_MODEL"

JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$")

# 项目根目录（.env 所在位置）：workflows/model_client.py 向上两级
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


# ── 环境变量加载 ──────────────────────────────────────────────────────────


def load_env() -> None:
    """从项目根目录 .env 加载环境变量（不覆盖已存在的变量）。

    在模块 import 时自动调用，使 chat()/_client() 以及调用方
    通过 ``os.environ.get(ENV_GITHUB_TOKEN)`` 都能读到 .env 配置。
    """
    if not ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE)
    except ImportError:
        # 兜底：手动解析 .env（忽略注释行与空行）
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()


# ── 客户端构建 ────────────────────────────────────────────────────────────


def _client() -> OpenAI:
    """构建 OpenAI 客户端实例。

    Returns:
        配置好 API Key 的 OpenAI 客户端。

    Raises:
        RuntimeError: 当 LLM_API_KEY 未设置时抛出。
    """
    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        raise RuntimeError(
            f"环境变量 {ENV_API_KEY} 未设置，请检查 .env 文件"
        )
    base_url = os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL)
    # 强制不走代理（trust_env=False 忽略 HTTP_PROXY/HTTPS_PROXY 环境变量）
    http_client = httpx.Client(trust_env=False)
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


def _model() -> str:
    """返回当前使用的模型名。"""
    return os.environ.get(ENV_MODEL, DEFAULT_MODEL)


# ── 高层接口 ──────────────────────────────────────────────────────────────


def chat(prompt: str, system: str = "", model: str | None = None) -> tuple[str, dict[str, Any]]:
    """发送单轮对话请求。

    Args:
        prompt: 用户消息内容。
        system: 可选系统提示词，置空则省略。
        model: 覆盖默认模型名，None 时使用环境变量配置。

    Returns:
        ``(text, usage)`` 元组：text 为模型回复文本，
        usage 为 token 用量字典（含 prompt_tokens / completion_tokens / total_tokens）。
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = _client().chat.completions.create(
        model=model or _model(),
        messages=messages,
    )

    text = response.choices[0].message.content or ""
    usage = response.usage.model_dump() if response.usage else {}
    logger.debug("LLM 调用完成, model=%s, usage=%s", model or _model(), usage)
    return text, usage


def chat_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """发送对话请求并强制解析 JSON 响应。

    Args:
        prompt: 用户消息内容，应明确要求返回 JSON。
        system: 可选系统提示词。
        model: 覆盖默认模型名。

    Returns:
        ``(parsed_json, usage)`` 元组：parsed_json 为解析后的字典，
        usage 为 token 用量字典（含 prompt_tokens / completion_tokens / total_tokens）。

    Raises:
        ValueError: 当模型返回内容无法解析为 JSON 时抛出。
    """
    json_system = (
        f"{system}\n请严格返回合法 JSON，不要包含任何多余文字或 markdown 代码块。"
        if system
        else "请严格返回合法 JSON，不要包含任何多余文字或 markdown 代码块。"
    )
    text, usage = chat(prompt, system=json_system, model=model)

    cleaned = JSON_FENCE_PATTERN.sub("", text.strip())

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("模型返回内容无法解析为 JSON: %s", text)
        raise ValueError(f"chat_json 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        logger.error("模型返回 JSON 根节点应为 object, 实际为 %s", type(data).__name__)
        raise ValueError(f"chat_json 返回根节点类型错误: {type(data).__name__}")

    return data, usage


# ── Token 用量追踪 ────────────────────────────────────────────────────────


def accumulate_usage(tracker: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    """将一次 LLM 调用的 token 用量累加到追踪器。

    每次调用都会自增 llm_calls，并累加三类 token 计数。
    不修改传入的 tracker，返回新字典（保持节点纯函数特性）。

    Args:
        tracker: 当前累计的用量追踪字典。
        usage: 单次调用返回的 usage 字典。

    Returns:
        累加后的新追踪字典。
    """
    accumulated = dict(tracker)
    accumulated["llm_calls"] = accumulated.get("llm_calls", 0) + 1
    accumulated["prompt_tokens"] = accumulated.get("prompt_tokens", 0) + int(
        usage.get("prompt_tokens", 0)
    )
    accumulated["completion_tokens"] = accumulated.get("completion_tokens", 0) + int(
        usage.get("completion_tokens", 0)
    )
    accumulated["total_tokens"] = accumulated.get("total_tokens", 0) + int(
        usage.get("total_tokens", 0)
    )
    return accumulated
