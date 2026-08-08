"""知识条目审核模块：Reviewer Agent 的 LangGraph 节点。

对 :mod:`workflows.state` 中 ``analyses`` 的前 N 条分析结果执行
五维度评分（摘要质量 / 技术深度 / 相关性 / 原创性 / 格式规范），
由代码按固定权重重算加权总分，据此判定是否通过审核。

审核结论写入 :class:`KBState` 的 ``review_passed`` / ``review_feedback`` /
``iteration`` / ``cost_tracker``，供图条件路由与 organize 回炉修正使用。

用法:
    from workflows.reviewer import review_node
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any

# 项目根目录注入 sys.path，保证以脚本方式运行时 workflows 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

REVIEW_SYSTEM = (
    "你是 AI 知识条目审核 Agent。对每条分析结果从五个维度各打 1-10 整数分："
    "summary_quality(摘要质量)、technical_depth(技术深度)、relevance(相关性)、"
    "originality(原创性)、formatting(格式规范)。不要自行计算加权总分，"
    "只输出合法 JSON，不要输出任何多余文字。"
)
DIMENSION_WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}
REVIEW_LIMIT = 5
PASS_THRESHOLD = 7.0
REVIEW_TEMPERATURE = 0.1
MIN_SCORE = 1.0
MAX_SCORE = 10.0
DEFAULT_MISSING_SCORE = 1.0


# ── 提示词构建 ────────────────────────────────────────────────────────────


def _build_review_prompt(analyses: list[dict[str, Any]], plan: str) -> str:
    """构建五维度审核提示词。

    Args:
        analyses: 待审核的分析结果列表（AnalysisEntry 摘要）。
        plan: 项目计划/目标文本，用于评估相关性；空字符串则省略。

    Returns:
        发给模型的审核提示词。
    """
    plan_section = f"\n项目计划/目标：{plan}\n" if plan else ""
    return (
        "请对以下 AI 技术分析结果逐条评分，每维打 1-10 整数分：\n"
        "- summary_quality（摘要质量）\n"
        "- technical_depth（技术深度）\n"
        "- relevance（相关性）\n"
        "- originality（原创性）\n"
        "- formatting（格式规范）\n"
        f"{plan_section}"
        f"分析结果：{json.dumps(analyses, ensure_ascii=False)}\n"
        "输出 JSON：{\"reviews\": [{\"source_id\": str, "
        "\"scores\": {\"summary_quality\": int, \"technical_depth\": int, "
        "\"relevance\": int, \"originality\": int, \"formatting\": int}, "
        "\"feedback\": str}], \"overall_feedback\": str}"
    )


# ── 评分计算 ──────────────────────────────────────────────────────────────


def _clamp_score(value: Any, dimension: str) -> float:
    """将单维评分规范化到 [1,10] 区间。

    Args:
        value: 模型返回的原始评分（可能是 int/float/字符串）。
        dimension: 维度名，用于失败日志。

    Returns:
        夹取到合法区间的浮点分；值缺失或非法时返回兜底分。
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        logger.warning(
            "维度 %s 评分缺失或非法（%r），使用兜底分 %s",
            dimension,
            value,
            DEFAULT_MISSING_SCORE,
        )
        return DEFAULT_MISSING_SCORE
    return max(MIN_SCORE, min(MAX_SCORE, score))


def _weighted_total(scores: dict[str, Any]) -> float:
    """按固定权重计算五维加权总分。

    权重定义于 :data:`DIMENSION_WEIGHTS`（合计 1.0），总分落在 [1,10]。
    不使用模型给出的总分，全部由代码重算，规避模型算术误差。

    Args:
        scores: 维度名 → 评分的映射；缺失维度按兜底分处理。

    Returns:
        [1,10] 区间内的加权总分。
    """
    if not isinstance(scores, dict):
        logger.warning("scores 应为 dict，实际 %s，按空处理", type(scores).__name__)
        scores = {}
    return sum(
        _clamp_score(scores.get(dimension), dimension) * weight
        for dimension, weight in DIMENSION_WEIGHTS.items()
    )


# ── 结果解析 ──────────────────────────────────────────────────────────────


def _parse_reviews(payload: Any) -> tuple[list[dict[str, Any]], str]:
    """从模型返回中抽取逐条审核结果与整体反馈。

    Args:
        payload: chat_json 解析出的字典。

    Returns:
        ``(reviews, overall_feedback)`` 元组。

    Raises:
        ValueError: payload 非字典或 reviews 缺失/为空时抛出，
            交由调用方按失败放行。
    """
    if not isinstance(payload, dict):
        raise ValueError(f"审核结果应为字典，实际为 {type(payload).__name__}")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError(f"审核结果缺少 reviews 数组: {payload}")
    overall_feedback = str(payload.get("overall_feedback") or "")
    return reviews, overall_feedback


def _build_feedback(
    reviews: list[dict[str, Any]],
    overall_feedback: str,
    weighted_totals: list[float],
    overall_score: float,
) -> str:
    """汇总审核反馈文本，供 organize 节点回炉修正。

    Args:
        reviews: 逐条审核结果列表。
        overall_feedback: 模型给出的整体反馈。
        weighted_totals: 逐条加权总分（与 reviews 等长）。
        overall_score: 整体加权总分。

    Returns:
        多行文本：整体意见 + 逐条意见。
    """
    lines = [f"加权总分 {overall_score:.2f}（通过阈值 {PASS_THRESHOLD:.1f}）"]
    if overall_feedback:
        lines.append(f"整体意见：{overall_feedback}")
    for review, total in zip(reviews, weighted_totals):
        source_id = review.get("source_id", "")
        item_feedback = review.get("feedback", "")
        lines.append(f"[{source_id}] 加权 {total:.2f}: {item_feedback}")
    return "\n".join(lines)


# ── 审核节点 ──────────────────────────────────────────────────────────────


def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：对 analyses 前 N 条做五维度 LLM 评分并判定通过。

    评分一致性使用低温度（0.1）；加权总分由代码重算，通过阈值为 7.0；
    LLM 调用失败或结果异常时自动放行，避免阻塞流水线。
    超过 ``plan.max_iterations``（默认 3）时作为内部兜底强制通过，
    保证审核循环必然终止（正常流程在第 max 轮未通过时由图路由到
    ``human_flag`` 人工介入）。

    Args:
        state: 当前全局状态，读取 ``analyses`` / ``plan`` / ``iteration`` /
            ``cost_tracker``。

    Returns:
        部分更新：``review_passed``、``review_feedback``、``iteration``、
        ``cost_tracker``。
    """
    iteration = state["iteration"] + 1
    tracker = dict(state["cost_tracker"])

    plan = state.get("plan", {}) or {}
    if not isinstance(plan, dict):
        plan = {}
    max_iterations = int(plan.get("max_iterations", 3))

    # 内部兜底：超过计划轮次上限仍不通过时强制通过，保证审核循环必然终止
    if iteration > max_iterations:
        feedback = f"达到计划最大审核轮次 {max_iterations}，强制通过"
        logger.warning("[review_node] %s", feedback)
        return {
            "review_passed": True,
            "review_feedback": feedback,
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    analyses = state["analyses"][:REVIEW_LIMIT]
    if not analyses:
        logger.info("[review_node] 无待审核分析结果，自动通过")
        return {
            "review_passed": True,
            "review_feedback": "无待审核的分析结果，自动通过",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    plan_text = json.dumps(plan, ensure_ascii=False) if plan else ""

    try:
        payload, usage = chat_json(
            _build_review_prompt(analyses, plan_text),
            system=REVIEW_SYSTEM,
            temperature=REVIEW_TEMPERATURE,
        )
        tracker = accumulate_usage(tracker, usage)
        reviews, overall_feedback = _parse_reviews(payload)
    except (RuntimeError, ValueError) as exc:
        logger.warning("[review_node] LLM 审核失败，自动放行: %s", exc)
        return {
            "review_passed": True,
            "review_feedback": f"LLM 审核失败，自动通过: {exc}",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    # 代码重算加权总分（不信任模型算术）
    weighted_totals = [_weighted_total(review.get("scores")) for review in reviews]
    overall_score = sum(weighted_totals) / len(weighted_totals)
    review_passed = overall_score >= PASS_THRESHOLD
    feedback = _build_feedback(reviews, overall_feedback, weighted_totals, overall_score)

    logger.info(
        "[review_node] 第 %d 轮审核: overall_score=%.2f review_passed=%s",
        iteration,
        overall_score,
        review_passed,
    )
    return {
        "review_passed": review_passed,
        "review_feedback": feedback,
        "iteration": iteration,
        "cost_tracker": tracker,
    }
