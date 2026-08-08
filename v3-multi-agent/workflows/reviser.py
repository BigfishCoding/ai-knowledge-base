"""分析结果修订模块：Reviser Agent 的 LangGraph 节点。

在审核未通过时，依据 :class:`KBState` 中的 ``review_feedback`` 对
``analyses`` 逐条定向改写，再重新进入整理与审核流程。
修订使用较高温度（0.4）以允许创造性改写，但要求保持条目结构与 source_id 不变。

用法:
    from workflows.reviser import revise_node
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

REVISE_SYSTEM = (
    "你是 AI 技术内容修订 Agent。根据审核反馈对分析结果逐条定向改写，"
    "保持每条的结构与 JSON 格式不变，只输出合法 JSON，不要输出任何多余文字。"
)
REVISE_TEMPERATURE = 0.4


# ── 提示词构建 ────────────────────────────────────────────────────────────


def _build_revise_prompt(
    analyses: list[dict[str, Any]], feedback: str
) -> str:
    """构建注入审核反馈的修订提示词。

    Args:
        analyses: 待修订的分析结果列表（AnalysisEntry 摘要）。
        feedback: 上一轮审核的改进意见，需注入提示词指导改写。

    Returns:
        发给模型的修订提示词。
    """
    return (
        "请根据以下审核反馈定向修订分析结果，逐条改进有问题的字段，"
        "保持 source_id 不变：\n"
        f"审核反馈：{feedback}\n"
        f"当前分析结果：{json.dumps(analyses, ensure_ascii=False)}\n"
        "输出 JSON：{\"analyses\": [{\"source_id\": str, \"summary\": str, "
        "\"key_points\": list[str], \"score\": float(0-1), \"tags\": list[str]}]}"
    )


# ── 结果解析 ──────────────────────────────────────────────────────────────


def _parse_revised(payload: Any) -> list[dict[str, Any]]:
    """校验并抽取修订后的 analyses 列表。

    Args:
        payload: chat_json 解析出的字典。

    Returns:
        修订后的分析结果列表。

    Raises:
        ValueError: payload 非字典、analyses 缺失/为空或条目非字典时抛出，
            交由调用方按失败保留原 analyses。
    """
    if not isinstance(payload, dict):
        raise ValueError(f"修订结果应为字典，实际为 {type(payload).__name__}")
    analyses = payload.get("analyses")
    if not isinstance(analyses, list) or not analyses:
        raise ValueError(f"修订结果缺少 analyses 列表: {payload}")
    if not all(isinstance(item, dict) for item in analyses):
        raise ValueError("修订结果中混入非字典条目")
    return analyses


# ── 修订节点 ──────────────────────────────────────────────────────────────


def revise_node(state: KBState) -> dict[str, Any]:
    """修订节点：依据审核反馈对 analyses 定向改写。

    analyses 或 review_feedback 为空时跳过（返回空字典，不产生状态更新）；
    LLM 调用失败或结果异常时同样返回空字典，保持原 analyses，不阻塞流程。

    Args:
        state: 当前全局状态，读取 ``analyses`` / ``review_feedback`` /
            ``cost_tracker``。

    Returns:
        - ``analyses`` 或 ``review_feedback`` 为空：``{}``。
        - 修订成功：``{"analyses": improved, "cost_tracker": tracker}``。
        - LLM 失败或结果异常：``{}``（原 analyses 原样保留）。
    """
    analyses = state["analyses"]
    feedback = state["review_feedback"]

    # 无内容或无反馈时跳过，不产生任何状态更新
    if not analyses or not feedback:
        logger.info("[revise_node] analyses 或 feedback 为空，跳过修订")
        return {}

    tracker = dict(state["cost_tracker"])

    try:
        payload, usage = chat_json(
            _build_revise_prompt(analyses, feedback),
            system=REVISE_SYSTEM,
            temperature=REVISE_TEMPERATURE,
        )
        tracker = accumulate_usage(tracker, usage)
        improved = _parse_revised(payload)
    except (RuntimeError, ValueError) as exc:
        logger.warning("[revise_node] LLM 修订失败，保留原 analyses: %s", exc)
        return {}

    logger.info("[revise_node] 修订完成 %d 条", len(improved))
    return {"analyses": improved, "cost_tracker": tracker}
