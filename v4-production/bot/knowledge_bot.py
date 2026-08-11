"""知识库交互模块（规则驱动，无 LLM 依赖）。

面向聊天机器人提供知识库查询与订阅能力：

- :class:`KnowledgeSearchEngine`: 关键词 / 标签 / 日期范围过滤的搜索引擎
- :class:`SubscriptionManager`: 用户订阅管理（增删查，可选 JSON 落盘）
- :class:`PermissionManager`: 三级权限控制（READ / WRITE / DELETE）
- :class:`KnowledgeBot`: 整合以上模块的统一消息入口
- :func:`recognize_intent`: 规则式意图识别（命令前缀优先，自然语言兜底）

权限约定：搜索类操作仅需 READ（默认授予），订阅需要 WRITE（显式授予）。
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# 项目根目录注入 sys.path，保证 distribution 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from distribution import formatter  # noqa: E402

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

DEFAULT_SEARCH_LIMIT = 10
DEFAULT_TOP_LIMIT = 5
DEFAULT_TODAY_HINT = "今天没有新的知识条目"

# 订阅主题的合法字符：字母数字、下划线、连字符、中文
SUBSCRIPTION_TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}$")

# 搜索参数中形如 标签:xx / 日期:xx~xx / 数量:n 的键值片段
SEARCH_PARAM_PATTERN = re.compile(
    r"(?:标签|tag):(?P<tags>[^\s]+)\s*"
    r"|(?:日期|date):(?P<date>\S+)\s*"
    r"|(?:数量|limit):(?P<limit>\d+)\s*"
)


# ── 枚举 ──────────────────────────────────────────────────────────────────


class Permission(Enum):
    """三级权限等级。

    Attributes:
        READ: 只读，搜索类操作所需。
        WRITE: 写入，订阅/退订所需。
        DELETE: 删除，预留给删除类操作。
    """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class Intent(Enum):
    """消息意图类型。

    Attributes:
        SEARCH: 关键词/标签/日期搜索。
        TODAY: 今日知识条目。
        TOP: 相关性 Top N。
        SUBSCRIBE: 订阅管理（含退订）。
        HELP: 使用帮助。
        UNKNOWN: 无法识别的意图。
    """

    SEARCH = "search"
    TODAY = "today"
    TOP = "top"
    SUBSCRIBE = "subscribe"
    HELP = "help"
    UNKNOWN = "unknown"


# ── 意图识别 ──────────────────────────────────────────────────────────────

# 命令前缀 → 意图（按前缀长度降序匹配，避免 /search 吞掉 /subscribe 等）
COMMAND_PREFIXES: dict[str, Intent] = {
    "/search": Intent.SEARCH,
    "/today": Intent.TODAY,
    "/top": Intent.TOP,
    "/subscribe": Intent.SUBSCRIBE,
    "/help": Intent.HELP,
}

# 自然语言关键词 → 意图（先匹配更明确的动作词，如 搜索/订阅）
NL_KEYWORDS: list[tuple[re.Pattern[str], Intent]] = [
    (re.compile(r"搜索|查询|查找|找一下|找找|\bsearch\b"), Intent.SEARCH),
    (re.compile(r"订阅|退订|\bsubscribe\b|\bunsubscribe\b"), Intent.SUBSCRIBE),
    (re.compile(r"今天|今日|\btoday\b"), Intent.TODAY),
    (re.compile(r"简报|热门|头条|排行榜|\btop\b|\btrending\b"), Intent.TOP),
    (re.compile(r"帮助|怎么用|\bhelp\b"), Intent.HELP),
]


def recognize_intent(text: str) -> tuple[Intent, str]:
    """基于规则识别消息意图。

    优先匹配命令前缀（如 ``/search``），再匹配自然语言关键词；两条都
    未命中时返回 :data:`Intent.UNKNOWN`。

    Args:
        text: 用户消息原文。

    Returns:
        ``(intent, params)`` 元组：intent 为识别出的意图，
        params 为命令前缀后的剩余参数（自然语言命中时返回原文）。
    """
    text = (text or "").strip()
    lower = text.lower()

    for prefix, intent in sorted(
        COMMAND_PREFIXES.items(), key=lambda item: -len(item[0])
    ):
        if lower == prefix or lower.startswith(prefix + " "):
            return intent, text[len(prefix):].strip()

    for pattern, intent in NL_KEYWORDS:
        if pattern.search(lower):
            return intent, text

    return Intent.UNKNOWN, text


# ── 搜索引擎 ──────────────────────────────────────────────────────────────


class KnowledgeSearchEngine:
    """知识库搜索引擎。

    基于 ``knowledge/articles`` 目录下的 JSON 条目，支持关键词（标题/摘要/
    要点/洞察/标签）、标签、日期范围过滤，结果按相关性评分降序返回。

    Args:
        knowledge_dir: 知识条目目录，默认 ``knowledge/articles``。
    """

    def __init__(
        self, knowledge_dir: str | Path = formatter.DEFAULT_KNOWLEDGE_DIR
    ) -> None:
        self._knowledge_dir = Path(knowledge_dir)

    def _load_articles(self) -> list[dict[str, Any]]:
        """加载全部知识条目（跳过 index.json）。

        Returns:
            解析成功的知识条目列表；文件缺失或 JSON 解析失败时跳过。
        """
        articles: list[dict[str, Any]] = []
        for path in sorted(self._knowledge_dir.glob("*.json")):
            if path.name == formatter.INDEX_FILENAME:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("跳过无法解析的知识条目文件: %s", path)
                continue
            if isinstance(data, dict):
                articles.append(data)
        return articles

    @staticmethod
    def _article_text(article: dict[str, Any]) -> str:
        """拼接可搜索文本（标题/摘要/要点/洞察/来源/标签）。

        Args:
            article: 单篇知识条目字典。

        Returns:
            小写拼接后的全文，供关键词子串匹配。
        """
        parts: list[str] = [str(article.get("title", ""))]
        summary = article.get("summary")
        if isinstance(summary, str):
            parts.append(summary)
        points = article.get("key_points")
        if isinstance(points, list):
            parts.extend(str(point) for point in points)
        insight = article.get("key_insight")
        if isinstance(insight, str):
            parts.append(insight)
        source = article.get("source") or article.get("source_type")
        if source:
            parts.append(str(source))
        tags = article.get("tags")
        if isinstance(tags, list):
            parts.extend(str(tag) for tag in tags)
        return " ".join(parts).lower()

    @staticmethod
    def _article_date_str(article: dict[str, Any]) -> str:
        """提取条目日期（``collected_at`` 优先，回退 id 内嵌日期）。

        Args:
            article: 单篇知识条目字典。

        Returns:
            标准 ``YYYY-MM-DD`` 日期字符串；无法提取时返回空串。
        """
        date = formatter._article_date(article)
        if date:
            return date
        return formatter._id_date(str(article.get("id", "")))

    def _matches(
        self,
        article: dict[str, Any],
        keyword: str | None,
        tags: set[str],
        date_from: str | None,
        date_to: str | None,
    ) -> bool:
        """判断单篇条目是否满足全部过滤条件。

        Args:
            article: 单篇知识条目字典。
            keyword: 关键词子串；None 或空表示不过滤。
            tags: 需全部命中的标签集合；空集合表示不过滤。
            date_from: 起始日期（含）；None 表示不限。
            date_to: 结束日期（含）；None 表示不限。

        Returns:
            满足全部条件返回 True，否则 False。
        """
        if keyword and keyword.lower() not in self._article_text(article):
            return False
        if tags:
            # 统一小写后比对，兼容历史数据中大小写不一致的标签（如 RAG / rag）
            article_tags = {str(tag).lower() for tag in (article.get("tags") or [])}
            if not tags.issubset(article_tags):
                return False
        if date_from or date_to:
            date = self._article_date_str(article)
            if not date:
                return False
            if date_from and date < date_from:
                return False
            if date_to and date > date_to:
                return False
        return True

    def search(
        self,
        keyword: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """按条件搜索知识条目。

        多个条件为 AND 关系；结果按相关性评分降序，最多返回 ``limit`` 条。

        Args:
            keyword: 关键词，匹配标题/摘要/要点/洞察/标签等。
            tags: 标签列表，条目需全部包含这些标签。
            date_from: 起始日期（``YYYY-MM-DD``，含）。
            date_to: 结束日期（``YYYY-MM-DD``，含）。
            limit: 返回条数上限，默认 10。

        Returns:
            匹配的知识条目列表。
        """
        tag_set = {tag.strip().lower() for tag in tags} if tags else set()
        matched = [
            article
            for article in self._load_articles()
            if self._matches(article, keyword, tag_set, date_from, date_to)
        ]
        matched.sort(key=formatter._score, reverse=True)
        return matched[:limit]

    def top(self, limit: int = DEFAULT_TOP_LIMIT) -> list[dict[str, Any]]:
        """返回相关性评分最高的 N 条知识条目。

        Args:
            limit: 返回条数上限，默认 5。

        Returns:
            按相关性降序的知识条目列表。
        """
        articles = self._load_articles()
        articles.sort(key=formatter._score, reverse=True)
        return articles[:limit]

    def today(self, date: str | None = None) -> list[dict[str, Any]]:
        """返回指定日期的知识条目。

        Args:
            date: 日期（``YYYY-MM-DD``）；None 时使用今天 UTC。

        Returns:
            该日期下的全部知识条目。
        """
        target = date or datetime.now(timezone.utc).strftime(formatter.DATE_FORMAT)
        return [
            article
            for article in self._load_articles()
            if self._article_date_str(article) == target
        ]


# ── 订阅管理 ──────────────────────────────────────────────────────────────


class SubscriptionManager:
    """用户订阅管理（增删查）。

    支持可选的 JSON 文件落盘，重启后恢复；未指定路径时仅在内存中维护。

    Args:
        storage_path: 订阅持久化文件路径；None 表示不落盘。
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path else None
        self._subscriptions: dict[str, set[str]] = {}
        if self._storage_path and self._storage_path.exists():
            self._load()

    def subscribe(self, user_id: str, topic: str) -> bool:
        """为指定用户新增订阅主题。

        Args:
            user_id: 用户标识。
            topic: 订阅主题（关键词或标签，≤32 个合法字符）。

        Returns:
            首次订阅返回 True；已订阅过返回 False。

        Raises:
            ValueError: 主题格式非法时抛出。
        """
        topic = topic.strip()
        if not SUBSCRIPTION_TOPIC_PATTERN.match(topic):
            raise ValueError(f"非法订阅主题：{topic}")
        topics = self._subscriptions.setdefault(user_id, set())
        if topic in topics:
            return False
        topics.add(topic)
        self._save()
        return True

    def unsubscribe(self, user_id: str, topic: str) -> bool:
        """移除指定用户的订阅主题。

        Args:
            user_id: 用户标识。
            topic: 要退订的主题。

        Returns:
            实际移除返回 True；原本未订阅返回 False。
        """
        topic = topic.strip()
        topics = self._subscriptions.get(user_id, set())
        if topic not in topics:
            return False
        topics.discard(topic)
        self._save()
        return True

    def get_subscriptions(self, user_id: str) -> list[str]:
        """查询指定用户的订阅主题列表。

        Args:
            user_id: 用户标识。

        Returns:
            排序后的订阅主题列表（可能为空）。
        """
        return sorted(self._subscriptions.get(user_id, set()))

    def _save(self) -> None:
        """将订阅落盘为 JSON（storage_path 未设置时跳过）。"""
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            user_id: sorted(topics) for user_id, topics in self._subscriptions.items()
        }
        self._storage_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load(self) -> None:
        """从 JSON 文件恢复订阅（解析失败时保持空状态）。"""
        if not self._storage_path:
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("订阅文件解析失败，重置为空: %s", self._storage_path)
            return
        for user_id, topics in data.items():
            if isinstance(topics, list):
                self._subscriptions[str(user_id)] = {str(topic) for topic in topics}


# ── 权限管理 ──────────────────────────────────────────────────────────────


class PermissionDeniedError(Exception):
    """权限不足异常。

    Attributes:
        user_id: 发起操作的用户标识。
        permission: 缺失的权限。
    """

    def __init__(self, user_id: str, permission: Permission) -> None:
        super().__init__(f"用户 {user_id} 缺少权限 {permission.value}")
        self.user_id = user_id
        self.permission = permission


class PermissionManager:
    """三级权限管理（READ / WRITE / DELETE）。

    新用户默认拥有 :data:`Permission.READ`；WRITE / DELETE 需显式授予。
    默认权限默认包含 READ，可通过 ``default_permissions`` 覆盖。

    Args:
        default_permissions: 对所有用户默认授予的权限集合。
    """

    def __init__(self, default_permissions: set[Permission] | None = None) -> None:
        self._default_permissions = set(default_permissions or {Permission.READ})
        self._grants: dict[str, set[Permission]] = {}

    def grant(self, user_id: str, permission: Permission) -> None:
        """为指定用户授予权限。

        Args:
            user_id: 用户标识。
            permission: 要授予的权限。
        """
        self._grants.setdefault(user_id, set()).add(permission)

    def revoke(self, user_id: str, permission: Permission) -> None:
        """撤销指定用户的显式授予权限。

        对默认权限（如 READ）的撤销不生效，仅影响显式授予的部分。

        Args:
            user_id: 用户标识。
            permission: 要撤销的权限。
        """
        self._grants.get(user_id, set()).discard(permission)

    def has_permission(self, user_id: str, permission: Permission) -> bool:
        """判断用户是否具备指定权限。

        Args:
            user_id: 用户标识。
            permission: 待检查的权限。

        Returns:
            具备（显式授予或默认授予）返回 True。
        """
        granted = self._grants.get(user_id, set())
        return permission in granted or permission in self._default_permissions

    def check_or_raise(self, user_id: str, permission: Permission) -> None:
        """检查权限，不足时抛出异常。

        Args:
            user_id: 用户标识。
            permission: 待检查的权限。

        Raises:
            PermissionDeniedError: 用户不具备该权限时抛出。
        """
        if not self.has_permission(user_id, permission):
            raise PermissionDeniedError(user_id, permission)


# ── Bot 主入口 ────────────────────────────────────────────────────────────


class KnowledgeBot:
    """整合搜索、订阅与权限的知识库机器人。

    Args:
        search_engine: 搜索引擎实例；None 时自动创建。
        subscriptions: 订阅管理实例；None 时自动创建。
        permissions: 权限管理实例；None 时自动创建。
    """

    def __init__(
        self,
        search_engine: KnowledgeSearchEngine | None = None,
        subscriptions: SubscriptionManager | None = None,
        permissions: PermissionManager | None = None,
    ) -> None:
        self._search = search_engine or KnowledgeSearchEngine()
        self._subscriptions = subscriptions or SubscriptionManager()
        self._permissions = permissions or PermissionManager()

    def handle_message(self, user_id: str, text: str) -> str:
        """统一消息入口：识别意图并按权限分发到对应处理器。

        Args:
            user_id: 用户标识。
            text: 用户消息原文。

        Returns:
            面向用户的回复文本。
        """
        intent, params = recognize_intent(text)
        handlers = {
            Intent.SEARCH: self._handle_search,
            Intent.TODAY: self._handle_today,
            Intent.TOP: self._handle_top,
            Intent.SUBSCRIBE: self._handle_subscribe,
            Intent.HELP: self._handle_help,
        }
        handler = handlers.get(intent)
        if handler is None:
            return self._help_text()
        try:
            return handler(user_id, params)
        except PermissionDeniedError as exc:
            return str(exc)

    def _require(self, user_id: str, permission: Permission) -> None:
        """校验用户权限，不足时抛出异常。

        Args:
            user_id: 用户标识。
            permission: 所需权限。

        Raises:
            PermissionDeniedError: 用户不具备该权限时抛出。
        """
        self._permissions.check_or_raise(user_id, permission)

    def _handle_search(self, user_id: str, params: str) -> str:
        """处理搜索意图。

        Args:
            user_id: 用户标识。
            params: 参数文本（形如 ``关键词 标签:xx 日期:2026-07-01~07-31``）。

        Returns:
            搜索结果文本或提示。
        """
        self._require(user_id, Permission.READ)
        keyword, tags, date_from, date_to, limit = _parse_search_params(params)
        if not keyword and not tags and not date_from and not date_to:
            return "请提供搜索条件，如：/search LLM 标签:agent"
        results = self._search.search(keyword, tags, date_from, date_to, limit=limit)
        if not results:
            return "未找到匹配的知识条目"
        return self._format_results(results)

    def _handle_today(self, user_id: str, params: str) -> str:
        """处理今日条目意图。

        Args:
            user_id: 用户标识。
            params: 可选日期参数。

        Returns:
            当日条目文本或提示。
        """
        self._require(user_id, Permission.READ)
        date = params.strip() or datetime.now(timezone.utc).strftime(
            formatter.DATE_FORMAT
        )
        articles = self._search.today(date)
        if not articles:
            return f"📭 {date} {DEFAULT_TODAY_HINT}"
        return f"📅 {date} 共 {len(articles)} 篇：\n" + self._format_results(articles)

    def _handle_top(self, user_id: str, params: str) -> str:
        """处理 Top N 意图。

        Args:
            user_id: 用户标识。
            params: 可选数量参数（纯数字）。

        Returns:
            Top 列表文本或提示。
        """
        self._require(user_id, Permission.READ)
        limit = DEFAULT_TOP_LIMIT
        number = re.search(r"\d+", params)
        if number:
            limit = int(number.group(0))
        articles = self._search.top(limit)
        if not articles:
            return "知识库暂无条目"
        return f"🏆 Top {len(articles)}：\n" + self._format_results(articles)

    def _handle_subscribe(self, user_id: str, params: str) -> str:
        """处理订阅/退订意图（需要 WRITE 权限）。

        无参数时列出当前订阅；``退订 <主题>`` 前缀触发退订。

        Args:
            user_id: 用户标识。
            params: 订阅主题或退订指令。

        Returns:
            订阅操作结果文本。
        """
        self._require(user_id, Permission.WRITE)
        params = params.strip()
        if not params:
            topics = self._subscriptions.get_subscriptions(user_id)
            if not topics:
                return "你还没有任何订阅，输入 `/subscribe 主题` 添加"
            topics_text = "\n".join(f"- {topic}" for topic in topics)
            return f"当前订阅（{len(topics)}）：\n{topics_text}"

        if re.match(r"^(退订|unsubscribe|/unsubscribe)\s*", params):
            topic = re.sub(r"^(退订|unsubscribe|/unsubscribe)\s*", "", params).strip()
            if not topic:
                return "用法：/subscribe 退订 主题"
            removed = self._subscriptions.unsubscribe(user_id, topic)
            return f"已退订「{topic}」" if removed else f"未订阅「{topic}」"

        try:
            added = self._subscriptions.subscribe(user_id, params)
        except ValueError as exc:
            return str(exc)
        if added:
            return f"✅ 已订阅「{params}」"
        return f"「{params}」已在订阅列表中"

    def _handle_help(self, user_id: str, params: str) -> str:
        """处理帮助意图。

        Args:
            user_id: 用户标识。
            params: 未使用。

        Returns:
            使用帮助文本。
        """
        self._require(user_id, Permission.READ)
        return self._help_text()

    @staticmethod
    def _help_text() -> str:
        """构建使用帮助文本。

        Returns:
            命令用法说明。
        """
        return "\n".join(
            [
                "🤖 知识库助手",
                "/search <关键词> [标签:xx] [日期:2026-07-01~07-31]  搜索",
                "/today  今日新增",
                "/top [N]  相关性 Top N",
                "/subscribe <主题>  订阅 / 退订（需 WRITE 权限）",
                "/help  帮助",
            ]
        )

    @staticmethod
    def _format_results(articles: list[dict[str, Any]]) -> str:
        """将知识条目列表格式化为文本。

        Args:
            articles: 知识条目列表。

        Returns:
            每行一条目，含标题、相关性、标签与原文链接。
        """
        lines: list[str] = []
        for article in articles:
            title = str(article.get("title", "未命名"))
            score = formatter._score(article)
            tags = ",".join(str(tag) for tag in (article.get("tags") or []))
            line = f"- {title}（相关性 {score:.2f}）"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
            url = article.get("url") or article.get("source_url")
            if url:
                lines.append(f"  {url}")
        return "\n".join(lines)


def _parse_search_params(
    params: str,
) -> tuple[str | None, list[str] | None, str | None, str | None, int]:
    """解析搜索参数文本。

    支持 ``标签:xx`` / ``tag:xx``（逗号分隔多值）、``日期:YYYY-MM-DD`` 或
    ``日期:起~止``、``数量:N`` / ``limit:N``；其余部分视为关键词。

    Args:
        params: 参数文本。

    Returns:
        ``(keyword, tags, date_from, date_to, limit)`` 元组，未提供的项为 None。
    """
    keyword = None
    tags: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit = DEFAULT_SEARCH_LIMIT

    for match in SEARCH_PARAM_PATTERN.finditer(params):
        if match.group("tags"):
            tags = [
                tag.strip() for tag in match.group("tags").split(",") if tag.strip()
            ]
        if match.group("date"):
            raw = match.group("date")
            if "~" in raw:
                left, right = raw.split("~", 1)
                date_from = left.strip() or None
                date_to = right.strip() or None
            else:
                date_from = date_to = raw
        if match.group("limit"):
            limit = int(match.group("limit"))

    cleaned = SEARCH_PARAM_PATTERN.sub("", params).strip()
    if cleaned:
        keyword = cleaned
    return keyword, tags, date_from, date_to, limit
