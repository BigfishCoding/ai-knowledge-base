"""Router 路由模式实现。

统一入口 :func:`route` 对用户输入做**两层意图分类**：

1. 第一层：关键词快速匹配（零成本，不调用 LLM）
2. 第二层：LLM 分类兜底（处理模糊意图）

三种意图，各自对应一个处理器函数：

- ``github_search``  → 调用 GitHub Search API 搜索仓库
- ``knowledge_query`` → 从本地知识库索引检索
- ``general_chat``   → 调用 LLM 直接回答

用法:
    python patterns/router.py
"""

import json
import logging
import os
import re
import sys
import http.client
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 项目根目录注入 sys.path，保证以 `python patterns/router.py` 方式运行时可导入 workflows 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.model_client import chat, chat_json

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_USER_AGENT = "ai-knowledge-base/1.0"

ENV_GITHUB_TOKEN = "GITHUB_TOKEN"

INDEX_PATH = PROJECT_ROOT / "knowledge" / "articles" / "index.json"

SEARCH_RESULT_LIMIT = 5
KNOWLEDGE_RESULT_LIMIT = 3
QUERY_TIMEOUT_SECONDS = 15

# 意图常量
INTENT_GITHUB_SEARCH = "github_search"
INTENT_KNOWLEDGE_QUERY = "knowledge_query"
INTENT_GENERAL_CHAT = "general_chat"
VALID_INTENTS = {INTENT_GITHUB_SEARCH, INTENT_KNOWLEDGE_QUERY, INTENT_GENERAL_CHAT}

# 第一层关键词表（小写匹配，命中越多的意图胜出）
GITHUB_KEYWORDS = [
    "github", "仓库", "repo", "repos", "开源项目", "star", "stars",
    "trending", "热门项目", "代码库", "repository",
]
KNOWLEDGE_KEYWORDS = [
    "知识库", "知识", "article", "articles", "条目", "索引",
    "know", "knowledge", "entry", "entries",
]

# 中文命令填充词：剔除后保留真正的检索载荷
SEARCH_STOPWORDS = [
    "帮我", "请帮我", "搜索", "搜一下", "搜", "找一下", "找找",
    "看看", "查一下", "查询", "有没有", "相关", "关于", "一下",
    "推荐", "介绍", "有什么", "项目",
]

# 未知意图的兜底
DEFAULT_INTENT = INTENT_GENERAL_CHAT

# 分词正则：按空白与中文标点切分查询
TOKEN_PATTERN = re.compile(r"[\s,，。、；;:：'\"“”]+")


# ── 两层意图分类 ──────────────────────────────────────────────────────────


def _match_keywords(query: str) -> str | None:
    """第一层：关键词快速匹配意图。

    将查询转小写后统计三个意图各自的关键词命中数，
    命中最多的意图胜出；若无任何命中则返回 None，交由 LLM 兜底。

    Args:
        query: 用户原始输入。

    Returns:
        命中最多的意图名；无命中时返回 None。
    """
    lowered = query.lower()
    scores = {
        INTENT_GITHUB_SEARCH: sum(1 for kw in GITHUB_KEYWORDS if kw in lowered),
        INTENT_KNOWLEDGE_QUERY: sum(1 for kw in KNOWLEDGE_KEYWORDS if kw in lowered),
    }

    best_intent = max(scores, key=scores.get)
    if scores[best_intent] == 0:
        return None
    return best_intent


def _llm_classify(query: str) -> str:
    """第二层：LLM 分类兜底，处理关键词无法判定的模糊意图。

    Args:
        query: 用户原始输入。

    Returns:
        三类意图之一，LLM 返回非法值时回退为 general_chat。
    """
    system = (
        "你是意图分类器，只能返回以下三种意图之一："
        f"{INTENT_GITHUB_SEARCH}（查询/搜索 GitHub 上的开源项目）、"
        f"{INTENT_KNOWLEDGE_QUERY}（查询本地 AI 知识库中的内容）、"
        f"{INTENT_GENERAL_CHAT}（其他一般性对话）。"
        "请以 JSON 返回，格式为 {\"intent\": \"<意图名>\"}。"
    )
    prompt = f"用户输入：{query}\n请判断其意图。"

    try:
        data, _ = chat_json(prompt, system=system)
        intent = data.get("intent")
    except (ValueError, RuntimeError) as exc:
        logger.warning("LLM 意图分类失败, 回退到 general_chat: %s", exc)
        return DEFAULT_INTENT

    if intent not in VALID_INTENTS:
        logger.warning("LLM 返回非法意图 %r, 回退到 general_chat", intent)
        return DEFAULT_INTENT

    return intent


def classify_intent(query: str) -> str:
    """两层意图分类主流程。

    Args:
        query: 用户原始输入。

    Returns:
        意图名，取值为 github_search / knowledge_query / general_chat 之一。
    """
    intent = _match_keywords(query)
    if intent is not None:
        logger.debug("关键词匹配命中意图: %s", intent)
        return intent
    return _llm_classify(query)


# ── 处理器函数 ────────────────────────────────────────────────────────────


def _handle_github_search(query: str) -> str:
    """github_search 处理器：调用 GitHub Search API 搜索仓库。

    Args:
        query: 用户原始输入，去除关键词后的剩余部分作为搜索词。

    Returns:
        格式化后的仓库搜索结果文本。
    """
    search_query = _clean_query(query, GITHUB_KEYWORDS) or query.strip()
    encoded = urllib.parse.quote(search_query, safe="")
    url = (
        f"{GITHUB_SEARCH_API}?q={encoded}"
        f"&sort=stars&order=desc&per_page={SEARCH_RESULT_LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": GITHUB_USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    token = os.environ.get(ENV_GITHUB_TOKEN)
    if token:
        request.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(request, timeout=QUERY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        http.client.RemoteDisconnected,
        ConnectionError,
    ) as exc:
        logger.error("GitHub Search API 调用失败: %s", exc)
        return f"GitHub 搜索失败：{exc}"

    items = payload.get("items", [])
    if not items:
        return f"GitHub 上未找到与「{search_query}」相关的仓库。"

    lines = [f"GitHub 搜索「{search_query}」Top {len(items)} 结果："]
    for i, item in enumerate(items, start=1):
        lines.append(
            f"{i}. {item.get('full_name', 'unknown')} "
            f"★{item.get('stargazers_count', 0)} "
            f"({item.get('language') or 'unknown'})\n"
            f"   {item.get('html_url', '')}\n"
            f"   {item.get('description') or '无描述'}"
        )
    return "\n".join(lines)


def _handle_knowledge_query(query: str) -> str:
    """knowledge_query 处理器：从本地知识库索引检索条目。

    Args:
        query: 用户原始输入，去除关键词后的剩余部分作为检索词。

    Returns:
        格式化后的知识条目检索结果文本。
    """
    search_query = _clean_query(query, KNOWLEDGE_KEYWORDS) or query.strip()

    if not INDEX_PATH.exists():
        logger.error("知识库索引不存在: %s", INDEX_PATH)
        return "知识库索引不存在，请先运行分析流程生成 index.json。"

    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("知识库索引读取/解析失败: %s", exc)
        return f"知识库索引解析失败：{exc}"

    tokens = [t for t in TOKEN_PATTERN.split(search_query.lower()) if t]

    scored: list[tuple[int, dict]] = []
    for article in index.get("articles", []):
        haystack = " ".join([
            str(article.get("title", "")),
            str(article.get("summary", "")),
            " ".join(article.get("tags", [])),
        ]).lower()
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            scored.append((score, article))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = [article for _, article in scored[:KNOWLEDGE_RESULT_LIMIT]]

    if not top:
        return f"知识库中未找到与「{search_query}」相关的条目。"

    lines = [f"知识库检索「{search_query}」找到 {len(top)} 条："]
    for i, article in enumerate(top, start=1):
        lines.append(
            f"{i}. {article.get('title', 'unknown')}\n"
            f"   {article.get('summary', '')}\n"
            f"   来源: {article.get('source_url', '')}"
        )
    return "\n".join(lines)


def _handle_general_chat(query: str) -> str:
    """general_chat 处理器：调用 LLM 直接回答。

    Args:
        query: 用户原始输入。

    Returns:
        LLM 的回复文本。
    """
    try:
        text, _ = chat(query)
    except RuntimeError as exc:
        logger.error("general_chat 调用 LLM 失败: %s", exc)
        return f"对话服务不可用：{exc}"
    return text


def _strip_keywords(query: str, keywords: list[str]) -> str:
    """从查询中剔除已知关键词，保留真正的意图载荷。

    Args:
        query: 用户原始输入。
        keywords: 需要剔除的关键词列表。

    Returns:
        剔除关键词后的查询文本。
    """
    lowered = query.lower()
    stripped = query
    for kw in sorted(keywords, key=len, reverse=True):
        if kw in lowered:
            stripped = re.sub(re.escape(kw), " ", stripped, flags=re.IGNORECASE)
            lowered = stripped.lower()
    return stripped


def _clean_query(query: str, keywords: list[str]) -> str:
    """去除关键词与中文填充词，得到干净的检索词。

    先剔除触发意图的关键词，再剔除通用命令填充词，
    避免诸如「帮我搜一下 GitHub 上的」这类噪音进入检索。

    Args:
        query: 用户原始输入。
        keywords: 意图关键词列表。

    Returns:
        清洗后的检索词语。
    """
    cleaned = _strip_keywords(query, keywords)
    cleaned = _strip_keywords(cleaned, SEARCH_STOPWORDS)
    return cleaned.strip()


# ── 统一入口 ──────────────────────────────────────────────────────────────


def route(query: str) -> str:
    """Router 统一入口：意图分类后分发到对应处理器。

    Args:
        query: 用户原始输入。

    Returns:
        对应处理器的文本输出。
    """
    intent = classify_intent(query)
    logger.info("意图分类结果: %s | 输入: %s", intent, query)

    handlers = {
        INTENT_GITHUB_SEARCH: _handle_github_search,
        INTENT_KNOWLEDGE_QUERY: _handle_knowledge_query,
        INTENT_GENERAL_CHAT: _handle_general_chat,
    }
    handler = handlers.get(intent, _handle_general_chat)
    return handler(query)


# ── 测试入口 ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(route(query))
    else:
        test_queries = [
            "帮我搜一下 GitHub 上的 RAG 项目",
            "github 搜索 agent 框架",
            "知识库里有没有 RAG 相关的条目",
            "知识库中 LangChain 是什么？",
            "你好，介绍一下你自己",
            "今天天气怎么样",
        ]

        for q in test_queries:
            print("=" * 60)
            print(f"输入: {q}")
            print("-" * 60)
            print(route(q))
            print()
