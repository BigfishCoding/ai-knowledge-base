"""常驻 Telegram 轮询入口（Docker bot 服务的进程主体）。

通过 Telegram Bot API 长轮询（``getUpdates``）接收用户消息，交给
:class:`KnowledgeBot` 规则引擎处理并回复，供 compose 的 bot 服务以
常驻进程方式运行。

设计要点：

- 环境变量 ``TELEGRAM_BOT_TOKEN`` 必填，缺失时启动即报错退出
- 订阅数据持久化到 ``data/subscriptions.json``，随 compose bind mount 存活
- 网络/API 异常按固定间隔退避重试，进程不退出
- 模块可被 import（供健康检查），命令行入口为 ``python -m bot.telegram_bot``
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import aiohttp

# 项目根目录注入 sys.path，保证 bot / distribution 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.knowledge_bot import (
    KnowledgeBot,
    KnowledgeSearchEngine,
    Permission,
    PermissionManager,
    SubscriptionManager,
)
from distribution.publisher import (
    ENV_TELEGRAM_BOT_TOKEN,
    ERROR_ENV_MISSING,
    ERROR_TELEGRAM_OK_FALSE,
    TELEGRAM_API_BASE,
    TELEGRAM_SEND_MESSAGE_PATH,
    TG_PARAM_CHAT_ID,
    TG_PARAM_TEXT,
    TG_RESPONSE_DESCRIPTION,
    TG_RESPONSE_OK,
    TG_RESPONSE_RESULT,
)

logger = logging.getLogger(__name__)

# ── Telegram 轮询参数 ─────────────────────────────────────────────────────

GET_UPDATES_PATH = "/bot{token}/getUpdates"
TG_PARAM_OFFSET = "offset"
TG_PARAM_TIMEOUT = "timeout"
TG_PARAM_LIMIT = "limit"
TG_FIELD_UPDATE_ID = "update_id"
TG_FIELD_MESSAGE = "message"
TG_FIELD_CHAT = "chat"
TG_FIELD_CHAT_ID = "id"
TG_FIELD_TEXT = "text"

# ── 运行参数 ───────────────────────────────────────────────────────────────

POLL_TIMEOUT_SECONDS = 30
DEFAULT_UPDATE_LIMIT = 100
NETWORK_RETRY_DELAY_SECONDS = 5.0
MAX_REPLY_LENGTH = 4096
REPLY_TRUNCATION_SUFFIX = "\n…（内容过长已截断）"

# ── 数据路径 ───────────────────────────────────────────────────────────────

DATA_DIRNAME = "data"
SUBSCRIPTIONS_FILENAME = "subscriptions.json"
KNOWLEDGE_DIRNAME = "knowledge"
ARTICLES_DIRNAME = "articles"


def _subscriptions_path() -> Path:
    """计算订阅持久化文件路径（``<项目根>/data/subscriptions.json``）。

    Returns:
        订阅文件的绝对路径。
    """
    return PROJECT_ROOT / DATA_DIRNAME / SUBSCRIPTIONS_FILENAME


def _build_bot() -> KnowledgeBot:
    """构建带持久化订阅的知识库机器人实例。

    Telegram 入口没有管理员授权命令，因此对聊天用户默认授予 READ + WRITE，
    使搜索与订阅功能开箱即用；如需收紧权限，可改回仅 ``{Permission.READ}``。

    Returns:
        配置完成的 :class:`KnowledgeBot` 实例。
    """
    search_engine = KnowledgeSearchEngine(
        knowledge_dir=PROJECT_ROOT / KNOWLEDGE_DIRNAME / ARTICLES_DIRNAME
    )
    subscriptions = SubscriptionManager(storage_path=_subscriptions_path())
    permissions = PermissionManager(
        default_permissions={Permission.READ, Permission.WRITE}
    )
    return KnowledgeBot(
        search_engine=search_engine,
        subscriptions=subscriptions,
        permissions=permissions,
    )


def _truncate(text: str, limit: int = MAX_REPLY_LENGTH) -> str:
    """将回复文本截断到 Telegram 单条消息长度上限。

    Args:
        text: 原始回复文本。
        limit: 允许的最大字符数，默认 4096。

    Returns:
        未超限返回原文；超限时截断并附加截断提示。
    """
    if len(text) <= limit:
        return text
    return text[: limit - len(REPLY_TRUNCATION_SUFFIX)] + REPLY_TRUNCATION_SUFFIX


async def _send_reply(
    session: aiohttp.ClientSession, token: str, chat_id: int, text: str
) -> None:
    """向指定聊天发送回复文本。

    Args:
        session: 复用的 aiohttp 会话。
        token: Telegram Bot Token。
        chat_id: 目标聊天 ID。
        text: 回复文本（自动截断）。

    Raises:
        aiohttp.ClientError: 网络错误或 HTTP 非 2xx 时抛出。
    """
    url = TELEGRAM_API_BASE + TELEGRAM_SEND_MESSAGE_PATH.format(token=token)
    payload = {TG_PARAM_CHAT_ID: chat_id, TG_PARAM_TEXT: _truncate(text)}
    async with session.post(url, json=payload) as response:
        response.raise_for_status()
        body = await response.json()
    if body.get(TG_RESPONSE_OK) is not True:
        logger.warning(
            ERROR_TELEGRAM_OK_FALSE.format(body.get(TG_RESPONSE_DESCRIPTION, ""))
        )


async def _handle_update(
    session: aiohttp.ClientSession,
    token: str,
    bot: KnowledgeBot,
    update: dict[str, Any],
) -> None:
    """处理单条 Telegram 更新（文本消息 → 检索 → 回复）。

    非文本消息直接忽略；处理或发送失败仅记录日志，不中断轮询循环。

    Args:
        session: 复用的 aiohttp 会话。
        token: Telegram Bot Token。
        bot: 知识库机器人实例。
        update: ``getUpdates`` 返回的单条更新对象。
    """
    message = update.get(TG_FIELD_MESSAGE)
    if not isinstance(message, dict):
        return
    text = message.get(TG_FIELD_TEXT)
    chat = message.get(TG_FIELD_CHAT)
    if not isinstance(text, str) or not isinstance(chat, dict):
        return
    chat_id = chat.get(TG_FIELD_CHAT_ID)
    if not isinstance(chat_id, int):
        return
    try:
        reply = bot.handle_message(str(chat_id), text)
        await _send_reply(session, token, chat_id, reply)
    except (aiohttp.ClientError, OSError) as exc:
        logger.warning("处理消息失败: %s", exc)


async def _poll_once(
    session: aiohttp.ClientSession, token: str, bot: KnowledgeBot, offset: int
) -> int:
    """执行一次长轮询并处理全部新消息。

    Args:
        session: 复用的 aiohttp 会话。
        token: Telegram Bot Token。
        bot: 知识库机器人实例。
        offset: 待确认的下一个 update_id；0 表示从最新更新开始。

    Returns:
        下一次轮询应使用的 offset（已处理的最新 update_id + 1）。

    Raises:
        aiohttp.ClientError: 网络错误、HTTP 非 2xx 或 API 返回 ok=false。
    """
    url = TELEGRAM_API_BASE + GET_UPDATES_PATH.format(token=token)
    params = {
        TG_PARAM_OFFSET: offset,
        TG_PARAM_TIMEOUT: POLL_TIMEOUT_SECONDS,
        TG_PARAM_LIMIT: DEFAULT_UPDATE_LIMIT,
    }
    async with session.get(url, params=params) as response:
        response.raise_for_status()
        body = await response.json()
    if body.get(TG_RESPONSE_OK) is not True:
        raise aiohttp.ClientError(
            ERROR_TELEGRAM_OK_FALSE.format(body.get(TG_RESPONSE_DESCRIPTION, ""))
        )
    updates = body.get(TG_RESPONSE_RESULT)
    if not isinstance(updates, list):
        return offset
    for update in updates:
        if not isinstance(update, dict):
            continue
        # 无论单条处理成败都推进 offset，避免失败消息导致无限重拉
        offset = max(offset, int(update.get(TG_FIELD_UPDATE_ID, 0)) + 1)
        await _handle_update(session, token, bot, update)
    return offset


async def _run_polling_loop(token: str, bot: KnowledgeBot) -> None:
    """持续轮询 Telegram 更新直到进程被终止。

    网络/API 异常时按固定间隔退避重试，保证常驻进程不因瞬时抖动退出。

    Args:
        token: Telegram Bot Token。
        bot: 知识库机器人实例。
    """
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                offset = await _poll_once(session, token, bot, offset)
            except (aiohttp.ClientError, OSError) as exc:
                logger.warning(
                    "轮询失败，%.1f 秒后重试: %s", NETWORK_RETRY_DELAY_SECONDS, exc
                )
                await asyncio.sleep(NETWORK_RETRY_DELAY_SECONDS)


async def main() -> int:
    """常驻入口：校验 token、构建机器人并进入轮询循环。

    Returns:
        缺少 ``TELEGRAM_BOT_TOKEN`` 时返回 1；正常常驻运行不返回。
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    token = os.environ.get(ENV_TELEGRAM_BOT_TOKEN, "").strip()
    if not token:
        logger.error(ERROR_ENV_MISSING.format(ENV_TELEGRAM_BOT_TOKEN))
        return 1
    bot = _build_bot()
    logger.info("知识库 Telegram bot 启动，开始长轮询")
    await _run_polling_loop(token, bot)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
