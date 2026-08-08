"""LangGraph 工作流组装：StateGraph + 三路条件路由。

将计划/采集/分析/审核/修订/人工介入/整理/保存节点组装为带审核回环的图：

::

    plan → collect → analyze → review ──passed=True──→ organize → save → END
                                 │
                                 ├──passed=False & iteration<plan.max_iterations ──→ revise ──→ review
                                 │
                                 └──passed=False & iteration>=plan.max_iterations ──→ human_flag → END

用法:
    python workflows/graph.py
"""

import logging
import sys
from pathlib import Path
from typing import Any

# 项目根目录注入 sys.path，保证以脚本方式运行时 workflows 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.graph import END, StateGraph

from workflows import nodes
from workflows.human_flag import human_flag_node
from workflows.planner import planner_node
from workflows.reviser import revise_node
from workflows.state import KBState, new_state

logger = logging.getLogger(__name__)

# ── 节点名常量 ────────────────────────────────────────────────────────────

NODE_PLAN = "plan"
NODE_COLLECT = "collect"
NODE_ANALYZE = "analyze"
NODE_ORGANIZE = "organize"
NODE_REVIEW = "review"
NODE_REVISE = "revise"
NODE_HUMAN_FLAG = "human_flag"
NODE_SAVE = "save"


# ── 条件路由 ──────────────────────────────────────────────────────────────


def route_after_review(state: KBState) -> str:
    """审核后的三路条件路由（审核轮次上限取自计划）。

    - 通过 → ``organize``：继续整理并保存
    - 未通过且 ``iteration < plan.max_iterations``（默认 3） → ``revise``：回炉修订
    - 未通过且 ``iteration >= plan.max_iterations`` → ``human_flag``：人工介入终点

    Args:
        state: 当前全局状态。

    Returns:
        目标节点名 ``organize`` / ``revise`` / ``human_flag``。
    """
    if state.get("review_passed"):
        target = NODE_ORGANIZE
    else:
        plan = state.get("plan", {}) or {}
        if not isinstance(plan, dict):
            plan = {}
        max_iterations = int(plan.get("max_iterations", 3))
        if state["iteration"] < max_iterations:
            target = NODE_REVISE
        else:
            target = NODE_HUMAN_FLAG
    logger.info(
        "审核路由: review_passed=%s iteration=%d → %s",
        state.get("review_passed"),
        state["iteration"],
        target,
    )
    return target


# ── 图构建 ────────────────────────────────────────────────────────────────


def build_graph() -> Any:
    """组装并编译 LangGraph 工作流。

    Returns:
        编译后的 StateGraph app，可通过 ``app.stream(input)`` 执行。
    """
    graph = StateGraph(KBState)

    # 注册节点
    graph.add_node(NODE_PLAN, planner_node)
    graph.add_node(NODE_COLLECT, nodes.collect_node)
    graph.add_node(NODE_ANALYZE, nodes.analyze_node)
    graph.add_node(NODE_REVIEW, nodes.review_node)
    graph.add_node(NODE_REVISE, revise_node)
    graph.add_node(NODE_HUMAN_FLAG, human_flag_node)
    graph.add_node(NODE_ORGANIZE, nodes.organize_node)
    graph.add_node(NODE_SAVE, nodes.save_node)

    # 线性主链：先定计划，再采集、分析，随后审核（review 针对 analyses，先于 organize）
    graph.add_edge(NODE_PLAN, NODE_COLLECT)
    graph.add_edge(NODE_COLLECT, NODE_ANALYZE)
    graph.add_edge(NODE_ANALYZE, NODE_REVIEW)

    # 审核后的三路条件分支
    graph.add_conditional_edges(
        NODE_REVIEW,
        route_after_review,
        {
            NODE_ORGANIZE: NODE_ORGANIZE,
            NODE_REVISE: NODE_REVISE,
            NODE_HUMAN_FLAG: NODE_HUMAN_FLAG,
        },
    )

    # 回炉循环：修订后的 analyses 重新审核
    graph.add_edge(NODE_REVISE, NODE_REVIEW)

    # 通过后整理并保存；超限未通过则人工介入
    graph.add_edge(NODE_ORGANIZE, NODE_SAVE)
    graph.add_edge(NODE_HUMAN_FLAG, END)

    # 终点
    graph.add_edge(NODE_SAVE, END)

    # 入口：计划节点
    graph.set_entry_point(NODE_PLAN)

    return graph.compile()


# ── 流式执行辅助 ──────────────────────────────────────────────────────────


def _summarize_update(node_name: str, update: dict[str, Any] | None) -> str:
    """抽取单节点输出的关键字段，用于流式打印。

    Args:
        node_name: 当前节点名。
        update: 节点返回的部分状态更新；LangGraph 对无状态变更的节点
            可能给出 None（如 save_node 返回空字典）。

    Returns:
        单行关键输出摘要。
    """
    if update is None:
        update = {}
    if node_name == NODE_PLAN:
        plan = update.get("plan", {})
        return (
            f"per_source_limit={plan.get('per_source_limit')}, "
            f"relevance_threshold={plan.get('relevance_threshold')}, "
            f"max_iterations={plan.get('max_iterations')}"
        )
    if node_name == NODE_COLLECT:
        return f"sources={len(update.get('sources', []))} 条"
    if node_name == NODE_ANALYZE:
        tracker = update.get("cost_tracker", {})
        return (
            f"analyses={len(update.get('analyses', []))} 条, "
            f"llm_calls={tracker.get('llm_calls', 0)}, "
            f"tokens={tracker.get('total_tokens', 0)}"
        )
    if node_name == NODE_ORGANIZE:
        return f"articles={len(update.get('articles', []))} 条"
    if node_name == NODE_REVIEW:
        return (
            f"passed={update.get('review_passed')}, "
            f"iteration={update.get('iteration')}, "
            f"feedback={update.get('review_feedback', '')[:40]!r}"
        )
    if node_name == NODE_REVISE:
        return f"analyses={len(update.get('analyses', []))} 条（已修订）"
    if node_name == NODE_HUMAN_FLAG:
        return f"needs_human_review={update.get('needs_human_review')}"
    if node_name == NODE_SAVE:
        return "知识条目已保存"
    return str(update)


# ── 测试入口 ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = build_graph()

    try:
        print(app.get_graph().draw_ascii())
    except Exception as exc:
        logger.warning("绘制图结构失败: %s", exc)

    print("=" * 60)
    print("流式执行 pipeline")
    print("=" * 60)

    for chunk in app.stream(new_state()):
        for node_name, update in chunk.items():
            print(f"[{node_name}] {_summarize_update(node_name, update)}")
