"""pipeline/pipeline.py — V4 一次完整执行入口（被 cron 触发）"""

import logging
import sys
from pathlib import Path

from workflows.graph import app as v3_workflow      # V3 LangGraph 核心
from distribution.publisher import publish_daily_digest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def run_once() -> int:
    """跑一次完整流水线：V3 工作流采集分析 → 分发推送。返回退出码。"""
    log.info("=== V4 pipeline 启动 ===")

    # 1. V3 LangGraph：采集 + 分析 + 审核 + 入库
    initial_state = {
        "sources": [], "analyses": [], "articles": [],
        "review_feedback": "", "review_passed": False,
        "iteration": 0, "needs_human_review": False,
        "plan": {}, "cost_tracker": {},
    }
    final_state = v3_workflow.invoke(initial_state)
    log.info(f"V3 完成：{len(final_state.get('articles', []))} 条新条目")

    # 2. 分发（异步推送到 Telegram / 飞书）
    import asyncio
    results = asyncio.run(publish_daily_digest())
    for r in results:
        log.info(f"  {r.channel}: {'✓' if r.success else '✗'} {r.message_id or r.error}")

    return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    sys.exit(run_once())