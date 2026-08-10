"""知识条目格式化模块（纯函数，无网络请求）。

将单篇知识条目 JSON 渲染为多平台文本/卡片，供 ``publisher`` 推送消费：

- :func:`json_to_markdown`: 通用 Markdown 文本
- :func:`json_to_telegram`: Telegram MarkdownV2 文本（特殊字符转义）
- :func:`json_to_feishu`: 飞书 interactive 卡片字典
- :func:`generate_daily_digest`: 按日期聚合 Top N 条目的多平台简报

本模块只做格式化，不发起任何网络请求；网络与渠道调用归 ``publisher`` 负责。
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 常量 ──────────────────────────────────────────────────────────────────

HIGH_SCORE_THRESHOLD = 0.8
"""高分阈值：相关性评分达到该值标记为高。"""
MEDIUM_SCORE_THRESHOLD = 0.6
"""中分阈值：相关性评分达到该值标记为中。"""

EMOJI_HIGH = "🟢"
EMOJI_MEDIUM = "🟟"
EMOJI_LOW = "🔴"

TEMPLATE_GREEN = "green"
TEMPLATE_YELLOW = "yellow"
TEMPLATE_RED = "red"
TEMPLATE_DIGEST = "blue"

MSG_TYPE_INTERACTIVE = "interactive"

DATE_FORMAT = "%Y-%m-%d"
DATE_LENGTH = 10
DEFAULT_KNOWLEDGE_DIR = "knowledge/articles"
DEFAULT_TOP_N = 5
INDEX_FILENAME = "index.json"

TELEGRAM_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"
TELEGRAM_ESCAPE_PATTERN = re.compile(fr"[{re.escape(TELEGRAM_ESCAPE_CHARS)}]")
TELEGRAM_CODE_MARKER = "\\`"

EMPTY_DIGEST_MESSAGE = "📭 {date} 暂无新增知识条目"


# ── 私有工具函数 ──────────────────────────────────────────────────────────


def _score(article: dict[str, Any]) -> float:
    """读取条目的相关性评分。

    Args:
        article: 单篇知识条目字典。

    Returns:
        相关性评分（0-1）；字段缺失或值非法时回退 0.0。
    """
    value = article.get("relevance_score")
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _article_date(article: dict[str, Any]) -> str:
    """提取条目的采集日期。

    Args:
        article: 单篇知识条目字典。

    Returns:
        ``collected_at`` 前 10 位日期（``YYYY-MM-DD``）；缺失时返回空串。
    """
    return str(article.get("collected_at", ""))[:DATE_LENGTH]


def _tags(article: dict[str, Any]) -> list[str]:
    """读取条目的标签列表。

    Args:
        article: 单篇知识条目字典。

    Returns:
        标签字符串列表；字段缺失或非列表时返回空列表。
    """
    tags = article.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags]


def _relevance_status(score: float) -> tuple[str, str]:
    """将相关性评分映射为展示状态。

    Args:
        score: 相关性评分（0-1）。

    Returns:
        ``(emoji, feishu_template)`` 元组：高(≥0.8) 🟢/green、
        中(≥0.6) 🟟/yellow、低(否则) 🔴/red。
    """
    if score >= HIGH_SCORE_THRESHOLD:
        return EMOJI_HIGH, TEMPLATE_GREEN
    if score >= MEDIUM_SCORE_THRESHOLD:
        return EMOJI_MEDIUM, TEMPLATE_YELLOW
    return EMOJI_LOW, TEMPLATE_RED


def _escape_telegram(text: str) -> str:
    """转义 Telegram MarkdownV2 特殊字符。

    Args:
        text: 原始文本。

    Returns:
        所有特殊字符前加反斜杠的转义文本。
    """
    return TELEGRAM_ESCAPE_PATTERN.sub(r"\\\g<0>", text)


def _feishu_meta_md(article: dict[str, Any]) -> str:
    """构建条目元信息的飞书 lark_md 文本。

    Args:
        article: 单篇知识条目字典。

    Returns:
        含相关性、来源、日期的单行 markdown 文本。
    """
    score = _score(article)
    emoji, _ = _relevance_status(score)
    return (
        f"{emoji} **相关性**：{score:.2f} · "
        f"**来源**：{article['source']} · **日期**：{_article_date(article)}"
    )


def _feishu_tags_md(article: dict[str, Any]) -> str:
    """构建条目标签的飞书 lark_md 文本。

    Args:
        article: 单篇知识条目字典。

    Returns:
        每个标签以反引号包裹、空格分隔的 markdown 文本。
    """
    return " ".join(f"`{tag}`" for tag in _tags(article))


def _feishu_article_block(article: dict[str, Any]) -> dict[str, Any]:
    """构建简报中单篇文章的飞书元素块（含标题）。

    Args:
        article: 单篇知识条目字典。

    Returns:
        一个 lark_md 文本 div 元素。
    """
    content = "\n".join(
        [
            f"**{article['title']}**",
            _feishu_meta_md(article),
            article["summary"],
            _feishu_tags_md(article),
            f"[原文链接]({article['url']})",
        ]
    )
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


# ── 单篇格式化 ─────────────────────────────────────────────────────────────


def json_to_markdown(article: dict[str, Any]) -> str:
    """将单篇知识条目格式化为 Markdown 文本。

    包含标题、来源、日期、相关性评分（含状态图标）、标签、摘要与原文链接。

    Args:
        article: 单篇知识条目 JSON 字典。

    Returns:
        渲染后的 Markdown 文本。
    """
    score = _score(article)
    emoji, _ = _relevance_status(score)
    date = _article_date(article)
    tags = " / ".join(_tags(article))

    return "\n".join(
        [
            f"## {article['title']}",
            "",
            f"- **来源**：{article['source']}",
            f"- **日期**：{date}",
            f"- **相关性**：{emoji} {score:.2f}",
            f"- **标签**：{tags}",
            "",
            article["summary"],
            "",
            f"🔗 原文链接：{article['url']}",
        ]
    )


def json_to_telegram(article: dict[str, Any]) -> str:
    """将单篇知识条目格式化为 Telegram MarkdownV2 文本。

    特殊字符 ``_*[]()~`>#+-=|{}.!`` 会被反斜杠转义，避免被 Telegram 解释为
    格式标记；标签内部的空格替换为下划线。

    Args:
        article: 单篇知识条目 JSON 字典。

    Returns:
        渲染后的 MarkdownV2 文本。
    """
    score = _score(article)
    emoji, _ = _relevance_status(score)
    title = _escape_telegram(article["title"])
    url = _escape_telegram(article["url"])
    summary = _escape_telegram(article["summary"])
    source = _escape_telegram(article["source"])
    tags = " ".join(_escape_telegram(tag.replace(" ", "_")) for tag in _tags(article))

    return "\n".join(
        [
            f"*[{title}]({url})*",
            "",
            f"{emoji} *相关性*：{score:.2f}",
            f"*来源*：{source}",
            "",
            summary,
            "",
            f"{TELEGRAM_CODE_MARKER}{tags}{TELEGRAM_CODE_MARKER}",
        ]
    )


def json_to_feishu(article: dict[str, Any]) -> dict[str, Any]:
    """将单篇知识条目格式化为飞书 interactive 卡片字典。

    卡片 ``header.template`` 按相关性评分染色：≥0.8 ``green``、≥0.6 ``yellow``、
    否则 ``red``。

    Args:
        article: 单篇知识条目 JSON 字典。

    Returns:
        飞书 interactive 消息卡片字典。
    """
    score = _score(article)
    emoji, template = _relevance_status(score)

    return {
        "msg_type": MSG_TYPE_INTERACTIVE,
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": article["title"]},
                "template": template,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": _feishu_meta_md(article)},
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": article["summary"]},
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": _feishu_tags_md(article)},
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"[原文链接]({article['url']})",
                    },
                },
            ],
        },
    }


# ── 每日简报 ───────────────────────────────────────────────────────────────


def _load_articles(knowledge_dir: Path, date: str) -> list[dict[str, Any]]:
    """加载指定日期的全部知识条目。

    Args:
        knowledge_dir: 知识条目目录。
        date: 日期前缀（``YYYY-MM-DD``）。

    Returns:
        解析成功的知识条目列表；文件缺失或 JSON 解析失败时跳过。
    """
    articles: list[dict[str, Any]] = []
    for path in sorted(knowledge_dir.glob(f"{date}-*.json")):
        if path.name == INDEX_FILENAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            articles.append(data)
    return articles


def generate_daily_digest(
    knowledge_dir: str | Path = DEFAULT_KNOWLEDGE_DIR,
    date: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any] | str:
    """生成指定日期的多平台知识简报（Top N 高相关性条目）。

    按 ``{date}-*.json`` 扫描知识条目目录，按相关性评分降序取前 N 条，
    分别渲染为 Markdown / Telegram 文本与飞书卡片。当日无文章时返回空提示。

    Args:
        knowledge_dir: 知识条目目录，默认 ``knowledge/articles``。
        date: 日期（``YYYY-MM-DD``）；None 时使用今天的 UTC 日期。
        top_n: 按相关性评分降序取前 N 条，默认 5。

    Returns:
        当日无文章时返回 ``"📭 {date} 暂无新增知识条目"``；
        否则返回 ``{"markdown": str, "telegram": str, "feishu": dict}`` 字典。
    """
    target = Path(knowledge_dir)
    if date is None:
        date = datetime.now(timezone.utc).strftime(DATE_FORMAT)

    articles = _load_articles(target, date)
    if not articles:
        return EMPTY_DIGEST_MESSAGE.format(date=date)

    articles.sort(key=_score, reverse=True)
    top = articles[:top_n]

    return {
        "markdown": "\n\n---\n\n".join(json_to_markdown(a) for a in top),
        "telegram": "\n\n".join(json_to_telegram(a) for a in top),
        "feishu": {
            "msg_type": MSG_TYPE_INTERACTIVE,
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{date} AI 知识简报",
                    },
                    "template": TEMPLATE_DIGEST,
                },
                "elements": [_feishu_article_block(a) for a in top],
            },
        },
    }
