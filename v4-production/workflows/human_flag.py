"""HumanFlag Agent — 人工介入节点（异常终点）。

当审核循环超过上限时，将待审核数据写入 ``knowledge/pending_review/`` 目录，
供人工后续处理。
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workflows.state import KBState

logger = logging.getLogger(__name__)

# 项目根目录：workflows/human_flag.py 向上两级
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PENDING_DIR = PROJECT_ROOT / "knowledge" / "pending_review"


def human_flag_node(state: KBState) -> dict[str, Any]:
    """审核循环超过上限时的兜底节点，写入 pending_review/ 目录。

    Args:
        state: 当前全局状态，包含 analyses、iteration、review_feedback 等字段。

    Returns:
        ``{"needs_human_review": True}``，标记需要人工介入。
    """
    analyses = state["analyses"]
    iteration = state["iteration"]
    feedback = state["review_feedback"]

    logger.warning(
        "[human_flag_node] 达到 %d 次审核仍未通过, 最后反馈: %s",
        iteration,
        feedback[:200],
    )

    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    filepath = PENDING_DIR / f"pending-{timestamp}.json"
    filepath.write_text(
        json.dumps(
            {
                "timestamp": timestamp,
                "iterations_used": iteration,
                "last_feedback": feedback,
                "analyses": analyses,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info("[human_flag_node] 已保存到 %s", filepath)
    return {"needs_human_review": True}
