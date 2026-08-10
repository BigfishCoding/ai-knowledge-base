"""知识条目格式化模块（纯函数，无网络请求）。

将单篇知识条目 JSON 渲染为多平台文本/卡片，供 ``publisher`` 推送消费：

- :func:`json_to_markdown`: 通用 Markdown 文本
- :func:`json_to_telegram`: Telegram MarkdownV2 文本（特殊字符转义）
- :func:`json_to_feishu`: 飞书 interactive 卡片字典
- :func:`generate_daily_digest`: 按日期聚合并按 category 分组的 Top N 多平台简报
- :func:`digest_from_index`: 基于 index.json 的轻量级预览（秒级返回）

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

INDEX_MISSING_MESSAGE = "知识库索引不存在：{path}"
INDEX_INVALID_MESSAGE = "知识库索引解析失败：{path}"

INDEX_ID_DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})[-/]?(?P<month>\d{2})[-/]?(?P<day>\d{2})"
)
"""从条目 id 中提取日期的正则（兼容 ``2026-04-11-000`` 与 ``gh-20260720-003``）。"""

TELEGRAM_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"
TELEGRAM_ESCAPE_PATTERN = re.compile(fr"[{re.escape(TELEGRAM_ESCAPE_CHARS)}]")
TELEGRAM_CODE_MARKER = "\\`"

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
"""Telegram 单条消息的字符上限。"""
TELEGRAM_SINGLE_TRUNCATE_THRESHOLD = 3500
"""单篇文章格式化后超过该长度时触发正文截断（预留标题与元信息空间）。"""
TELEGRAM_SUMMARY_TRUNCATE_LENGTH = 500
"""单篇文章正文超限时的截断保留长度（字符）。"""
TELEGRAM_TRUNCATE_SUFFIX = "...（点击查看完整）"
"""正文被截断时追加的提示后缀。"""

TELEGRAM_DIGEST_MAX_LENGTH = 4000
"""Telegram 每日简报的字符上限。"""
TELEGRAM_DIGEST_BODY_LIMIT = 300
"""简报超限时每篇文章正文的截断保留长度（字符）。"""
TELEGRAM_DIGEST_FOOTER_TEMPLATE = "📖 完整简报：{link}"
"""简报末尾的完整版入口模板。"""
TELEGRAM_DIGEST_FOOTER_LINK = "#"
"""完整版简报链接占位符（尚未接入真实链接）。"""

SUMMARY_FALLBACK_LENGTH = 100
"""key_insight 缺失时 summary 的回退截断长度（字符）。"""
ELLIPSIS = "..."
"""摘要被截断时的省略号后缀。"""

CATEGORY_LIMIT = 3
"""简报中每个 category 分组最多展示的文章数，超出部分以 ``+N more`` 提示。"""

DEFAULT_CATEGORY_NAME = "uncategorized"
"""article 缺少 category 字段时使用的兜底分类名。"""
DEFAULT_CATEGORY_EMOJI = "📌"
"""未知分类的兜底展示图标。"""

CATEGORY_EMOJIS: dict[str, str] = {
    "framework": "🤖",
    "agent": "🧠",
    "rag": "📚",
    "tool": "🛠️",
    "mcp": "🔌",
}

MARKDOWN_HEADING_LEVEL = 2
"""单篇 Markdown 文章使用的标题级别（``##``）。"""
DIGEST_ARTICLE_HEADING_LEVEL = 3
"""简报中分组内单篇文章使用的标题级别（``###``）。"""

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


def _source(article: dict[str, Any]) -> str:
    """读取条目来源：优先 ``source``，缺失时回退 ``source_type``。

    Args:
        article: 单篇知识条目字典。

    Returns:
        来源字符串；两者均缺失时返回空串。
    """
    source = article.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    source_type = article.get("source_type")
    if isinstance(source_type, str) and source_type.strip():
        return source_type.strip()
    return ""


def _url(article: dict[str, Any]) -> str:
    """读取条目原文链接：优先 ``url``，缺失时回退 ``source_url``。

    Args:
        article: 单篇知识条目字典。

    Returns:
        链接字符串；两者均缺失时返回空串。
    """
    url = article.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    source_url = article.get("source_url")
    if isinstance(source_url, str) and source_url.strip():
        return source_url.strip()
    return ""


def _summary(article: dict[str, Any]) -> str:
    """读取条目的摘要文本。

    Args:
        article: 单篇知识条目字典。

    Returns:
        ``summary`` 字符串；字段缺失或非字符串时返回空串。
    """
    summary = article.get("summary")
    if isinstance(summary, str):
        return summary
    return ""


def _truncate_fallback(text: str) -> str:
    """将文本截断到回退长度，超长时追加省略号。

    Args:
        text: 原始文本。

    Returns:
        未超长时原样返回；超长时截取前 :data:`SUMMARY_FALLBACK_LENGTH`
        字符并追加 ``...``。
    """
    if len(text) > SUMMARY_FALLBACK_LENGTH:
        return text[:SUMMARY_FALLBACK_LENGTH].rstrip() + ELLIPSIS
    return text


def _insight(article: dict[str, Any]) -> str:
    """读取条目的核心洞察，缺失时依次回退到要点/摘要截断。

    Args:
        article: 单篇知识条目字典。

    Returns:
        依次回退：``key_insight`` → ``key_points``（分号连接）→ ``summary``；
        后两者超长时截断到 :data:`SUMMARY_FALLBACK_LENGTH` 并追加 ``...``。
    """
    insight = article.get("key_insight")
    if isinstance(insight, str) and insight.strip():
        return insight.strip()

    points = article.get("key_points")
    if isinstance(points, list):
        text = "；".join(str(point) for point in points)
        if text.strip():
            return _truncate_fallback(text)

    return _truncate_fallback(_summary(article))


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
        f"**来源**：{_source(article)} · **日期**：{_article_date(article)}"
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
            _insight(article),
            _feishu_tags_md(article),
            f"[原文链接]({_url(article)})",
        ]
    )
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


# ── 单篇格式化 ─────────────────────────────────────────────────────────────


def _markdown_article(article: dict[str, Any], heading_level: int) -> str:
    """按指定标题级别渲染单篇文章的 Markdown 文本。

    含标题、来源、日期、相关性评分（含状态图标）、标签、核心洞察与原文链接。
    正文优先使用 ``key_insight``（一句话洞察），缺失时回退到摘要截断。

    Args:
        article: 单篇知识条目字典。
        heading_level: 标题级别（2 表示 ``##``，3 表示 ``###``）。

    Returns:
        渲染后的 Markdown 文本。
    """
    score = _score(article)
    emoji, _ = _relevance_status(score)
    date = _article_date(article)
    tags = " / ".join(_tags(article))
    heading = "#" * heading_level

    return "\n".join(
        [
            f"{heading} {article['title']}",
            "",
            f"- **来源**：{_source(article)}",
            f"- **日期**：{date}",
            f"- **相关性**：{emoji} {score:.2f}",
            f"- **标签**：{tags}",
            "",
            _insight(article),
            "",
            f"🔗 原文链接：{_url(article)}",
        ]
    )


def json_to_markdown(article: dict[str, Any]) -> str:
    """将单篇知识条目格式化为 Markdown 文本。

    包含标题、来源、日期、相关性评分（含状态图标）、标签、核心洞察与原文链接。
    正文优先使用 ``key_insight``（一句话洞察），缺失时回退到摘要截断。

    Args:
        article: 单篇知识条目 JSON 字典。

    Returns:
        渲染后的 Markdown 文本。
    """
    return _markdown_article(article, MARKDOWN_HEADING_LEVEL)


def _telegram_body(article: dict[str, Any]) -> str:
    """读取 Telegram 正文：优先 key_insight，依次回退 key_points / summary。

    Args:
        article: 单篇知识条目字典。

    Returns:
        ``key_insight`` 文本（去除首尾空白）；缺失/为空时回退到
        ``key_points``（分号连接）；再缺失时返回 ``summary`` 原文
        （非字符串时返回空串）。
    """
    insight = article.get("key_insight")
    if isinstance(insight, str) and insight.strip():
        return insight.strip()
    points = article.get("key_points")
    if isinstance(points, list):
        text = "；".join(str(point) for point in points)
        if text.strip():
            return text
    return _summary(article)


def _truncate_body(text: str, max_length: int) -> str:
    """按需截断正文，超长时追加查看提示。

    Args:
        text: 原始正文。
        max_length: 保留的最大字符数。

    Returns:
        未超长时原样返回；超长时截断到 ``max_length`` 并追加
        :data:`TELEGRAM_TRUNCATE_SUFFIX`。
    """
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + TELEGRAM_TRUNCATE_SUFFIX


def _enforce_max_length(text: str, max_length: int) -> str:
    """硬性截断文本，确保不超过指定长度。

    Args:
        text: 原始文本。
        max_length: 允许的最大字符数。

    Returns:
        超长时截取前 ``max_length`` 字符，否则原样返回。
    """
    if len(text) <= max_length:
        return text
    return text[:max_length]


def _render_telegram_article(
    title: str,
    url: str,
    score: float,
    emoji: str,
    source: str,
    tags: str,
    body: str,
) -> str:
    """渲染单篇文章的 Telegram MarkdownV2 文本（字段均已转义）。

    Args:
        title: 转义后的标题。
        url: 转义后的原文链接。
        score: 相关性评分。
        emoji: 相关性状态图标。
        source: 转义后的来源。
        tags: 转义并拼接后的标签。
        body: 转义后的正文。

    Returns:
        组装完成的 MarkdownV2 文本。
    """
    return "\n".join(
        [
            f"*[{title}]({url})*",
            "",
            f"{emoji} *相关性*：{score:.2f}",
            f"*来源*：{source}",
            "",
            body,
            "",
            f"{TELEGRAM_CODE_MARKER}{tags}{TELEGRAM_CODE_MARKER}",
        ]
    )


def json_to_telegram(
    article: dict[str, Any], summary_limit: int | None = None
) -> str:
    """将单篇知识条目格式化为 Telegram MarkdownV2 文本。

    特殊字符 ``_*[]()~`>#+-=|{}.!`` 会被反斜杠转义，避免被解释为格式标记；
    标签内部的空格替换为下划线。正文优先使用 ``key_insight``（一句话洞察），
    缺失时回退到完整 ``summary``。

    单篇超长保护：格式化后超过 :data:`TELEGRAM_SINGLE_TRUNCATE_THRESHOLD` 时，
    将正文截断到 :data:`TELEGRAM_SUMMARY_TRUNCATE_LENGTH` 并追加
    :data:`TELEGRAM_TRUNCATE_SUFFIX`；最终输出不超过
    :data:`TELEGRAM_MAX_MESSAGE_LENGTH`。

    Args:
        article: 单篇知识条目 JSON 字典。
        summary_limit: 正文最大长度（字符）；None 表示不额外限制。

    Returns:
        渲染后的 MarkdownV2 文本。
    """
    score = _score(article)
    emoji, _ = _relevance_status(score)
    title = _escape_telegram(article["title"])
    url = _escape_telegram(_url(article))
    source = _escape_telegram(_source(article))
    tags = " ".join(_escape_telegram(tag.replace(" ", "_")) for tag in _tags(article))

    body = _telegram_body(article)
    if summary_limit is not None:
        body = _truncate_body(body, summary_limit)

    text = _render_telegram_article(
        title, url, score, emoji, source, tags, _escape_telegram(body)
    )
    if len(text) > TELEGRAM_SINGLE_TRUNCATE_THRESHOLD:
        body = _truncate_body(
            _telegram_body(article), TELEGRAM_SUMMARY_TRUNCATE_LENGTH
        )
        text = _render_telegram_article(
            title, url, score, emoji, source, tags, _escape_telegram(body)
        )
    return _enforce_max_length(text, TELEGRAM_MAX_MESSAGE_LENGTH)


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
                    "text": {"tag": "lark_md", "content": _summary(article)},
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": _feishu_tags_md(article)},
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"[原文链接]({_url(article)})",
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


def _category_emoji(category: str) -> str:
    """返回分类对应的展示 emoji。

    Args:
        category: 分类名（如 ``framework``）。

    Returns:
        已知分类的 emoji；未知分类回退 :data:`DEFAULT_CATEGORY_EMOJI`。
    """
    return CATEGORY_EMOJIS.get(category, DEFAULT_CATEGORY_EMOJI)


def _category_label(category: str, count: int) -> str:
    """构建分类分组的展示标签（含 emoji 与篇数）。

    Args:
        category: 分类名。
        count: 该分类下文章总数。

    Returns:
        形如 ``🤖 framework（3篇）`` 的标签文本。
    """
    return f"{_category_emoji(category)} {category}（{count}篇）"


def _more_line(count: int) -> str:
    """构建分类超限时的 ``+N more`` 提示行。

    Args:
        count: 未展示的文章数。

    Returns:
        形如 ``+3 more`` 的文本。
    """
    return f"+{count} more"


def _group_by_category(
    articles: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """按 category 分组并排序。

    - 组内按 ``relevance_score`` 降序
    - 组间按文章数降序（文章数相同时按分类名升序）

    Args:
        articles: 知识条目列表。

    Returns:
        ``(category, articles)`` 元组列表，各组已排好序。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for article in articles:
        category = str(article.get("category", DEFAULT_CATEGORY_NAME))
        groups.setdefault(category, []).append(article)

    for items in groups.values():
        items.sort(key=_score, reverse=True)

    return sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))


def _render_category_markdown(
    category: str, articles: list[dict[str, Any]]
) -> str:
    """渲染单个 category 分组的 Markdown 章节。

    Args:
        category: 分类名。
        articles: 该分类下的文章列表（已按相关性降序）。

    Returns:
        含二级标题、三级标题文章与 ``+N more`` 的 Markdown 文本。
    """
    lines = [f"## {_category_label(category, len(articles))}"]
    lines.extend(
        _markdown_article(article, DIGEST_ARTICLE_HEADING_LEVEL)
        for article in articles[:CATEGORY_LIMIT]
    )
    if len(articles) > CATEGORY_LIMIT:
        lines.append(_more_line(len(articles) - CATEGORY_LIMIT))
    return "\n\n".join(lines)


def _render_category_telegram(
    category: str,
    articles: list[dict[str, Any]],
    display_limit: int = CATEGORY_LIMIT,
    summary_limit: int | None = None,
) -> str:
    """渲染单个 category 分组的 Telegram MarkdownV2 章节。

    Args:
        category: 分类名。
        articles: 该分类下的文章列表（已按相关性降序）。
        display_limit: 该分类最多展示的文章数，默认 :data:`CATEGORY_LIMIT`。
        summary_limit: 每篇文章正文最大长度（字符）；None 表示不额外限制。

    Returns:
        含加粗分类标签、文章与 ``+N more`` 的 MarkdownV2 文本。
    """
    label = _escape_telegram(_category_label(category, len(articles)))
    lines = [f"**{label}**"]
    lines.extend(
        json_to_telegram(article, summary_limit)
        for article in articles[:display_limit]
    )
    if len(articles) > display_limit:
        lines.append(_more_line(len(articles) - display_limit))
    return "\n\n".join(lines)


def _build_telegram_digest(
    groups: list[tuple[str, list[dict[str, Any]]]],
    display_limit: int,
    summary_limit: int | None,
) -> str:
    """按给定压缩参数渲染 Telegram 简报全文（含完整版入口）。

    Args:
        groups: ``(category, articles)`` 分组列表。
        display_limit: 每个分类最多展示的文章数。
        summary_limit: 每篇文章正文最大长度；None 表示不额外限制。

    Returns:
        含分组内容与 ``📖 完整简报`` 尾注的 MarkdownV2 文本。
    """
    parts = [
        _render_category_telegram(category, items, display_limit, summary_limit)
        for category, items in groups
    ]
    footer = _escape_telegram(
        TELEGRAM_DIGEST_FOOTER_TEMPLATE.format(link=TELEGRAM_DIGEST_FOOTER_LINK)
    )
    return "\n\n".join(parts) + "\n\n" + footer


def _shrink_telegram_digest(
    groups: list[tuple[str, list[dict[str, Any]]]],
) -> str:
    """压缩 Telegram 简报至 :data:`TELEGRAM_DIGEST_MAX_LENGTH` 内。

    依次尝试：先截断每篇文章正文，再逐档减少每个分类的展示篇数；
    仍超限时做硬截断。

    Args:
        groups: ``(category, articles)`` 分组列表。

    Returns:
        长度不超过 :data:`TELEGRAM_DIGEST_MAX_LENGTH` 的 MarkdownV2 文本。
    """
    text = ""
    for summary_limit in (None, TELEGRAM_DIGEST_BODY_LIMIT):
        for display_limit in range(CATEGORY_LIMIT, 0, -1):
            text = _build_telegram_digest(groups, display_limit, summary_limit)
            if len(text) <= TELEGRAM_DIGEST_MAX_LENGTH:
                return text
    return text[:TELEGRAM_DIGEST_MAX_LENGTH]


def _render_category_feishu(
    category: str, articles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """渲染单个 category 分组的飞书卡片元素。

    Args:
        category: 分类名。
        articles: 该分类下的文章列表（已按相关性降序）。

    Returns:
        含分类标签、文章块与 ``+N more`` 的元素列表。
    """
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{_category_label(category, len(articles))}**",
            },
        }
    ]
    elements.extend(
        _feishu_article_block(article) for article in articles[:CATEGORY_LIMIT]
    )
    if len(articles) > CATEGORY_LIMIT:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": _more_line(len(articles) - CATEGORY_LIMIT),
                },
            }
        )
    return elements


def generate_daily_digest(
    knowledge_dir: str | Path = DEFAULT_KNOWLEDGE_DIR,
    date: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    score_threshold: float = 0.0,
) -> dict[str, Any] | str:
    """生成指定日期的多平台知识简报（按 category 分组）。

    按 ``{date}-*.json`` 扫描知识条目目录，低于 ``score_threshold`` 的
    低质量文章先被过滤，再按相关性评分降序取前 N 条，随后按 ``category``
    分组展示：组内按 ``relevance_score`` 降序，组间按文章数降序；单个分组
    最多展示 :data:`CATEGORY_LIMIT` 篇，超出以 ``+N more`` 提示。
    Telegram 简报超出 :data:`TELEGRAM_DIGEST_MAX_LENGTH` 时，先截断各篇正文，
    再逐档减少每类展示篇数，并在末尾追加 ``📖 完整简报`` 入口。
    正文优先使用 ``key_insight``，缺失时回退到完整 ``summary``。
    当日无文章或全部低于阈值时返回空提示。

    Args:
        knowledge_dir: 知识条目目录，默认 ``knowledge/articles``。
        date: 日期（``YYYY-MM-DD``）；None 时使用今天的 UTC 日期。
        top_n: 先按相关性评分降序截取前 N 条，默认 5。
        score_threshold: 相关性评分下限（0-1）；低于该值的文章直接过滤，
            默认 0.0 表示不过滤。

    Returns:
        当日无文章时返回 ``"📭 {date} 暂无新增知识条目"``；
        否则返回 ``{"markdown": str, "telegram": str, "feishu": dict}`` 字典。
    """
    target = Path(knowledge_dir)
    if date is None:
        date = datetime.now(timezone.utc).strftime(DATE_FORMAT)

    articles = _load_articles(target, date)
    articles = [article for article in articles if _score(article) >= score_threshold]
    if not articles:
        return EMPTY_DIGEST_MESSAGE.format(date=date)

    articles.sort(key=_score, reverse=True)
    top = articles[:top_n]
    groups = _group_by_category(top)

    return {
        "markdown": "\n\n".join(
            _render_category_markdown(category, items)
            for category, items in groups
        ),
        "telegram": _shrink_telegram_digest(groups),
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
                "elements": [
                    element
                    for category, items in groups
                    for element in _render_category_feishu(category, items)
                ],
            },
        },
    }


# ── 基于索引的轻量预览 ─────────────────────────────────────────────────────


def _id_date(article_id: str) -> str:
    """从条目 id 中提取日期（标准化为 ``YYYY-MM-DD``）。

    兼容 ``2026-04-11-000``（日期带横杠）与 ``gh-20260720-003``
    （日期为连续 8 位）两种 id 格式。

    Args:
        article_id: 条目 id 字符串。

    Returns:
        标准化日期（``YYYY-MM-DD``）；无法提取时返回空串。
    """
    match = INDEX_ID_DATE_PATTERN.search(article_id)
    if not match:
        return ""
    return (
        f"{match.group('year')}-{match.group('month')}-{match.group('day')}"
    )


def _preview_markdown(previews: list[dict[str, Any]]) -> str:
    """渲染轻量预览的 Markdown 表格。

    Args:
        previews: 已按相关性降序的预览条目列表。

    Returns:
        ``| 标题 | 分类 | 相关性 |`` 表格文本。
    """
    lines = ["| 标题 | 分类 | 相关性 |", "|------|------|--------|"]
    lines.extend(
        f"| {item['title']} | {item['category']} | {item['relevance_score']:.2f} |"
        for item in previews
    )
    return "\n".join(lines)


def _preview_telegram(date: str, previews: list[dict[str, Any]]) -> str:
    """渲染轻量预览的 Telegram 纯文本列表。

    Args:
        date: 日期（``YYYY-MM-DD``）。
        previews: 已按相关性降序的预览条目列表。

    Returns:
        ``📋 {date} Top {n}`` 开头、带相关性图标的编号列表文本。
    """
    lines = [f"📋 {date} Top {len(previews)}"]
    for idx, item in enumerate(previews, start=1):
        emoji, _ = _relevance_status(item["relevance_score"])
        lines.append(
            f"{idx}. {item['title']} [{item['category']}] "
            f"{emoji}{item['relevance_score']:.2f}"
        )
    return "\n".join(lines)


def digest_from_index(
    knowledge_dir: str | Path = DEFAULT_KNOWLEDGE_DIR,
    date: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, str] | str:
    """基于 index.json 的轻量级知识预览（不读取单篇文章）。

    只读取 ``knowledge/articles/index.json`` 索引，从条目 ``id`` 中提取日期
    （兼容 ``gh-20260720-003`` 与 ``2026-04-11-000`` 两种格式）并按 ``date``
    筛选，以 ``relevance_score`` 降序取前 N 条，渲染为 Markdown 表格与 Telegram
    纯文本列表。适合 Bot 快速响应"今天有什么新内容"，秒级返回。

    Args:
        knowledge_dir: 知识条目目录，默认 ``knowledge/articles``。
        date: 日期（``YYYY-MM-DD``）；None 时使用今天的 UTC 日期。
        top_n: 按相关性评分降序取前 N 条，默认 5。

    Returns:
        索引缺失/解析失败或筛选后无条目时返回 ``"📭 {date} 暂无新增知识条目"``；
        否则返回 ``{"markdown": str, "telegram": str}`` 字典。
    """
    target = Path(knowledge_dir)
    if date is None:
        date = datetime.now(timezone.utc).strftime(DATE_FORMAT)

    index_path = target / INDEX_FILENAME
    if not index_path.exists():
        return INDEX_MISSING_MESSAGE.format(path=index_path)

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return INDEX_INVALID_MESSAGE.format(path=index_path)

    previews: list[dict[str, Any]] = []
    for article in index.get("articles", []):
        if not isinstance(article, dict):
            continue
        article_id = str(article.get("id", ""))
        if _id_date(article_id) != date:
            continue
        previews.append(
            {
                "id": article_id,
                "title": str(article.get("title", "")),
                "category": str(
                    article.get("category") or DEFAULT_CATEGORY_NAME
                ),
                "relevance_score": _score(article),
            }
        )

    if not previews:
        return EMPTY_DIGEST_MESSAGE.format(date=date)

    previews.sort(key=lambda item: item["relevance_score"], reverse=True)
    top = previews[:top_n]

    return {
        "markdown": _preview_markdown(top),
        "telegram": _preview_telegram(date, top),
    }
