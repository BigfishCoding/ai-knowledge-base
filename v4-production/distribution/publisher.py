"""多渠道消息推送模块（异步，基于 aiohttp）。

将 :mod:`distribution.formatter` 渲染好的文本/卡片推送到各分发渠道，
本模块只负责网络与渠道调用，不做任何格式化：

- :class:`BasePublisher`: 抽象基类，定义 ``send_message`` / ``send_digest`` 接口
- :class:`TelegramPublisher`: 通过 Telegram Bot API 发送 MarkdownV2 消息
- :class:`FeishuPublisher`: 通过飞书 Webhook 发送卡片消息
- :class:`OpenClawPublisher`: 通过 OpenClaw 本地 gateway 发送微信消息
- :func:`publish_daily_digest`: 统一异步入口，并发发布到所有已配置渠道

渠道凭据一律从环境变量读取（红线：禁止硬编码 Token），模块导入时自动加载
项目根目录 ``.env``。
"""

import asyncio
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

# 项目根目录注入 sys.path，保证 distribution 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from distribution.formatter import (
    DEFAULT_KNOWLEDGE_DIR,
    DEFAULT_TOP_N,
    generate_daily_digest,
)

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

# 渠道标识（与 formatter digest 返回键保持一致）
CHANNEL_TELEGRAM = "telegram"
CHANNEL_FEISHU = "feishu"
CHANNEL_OPENCLAW = "openclaw"

# 环境变量名
ENV_TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
ENV_FEISHU_WEBHOOK_URL = "FEISHU_WEBHOOK_URL"
ENV_OPENCLAW_API_URL = "OPENCLAW_API_URL"

# 项目根目录（.env 所在位置）：distribution/publisher.py 向上两级
ENV_FILE = PROJECT_ROOT / ".env"

# 请求超时（秒）
REQUEST_TIMEOUT_SECONDS = 30

# Telegram Bot API 参数与响应字段
TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_SEND_MESSAGE_PATH = "/bot{token}/sendMessage"
TELEGRAM_PARSE_MODE = "MarkdownV2"
TG_PARAM_CHAT_ID = "chat_id"
TG_PARAM_TEXT = "text"
TG_PARAM_PARSE_MODE = "parse_mode"
TG_RESPONSE_OK = "ok"
TG_RESPONSE_RESULT = "result"
TG_RESPONSE_MESSAGE_ID = "message_id"
TG_RESPONSE_DESCRIPTION = "description"

# 飞书 Webhook 请求/响应字段
FEISHU_MSG_TYPE_KEY = "msg_type"
FEISHU_MSG_TYPE_TEXT = "text"
FEISHU_CONTENT_KEY = "content"
FEISHU_RESPONSE_CODE = "code"
FEISHU_RESPONSE_MSG = "msg"
FEISHU_SUCCESS_CODE = 0

# OpenClaw 本地 gateway 请求/响应字段
DEFAULT_OPENCLAW_API_URL = "http://localhost:3000"
OPENCLAW_MESSAGE_PATH = "/api/message"
OPENCLAW_CHANNELS_PATH = "/api/channels"
OPENCLAW_MSG_CHANNEL = "weixin"
OPENCLAW_REQ_CHANNEL = "channel"
OPENCLAW_REQ_TEXT = "text"
OPENCLAW_RESPONSE_ID = "id"
OPENCLAW_RESPONSE_ERROR = "error"
OPENCLAW_RESPONSE_CODE = "code"

# 失败兜底描述模板
ERROR_ENV_MISSING = "环境变量 {} 未设置，请检查 .env 文件"
ERROR_DIGEST_KEY_MISSING = "digest 缺少渠道 {} 的格式化内容"
ERROR_TELEGRAM_OK_FALSE = "Telegram API 返回 ok=false: {}"
ERROR_FEISHU_NONZERO_CODE = "飞书 Webhook 返回 code={}: {}"


# ── 环境变量加载 ──────────────────────────────────────────────────────────


def load_env() -> None:
    """从项目根目录 .env 加载环境变量（不覆盖已存在的变量）。

    模块导入时自动调用，使发布器与调用方都能通过
    ``os.environ.get(ENV_TELEGRAM_BOT_TOKEN)`` 读到 .env 配置；
    dotenv 不可用时回退为手动解析。
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


# ── 数据模型 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublishResult:
    """单次发布操作的结果。

    Attributes:
        channel: 渠道标识（``telegram`` / ``feishu``）。
        success: 是否发布成功。
        message_id: 平台返回的消息 ID；飞书无此字段时为 None。
        error: 失败原因描述；成功时为 None。
    """

    channel: str
    success: bool
    message_id: str | None = None
    error: str | None = None


# ── 抽象基类 ──────────────────────────────────────────────────────────────


class BasePublisher(ABC):
    """渠道推送抽象基类。

    Attributes:
        channel: 渠道标识，子类必须覆写。
    """

    channel: str = ""

    @abstractmethod
    async def send_message(self, text: str) -> PublishResult:
        """发送一条纯文本消息。

        Args:
            text: 已格式化好的消息文本。

        Returns:
            本次发布的结果，失败时 error 携带原因。
        """

    @abstractmethod
    async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
        """发送一份多平台简报（只取本渠道对应的格式）。

        Args:
            digest: :func:`generate_daily_digest` 返回的简报字典。

        Returns:
            本次发布的结果，失败时 error 携带原因。
        """


# ── 通用 HTTP 助手 ────────────────────────────────────────────────────────


async def _post_json(
    url: str,
    *,
    params: dict[str, str] | None = None,
    payload: Any = None,
) -> Any:
    """向指定 URL 发起 POST 请求并解析 JSON 响应。

    Args:
        url: 请求地址。
        params: URL 查询参数。
        payload: JSON 请求体。

    Returns:
        解析后的 JSON 响应（结构取决于各平台 API）。

    Raises:
        aiohttp.ClientError: 网络错误或非 2xx 状态码。
        ValueError: 响应体无法解析为 JSON。
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, params=params, json=payload) as resp:
            # content_type=None：兼容平台返回的非标准 Content-Type
            return await resp.json(content_type=None)


# ── Telegram 发布器 ───────────────────────────────────────────────────────


class TelegramPublisher(BasePublisher):
    """通过 Telegram Bot API 异步发送 MarkdownV2 消息。

    依赖环境变量 ``TELEGRAM_BOT_TOKEN`` 与 ``TELEGRAM_CHAT_ID``，
    请求超时 30 秒；``send_message`` 要求文本已按 MarkdownV2 转义
    （可直接使用 :func:`distribution.formatter.json_to_telegram` 的输出）。

    Raises:
        ValueError: 构造函数在凭据缺失时抛出。
    """

    channel = CHANNEL_TELEGRAM

    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        """初始化 Telegram 发布器。

        Args:
            token: Bot Token；None 时从环境变量读取。
            chat_id: 目标会话 ID；None 时从环境变量读取。

        Raises:
            ValueError: Token 或会话 ID 缺失时抛出。
        """
        self._token = token or os.environ.get(ENV_TELEGRAM_BOT_TOKEN, "")
        self._chat_id = chat_id or os.environ.get(ENV_TELEGRAM_CHAT_ID, "")
        if not self._token:
            raise ValueError(ERROR_ENV_MISSING.format(ENV_TELEGRAM_BOT_TOKEN))
        if not self._chat_id:
            raise ValueError(ERROR_ENV_MISSING.format(ENV_TELEGRAM_CHAT_ID))
        self._send_url = TELEGRAM_API_BASE + TELEGRAM_SEND_MESSAGE_PATH.format(
            token=self._token
        )

    async def send_message(self, text: str) -> PublishResult:
        """发送一条 MarkdownV2 文本消息。

        Args:
            text: 已按 MarkdownV2 转义的文本。

        Returns:
            本次发布的结果。
        """
        try:
            payload = await _post_json(
                self._send_url,
                params={
                    TG_PARAM_CHAT_ID: self._chat_id,
                    TG_PARAM_TEXT: text,
                    TG_PARAM_PARSE_MODE: TELEGRAM_PARSE_MODE,
                },
            )
        except (aiohttp.ClientError, ValueError) as exc:
            return PublishResult(CHANNEL_TELEGRAM, False, error=str(exc))

        if not isinstance(payload, dict) or not payload.get(TG_RESPONSE_OK):
            description = (
                payload.get(TG_RESPONSE_DESCRIPTION)
                if isinstance(payload, dict)
                else str(payload)
            )
            return PublishResult(
                CHANNEL_TELEGRAM,
                False,
                error=ERROR_TELEGRAM_OK_FALSE.format(description),
            )

        result = payload.get(TG_RESPONSE_RESULT) or {}
        message_id = result.get(TG_RESPONSE_MESSAGE_ID)
        return PublishResult(
            CHANNEL_TELEGRAM,
            True,
            message_id=str(message_id) if message_id is not None else None,
        )

    async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
        """发送简报的 Telegram 格式（``digest["telegram"]``）。

        Args:
            digest: :func:`generate_daily_digest` 返回的简报字典。

        Returns:
            本次发布的结果。
        """
        text = digest.get(CHANNEL_TELEGRAM) if isinstance(digest, dict) else None
        if not isinstance(text, str):
            return PublishResult(
                CHANNEL_TELEGRAM,
                False,
                error=ERROR_DIGEST_KEY_MISSING.format(CHANNEL_TELEGRAM),
            )
        return await self.send_message(text)


# ── 飞书发布器 ────────────────────────────────────────────────────────────


class FeishuPublisher(BasePublisher):
    """通过飞书 Webhook 发送卡片消息。

    依赖环境变量 ``FEISHU_WEBHOOK_URL``，请求超时 30 秒；
    飞书 Webhook 不返回 message_id，故结果中该项恒为 None。

    Raises:
        ValueError: 构造函数在 Webhook 地址缺失时抛出。
    """

    channel = CHANNEL_FEISHU

    def __init__(self, webhook_url: str | None = None) -> None:
        """初始化飞书发布器。

        Args:
            webhook_url: Webhook 地址；None 时从环境变量读取。

        Raises:
            ValueError: Webhook 地址缺失时抛出。
        """
        self._webhook_url = webhook_url or os.environ.get(
            ENV_FEISHU_WEBHOOK_URL, ""
        )
        if not self._webhook_url:
            raise ValueError(ERROR_ENV_MISSING.format(ENV_FEISHU_WEBHOOK_URL))

    async def send_message(self, text: str) -> PublishResult:
        """发送一条纯文本消息。

        Args:
            text: 消息正文。

        Returns:
            本次发布的结果。
        """
        payload = {
            FEISHU_MSG_TYPE_KEY: FEISHU_MSG_TYPE_TEXT,
            FEISHU_CONTENT_KEY: {FEISHU_MSG_TYPE_TEXT: text},
        }
        try:
            response = await _post_json(self._webhook_url, payload=payload)
        except (aiohttp.ClientError, ValueError) as exc:
            return PublishResult(CHANNEL_FEISHU, False, error=str(exc))
        return self._result_from_response(response)

    async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
        """发送简报的飞书卡片（``digest["feishu"]``）。

        Args:
            digest: :func:`generate_daily_digest` 返回的简报字典。

        Returns:
            本次发布的结果。
        """
        card = digest.get(CHANNEL_FEISHU) if isinstance(digest, dict) else None
        if not isinstance(card, dict):
            return PublishResult(
                CHANNEL_FEISHU,
                False,
                error=ERROR_DIGEST_KEY_MISSING.format(CHANNEL_FEISHU),
            )
        try:
            response = await _post_json(self._webhook_url, payload=card)
        except (aiohttp.ClientError, ValueError) as exc:
            return PublishResult(CHANNEL_FEISHU, False, error=str(exc))
        return self._result_from_response(response)

    def _result_from_response(self, response: Any) -> PublishResult:
        """将飞书 Webhook 响应转换为发布结果。

        Args:
            response: ``_post_json`` 返回的 JSON 响应。

        Returns:
            发布成功与否对应的结果对象。
        """
        code = (
            response.get(FEISHU_RESPONSE_CODE)
            if isinstance(response, dict)
            else None
        )
        if code != FEISHU_SUCCESS_CODE:
            msg = (
                response.get(FEISHU_RESPONSE_MSG)
                if isinstance(response, dict)
                else str(response)
            )
            return PublishResult(
                CHANNEL_FEISHU,
                False,
                error=ERROR_FEISHU_NONZERO_CODE.format(code, msg),
            )
        return PublishResult(CHANNEL_FEISHU, True)


# ── OpenClaw 发布器 ──────────────────────────────────────────────────────


class OpenClawPublisher(BasePublisher):
    """通过 OpenClaw 本地 gateway 的 API 发送微信消息。

    gateway 默认运行在 ``http://localhost:3000``，可通过环境变量
    ``OPENCLAW_API_URL`` 覆盖。发送端点 ``POST /api/message``，
    请求体 ``{"channel": "weixin", "text": content}``。

    由于 gateway 地址有默认值，构造函数不会因配置缺失而报错；
    gateway 未启动时发送失败，由返回的 :class:`PublishResult` 携带原因。
    """

    channel = CHANNEL_OPENCLAW

    def __init__(self, api_url: str | None = None) -> None:
        """初始化 OpenClaw 发布器。

        Args:
            api_url: gateway 地址；None 时读取环境变量
                ``OPENCLAW_API_URL``，未设置则使用默认值
                :data:`DEFAULT_OPENCLAW_API_URL`。
        """
        self._api_url = api_url or os.environ.get(
            ENV_OPENCLAW_API_URL, DEFAULT_OPENCLAW_API_URL
        )
        self._send_url = self._api_url.rstrip("/") + OPENCLAW_MESSAGE_PATH

    async def send_message(self, text: str) -> PublishResult:
        """发送一条微信消息。

        Args:
            text: 消息正文。

        Returns:
            本次发布的结果，失败时 error 携带原因。
        """
        payload = {
            OPENCLAW_REQ_CHANNEL: OPENCLAW_MSG_CHANNEL,
            OPENCLAW_REQ_TEXT: text,
        }
        try:
            response = await _post_json(self._send_url, payload=payload)
        except (aiohttp.ClientError, ValueError) as exc:
            return PublishResult(CHANNEL_OPENCLAW, False, error=str(exc))
        return self._result_from_response(response)

    async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
        """发送简报的 Markdown 格式（``digest["markdown"]``）。

        WeChat 不识别 MarkdownV2 转义符，故取可读性最好的 markdown 纯文本。

        Args:
            digest: :func:`generate_daily_digest` 返回的简报字典。

        Returns:
            本次发布的结果。
        """
        text = digest.get("markdown") if isinstance(digest, dict) else None
        if not isinstance(text, str):
            return PublishResult(
                CHANNEL_OPENCLAW,
                False,
                error=ERROR_DIGEST_KEY_MISSING.format("markdown"),
            )
        return await self.send_message(text)

    def _result_from_response(self, response: Any) -> PublishResult:
        """将 OpenClaw gateway 响应转换为发布结果。

        gateway 尚未提供正式响应契约，此处做防御式解析：优先识别
        ``error`` 字段，其次识别非零 ``code``，否则视为成功并尽量提取
        ``id`` 作为 message_id。

        Args:
            response: ``_post_json`` 返回的 JSON 响应。

        Returns:
            发布成功与否对应的结果对象。
        """
        if not isinstance(response, dict):
            return PublishResult(
                CHANNEL_OPENCLAW, False, error=f"OpenClaw 返回非 JSON 对象: {response!r}"
            )
        error = response.get(OPENCLAW_RESPONSE_ERROR)
        if error:
            return PublishResult(CHANNEL_OPENCLAW, False, error=str(error))
        code = response.get(OPENCLAW_RESPONSE_CODE)
        if isinstance(code, int) and code != 0:
            return PublishResult(
                CHANNEL_OPENCLAW, False, error=f"OpenClaw 返回 code={code}"
            )
        message_id = response.get(OPENCLAW_RESPONSE_ID)
        return PublishResult(
            CHANNEL_OPENCLAW,
            True,
            message_id=str(message_id) if message_id is not None else None,
        )


# ── 统一入口 ──────────────────────────────────────────────────────────────


def _build_publishers() -> list[BasePublisher]:
    """构建所有已配置渠道的发布器。

    凭据缺失的渠道记录 warning 后跳过，便于部分渠道未配置时正常运行。

    Returns:
        已配置的发布器列表（可为空）。
    """
    publishers: list[BasePublisher] = []
    for publisher_cls in (TelegramPublisher, FeishuPublisher, OpenClawPublisher):
        try:
            publishers.append(publisher_cls())
        except ValueError as exc:
            logger.warning("渠道 %s 未配置，跳过: %s", publisher_cls.channel, exc)
    return publishers


async def publish_daily_digest(
    knowledge_dir: str | Path = DEFAULT_KNOWLEDGE_DIR,
    date: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> list[PublishResult]:
    """生成并并发发布当日知识简报到所有已配置渠道。

    通过 :func:`generate_daily_digest` 生成 markdown / telegram / feishu
    三种格式，再由各渠道发布器并发取出本渠道对应格式推送。

    Args:
        knowledge_dir: 知识条目目录，透传给 ``generate_daily_digest``。
        date: 日期（``YYYY-MM-DD``）；None 时使用今天 UTC。
        top_n: 简报取前 N 条，透传给 ``generate_daily_digest``。

    Returns:
        各渠道的发布结果列表；当日无条目或无渠道配置时返回空列表。
    """
    digest = generate_daily_digest(knowledge_dir, date, top_n)
    if isinstance(digest, str):
        logger.info("当日无知识条目，跳过发布: %s", digest)
        return []

    publishers = _build_publishers()
    if not publishers:
        logger.warning("没有任何已配置的分发渠道，跳过发布")
        return []

    results = await asyncio.gather(
        *(publisher.send_digest(digest) for publisher in publishers)
    )
    for result in results:
        if result.success:
            logger.info(
                "[publish] %s 推送成功, message_id=%s",
                result.channel,
                result.message_id,
            )
        else:
            logger.error("[publish] %s 推送失败: %s", result.channel, result.error)
    return list(results)
