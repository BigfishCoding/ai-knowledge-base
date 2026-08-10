"""计划模块：Planner Agent 的 LangGraph 节点。

根据目标采集量（target_count）选择三档采集/审核策略，策略字典写入
:class:`KBState` 的 ``plan`` 字段，供下游节点（采集/分析/审核）参考。

策略分档：

- ``lite``：目标 < 10，聚焦少量高价值来源
- ``standard``：10 <= 目标 < 20，覆盖度与噪声的平衡
- ``full``：目标 >= 20，充分采掘并靠审核迭代兜底

用法:
    from workflows.planner import plan_strategy, planner_node
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

# 项目根目录注入 sys.path，保证以脚本方式运行时 workflows 包可导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

ENV_TARGET_COUNT = "PLANNER_TARGET_COUNT"
DEFAULT_TARGET_COUNT = 10
TARGET_BOUNDARY_LITE = 10
TARGET_BOUNDARY_STANDARD = 20

STRATEGY_LITE: dict[str, Any] = {
    "per_source_limit": 5,
    "relevance_threshold": 0.7,
    "max_iterations": 1,
    "rationale": (
        "目标采集量小于 10：降低单源采集量至 5、提高相关性门槛至 0.7，"
        "聚焦少数高质量来源，审核迭代减至 1 轮以控制延迟与成本"
    ),
}

STRATEGY_STANDARD: dict[str, Any] = {
    "per_source_limit": 10,
    "relevance_threshold": 0.5,
    "max_iterations": 2,
    "rationale": (
        "目标采集量 10-19：单源采集 10 条、相关性门槛 0.5，"
        "在覆盖度与噪声之间取得平衡，允许 2 轮审核迭代修正质量"
    ),
}

STRATEGY_FULL: dict[str, Any] = {
    "per_source_limit": 20,
    "relevance_threshold": 0.4,
    "max_iterations": 3,
    "rationale": (
        "目标采集量大于等于 20：单源采集 20 条充分采掘、相关性门槛降至 0.4 "
        "扩大候选池，以 3 轮审核迭代兜底质量"
    ),
}


# ── 策略选择 ──────────────────────────────────────────────────────────────


def _read_target_count() -> int:
    """从环境变量 PLANNER_TARGET_COUNT 读取目标采集量。

    Returns:
        解析后的目标采集量；环境变量缺失或值非法时回退默认值
        :data:`DEFAULT_TARGET_COUNT`。
    """
    raw = os.environ.get(ENV_TARGET_COUNT)
    if raw is None:
        return DEFAULT_TARGET_COUNT
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "[planner] 环境变量 %s 非法（%r），回退默认值 %d",
            ENV_TARGET_COUNT,
            raw,
            DEFAULT_TARGET_COUNT,
        )
        return DEFAULT_TARGET_COUNT


def plan_strategy(target_count: int | None = None) -> dict[str, Any]:
    """按目标采集量选择三档策略之一。

    Args:
        target_count: 目标采集量；None 时从环境变量
            ``PLANNER_TARGET_COUNT`` 读取（非法则回退默认 10）。

    Returns:
        所选策略字典，含 ``per_source_limit`` / ``relevance_threshold`` /
        ``max_iterations`` / ``rationale`` 四个字段。
    """
    if target_count is None:
        target_count = _read_target_count()

    if target_count < TARGET_BOUNDARY_LITE:
        strategy = STRATEGY_LITE
    elif target_count < TARGET_BOUNDARY_STANDARD:
        strategy = STRATEGY_STANDARD
    else:
        strategy = STRATEGY_FULL

    logger.info(
        "[planner] 目标采集量 %d → per_source_limit=%s, "
        "relevance_threshold=%s, max_iterations=%s",
        target_count,
        strategy["per_source_limit"],
        strategy["relevance_threshold"],
        strategy["max_iterations"],
    )
    # 返回副本，避免调用方修改模块级常量
    return dict(strategy)


# ── 计划节点 ──────────────────────────────────────────────────────────────


def planner_node(state: KBState) -> dict[str, Any]:
    """计划节点：生成采集/审核策略并写入 state 的 plan 字段。

    Args:
        state: 当前全局状态（本节点仅写入，不读取业务字段）。

    Returns:
        部分更新：``plan``（策略字典）。
    """
    plan = plan_strategy()
    logger.info("[planner_node] 已生成计划: %s", plan)
    return {"plan": plan}
