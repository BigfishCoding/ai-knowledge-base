"""LangGraph 工作流节点定义。

五个节点组成采集 → 分析 → 整理 → 审核 → 保存的流水线，
每个节点是纯函数：接收 :class:`KBState`，返回部分状态更新的字典
（LangGraph 会将返回值 merge 回全局 state）。

节点一览：
- ``collect_node``: GitHub Search API 采集 AI 相关仓库
- ``analyze_node``: LLM 生成中文摘要、标签、评分
- ``organize_node``: 过滤低分(<0.6)、按 URL 去重、应用审核反馈修正
- ``review_node``: LLM 四维度审核，iteration >= 2 强制通过
- ``save_node``: 写入 knowledge/articles/ JSON 文件并重建 index.json
"""

import http.client
import json
import logging
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 项目根目录注入 sys.path，保证以脚本方式运行时 workflows 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.model_client import accumulate_usage, chat, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_AI_QUERY = "LLM OR AI OR agent"
GITHUB_USER_AGENT = "ai-knowledge-base/1.0"
GITHUB_RESULT_LIMIT = 5
GITHUB_SORT = "stars"

ENV_GITHUB_TOKEN = "GITHUB_TOKEN"

SOURCE_TYPE = "github_trending"
SCORE_KEEP_THRESHOLD = 0.6
REVIEW_FORCE_ITERATION = 2
QUERY_TIMEOUT_SECONDS = 15

ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILENAME = "index.json"

ANALYZE_SYSTEM = (
    "你是 AI 技术内容分析 Agent。对每条 GitHub 仓库信息生成结构化中文分析，"
    "只输出合法 JSON，不要输出任何多余文字。"
)
REVIEW_SYSTEM = (
    "你是知识条目审核 Agent。从摘要质量、标签准确、分类合理、一致性四个维度"
    "审核知识条目，只输出合法 JSON，不要输出任何多余文字。"
)
FIX_SYSTEM = (
    "你是知识条目修正 Agent。根据审核反馈定向修正知识条目列表，"
    "保持条目结构与 JSON 格式，只输出合法 JSON。"
)


# ── 工具函数 ──────────────────────────────────────────────────────────────


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _make_slug(title: str) -> str:
    """从条目标题生成文件名 slug。

    Args:
        title: 条目标题，如 ``Significant-Gravitas/AutoGPT``。

    Returns:
        小写、仅含字母数字与连字符的 slug，如 ``autogpt``。
    """
    last = title.strip().split("/")[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", last.lower()).strip("-")
    return slug or "untitled"


def _build_github_request(query: str) -> urllib.request.Request:
    """构建带鉴权头的 GitHub Search API 请求。

    Args:
        query: 搜索关键词（将用 urllib.parse.quote 编码）。

    Returns:
        配置好的 Request 对象。
    """
    encoded = urllib.parse.quote(query, safe="")
    url = (
        f"{GITHUB_SEARCH_API}?q={encoded}"
        f"&sort={GITHUB_SORT}&order=desc&per_page={GITHUB_RESULT_LIMIT}"
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": GITHUB_USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    token = os.environ.get(ENV_GITHUB_TOKEN, "")
    if token:
        request.add_header("Authorization", f"token {token}")

    # 配置代理（从环境变量读取）
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)

    return request


# ── 节点 1：采集 ──────────────────────────────────────────────────────────


def collect_node(state: KBState) -> dict[str, Any]:
    """采集节点：调用 GitHub Search API 抓取 AI 相关仓库。

    Args:
        state: 当前全局状态。

    Returns:
        部分更新：``sources``（SourceEntry 摘要列表）。
    """
    logger.info("[collect_node] 开始采集 GitHub AI 相关仓库")
    request = _build_github_request(GITHUB_AI_QUERY)

    try:
        with urllib.request.urlopen(request, timeout=QUERY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        http.client.RemoteDisconnected,
        ConnectionError,
        ssl.SSLError,
    ) as exc:
        logger.error("[collect_node] GitHub API 调用失败: %s", exc)
        return {"sources": []}

    items = payload.get("items", [])
    now = _now_iso()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sources: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        sources.append(
            {
                "source_id": f"gh-{date_str.replace('-', '')}-{index:03d}",
                "title": item.get("full_name", "unknown"),
                "url": item.get("html_url", ""),
                "source_type": SOURCE_TYPE,
                "collected_at": now,
                "popularity": float(item.get("stargazers_count", 0)),
                "summary": item.get("description") or "",
            }
        )

    logger.info("[collect_node] 采集到 %d 条仓库", len(sources))
    return {"sources": sources}


# ── 节点 2：分析 ──────────────────────────────────────────────────────────


def _build_analyze_prompt(source: dict[str, Any]) -> str:
    """构建单条 source 的分析提示词。"""
    return (
        "请分析以下 GitHub 仓库：\n"
        f"标题: {source['title']}\n"
        f"描述: {source['summary']}\n"
        f"Stars: {source['popularity']:.0f}\n"
        "输出 JSON：{\"summary\": str(中文摘要, <=100字), "
        "\"key_points\": list[str](2-5条), "
        "\"score\": float(0-1 技术价值与相关性), "
        "\"tags\": list[str](2-5个)}"
    )


def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：对每条 source 调用 LLM 生成中文摘要、标签、评分。

    Args:
        state: 当前全局状态。

    Returns:
        部分更新：``analyses``（AnalysisEntry 列表）与 ``cost_tracker``。
    """
    logger.info("[analyze_node] 开始分析 %d 条数据", len(state["sources"]))
    tracker = dict(state["cost_tracker"])
    analyses: list[dict[str, Any]] = []

    for source in state["sources"]:
        try:
            data, usage = chat_json(
                _build_analyze_prompt(source), system=ANALYZE_SYSTEM
            )
            tracker = accumulate_usage(tracker, usage)
        except (RuntimeError, ValueError) as exc:
            logger.warning("[analyze_node] 条目 %s 分析失败: %s", source["title"], exc)
            continue

        analyses.append(
            {
                "source_id": source["source_id"],
                "summary": str(data.get("summary", "")),
                "key_points": [str(k) for k in data.get("key_points", [])],
                "score": float(data.get("score", 0.0)),
                "tags": [str(t) for t in data.get("tags", [])],
            }
        )

    logger.info("[analyze_node] 分析完成 %d/%d 条", len(analyses), len(state["sources"]))
    return {"analyses": analyses, "cost_tracker": tracker}


# ── 节点 3：整理 ──────────────────────────────────────────────────────────


def _build_fix_prompt(articles: list[dict[str, Any]], feedback: str) -> str:
    """构建基于审核反馈的修正提示词。"""
    return (
        "根据以下审核反馈定向修正知识条目列表，只修改有问题的字段：\n"
        f"审核反馈：{feedback}\n"
        f"当前条目：{json.dumps(articles, ensure_ascii=False)}\n"
        "输出 JSON：{\"articles\": [{\"id\", \"title\", \"source_url\", "
        "\"source_type\", \"summary\", \"key_points\", \"tags\", \"status\"}]}"
    )


def organize_node(state: KBState) -> dict[str, Any]:
    """整理节点：过滤低分条目、按 URL 去重、应用审核反馈修正。

    Args:
        state: 当前全局状态。

    Returns:
        部分更新：``articles``（ArticleEntry 列表）与 ``cost_tracker``。
    """
    logger.info("[organize_node] 整理 %d 条分析结果", len(state["analyses"]))
    tracker = dict(state["cost_tracker"])
    source_map = {s["source_id"]: s for s in state["sources"]}

    seen_urls: set[str] = set()
    articles: list[dict[str, Any]] = []

    for analysis in state["analyses"]:
        # 过滤低分条目
        if analysis["score"] < SCORE_KEEP_THRESHOLD:
            logger.debug("[organize_node] 剔除低分条目 %s", analysis["source_id"])
            continue

        source = source_map.get(analysis["source_id"])
        if not source:
            continue

        # 按 URL 去重（保留首个出现）
        if source["url"] in seen_urls:
            logger.debug("[organize_node] 去重跳过 %s", source["url"])
            continue
        seen_urls.add(source["url"])

        articles.append(
            {
                "id": analysis["source_id"],
                "title": source["title"],
                "source_url": source["url"],
                "source_type": source["source_type"],
                "summary": analysis["summary"],
                "key_points": analysis["key_points"],
                "tags": analysis["tags"],
                "status": "draft",
            }
        )

    # 有审核反馈时用 LLM 定向修正
    if state["iteration"] > 0 and state["review_feedback"] and articles:
        logger.info("[organize_node] 应用审核反馈修正 %d 条条目", len(articles))
        try:
            data, usage = chat_json(
                _build_fix_prompt(articles, state["review_feedback"]),
                system=FIX_SYSTEM,
            )
            tracker = accumulate_usage(tracker, usage)
            fixed = data.get("articles")
            if isinstance(fixed, list) and fixed:
                articles = fixed
        except (RuntimeError, ValueError) as exc:
            logger.warning("[organize_node] 反馈修正失败，保留原条目: %s", exc)

    logger.info("[organize_node] 整理完成，保留 %d 条", len(articles))
    return {"articles": articles, "cost_tracker": tracker}


# ── 节点 4：审核 ──────────────────────────────────────────────────────────


def _build_review_prompt(articles: list[dict[str, Any]]) -> str:
    """构建四维度审核提示词。"""
    return (
        "请从四个维度审核以下知识条目：摘要质量、标签准确、分类合理、一致性。\n"
        f"条目列表：{json.dumps(articles, ensure_ascii=False)}\n"
        "输出 JSON：{\"passed\": bool, \"overall_score\": float(0-1), "
        "\"feedback\": str(具体改进意见), "
        "\"scores\": {\"summary_quality\": float, \"tag_accuracy\": float, "
        "\"category_reasonableness\": float, \"consistency\": float}}"
    )


def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：LLM 四维度评分，达到最大轮次时强制通过。

    Args:
        state: 当前全局状态。

    Returns:
        部分更新：``review_passed``、``review_feedback``、``iteration``、
        ``cost_tracker``。
    """
    iteration = state["iteration"] + 1
    logger.info("[review_node] 第 %d 轮审核", iteration)

    # 达到最大审核轮次：不再调用 LLM，强制通过
    if state["iteration"] >= REVIEW_FORCE_ITERATION:
        logger.info("[review_node] 达到最大审核轮次，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "达到最大审核轮次，强制通过",
            "iteration": iteration,
        }

    tracker = dict(state["cost_tracker"])
    try:
        data, usage = chat_json(
            _build_review_prompt(state["articles"]), system=REVIEW_SYSTEM
        )
        tracker = accumulate_usage(tracker, usage)
    except (RuntimeError, ValueError) as exc:
        logger.error("[review_node] 审核调用失败: %s", exc)
        return {
            "review_passed": False,
            "review_feedback": f"审核调用失败：{exc}",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    passed = bool(data.get("passed"))
    logger.info(
        "[review_node] 第 %d 轮结果: passed=%s overall_score=%s",
        iteration,
        passed,
        data.get("overall_score"),
    )
    return {
        "review_passed": passed,
        "review_feedback": str(data.get("feedback") or ""),
        "iteration": iteration,
        "cost_tracker": tracker,
    }


# ── 节点 5：保存 ──────────────────────────────────────────────────────────


def _build_article_payload(article: dict[str, Any]) -> dict[str, Any]:
    """为落盘补充时间戳等元数据字段。"""
    now = _now_iso()
    return {
        **article,
        "collected_at": now,
        "analyzed_at": now,
        "distributed_to": [],
    }


def _rebuild_index() -> None:
    """重建 knowledge/articles/index.json 索引。

    扫描目录下所有条目文件（排除 index.json），
    汇总 id/title/summary/tags/source_url 生成检索索引。
    """
    entries: list[dict[str, Any]] = []
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        if path.name == INDEX_FILENAME:
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[save_node] 索引跳过文件 %s: %s", path.name, exc)
            continue
        entries.append(
            {
                "id": entry.get("id", ""),
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "tags": entry.get("tags", []),
                "source_url": entry.get("source_url", ""),
            }
        )

    index = {
        "version": 1,
        "updated_at": _now_iso(),
        "total": len(entries),
        "articles": entries,
    }
    (ARTICLES_DIR / INDEX_FILENAME).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("[save_node] 索引已更新: index.json (%d 条)", len(entries))


def save_node(state: KBState) -> dict[str, Any]:
    """保存节点：将 articles 写入 JSON 文件并重建索引。

    Args:
        state: 当前全局状态。

    Returns:
        空字典（终态节点，无后续状态变更）。
    """
    logger.info("[save_node] 保存 %d 条知识条目", len(state["articles"]))
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for article in state["articles"]:
        slug = _make_slug(article["title"])
        path = ARTICLES_DIR / f"{date_str}-{article['source_type']}-{slug}.json"

        # 同名文件存在时追加序号，避免覆盖（同日同源同 slug 冲突）
        seq = 2
        while path.exists():
            path = ARTICLES_DIR / f"{date_str}-{article['source_type']}-{slug}-{seq}.json"
            seq += 1

        payload = _build_article_payload(article)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("[save_node] 已写入 %s", path.name)

    _rebuild_index()
    return {}


# ── 节点注册表 ────────────────────────────────────────────────────────────

NODES = {
    "collect": collect_node,
    "analyze": analyze_node,
    "organize": organize_node,
    "review": review_node,
    "save": save_node,
}
