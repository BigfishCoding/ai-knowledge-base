"""Supervisor 监督模式实现。

两个 Agent 协作完成一个分析任务：

1. **Worker Agent**：接收任务，产出 JSON 格式的分析报告
2. **Supervisor Agent**：对 Worker 输出做三种评分（准确性/深度/格式，各 1-10），
   输出 ``{"passed": bool, "score": int, "feedback": str}``

审核循环：

- 通过（score >= 7）→ 返回一份合格报告
- 不通过 → 携带 feedback 让 Worker 重做（最多 ``max_retries`` 轮）
- 超出轮次 → 强制返回最后一次结果，并附带 warning

统一入口：
    supervisor(task, max_retries=3) -> dict

用法:
    python patterns/supervisor.py
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

# 项目根目录注入 sys.path，保证以 `python patterns/supervisor.py` 方式运行时可导入 workflows 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.model_client import chat

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

SCORE_PASS_THRESHOLD = 7
DEFAULT_MAX_RETRIES = 3
JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$")


# ── 提示词构建 ────────────────────────────────────────────────────────────


def build_worker_prompt(task: str, feedback: str = "") -> str:
    """构建 Worker 的任务提示词。

    Args:
        task: 用户原始任务描述。
        feedback: 上一轮 Supervisor 的反馈；非空时要求 Worker 据此改进。

    Returns:
        发送给模型的任务提示词。
    """
    revision = (
        f"\nSupervisor 上一轮反馈，请据此改进后再输出：\n{feedback}"
        if feedback
        else ""
    )
    return (
        "你是一个分析 Worker Agent。请严格完成以下任务，"
        f"并以合法 JSON 对象返回分析报告。\n任务描述：{task}{revision}"
    )


def build_supervisor_prompt(task: str, output: dict[str, Any]) -> str:
    """构建 Supervisor 的审核提示词。

    Args:
        task: 原始任务描述。
        output: Worker 产出的分析报告。

    Returns:
        给模型审核使用的提示词。
    """
    return (
        "你是一个审核 Supervisor Agent。请对 Worker 的分析报告进行评审，"
        "从准确性、深度、格式三个维度各打 1-10 分，"
        "并以合法 JSON 返回，格式为 "
        '{"passed": bool, "score": int, "feedback": str}，'
        f"score >= {SCORE_PASS_THRESHOLD} 时 passed 为 true。\n"
        f"原始任务：{task}\nWorker 输出：{json.dumps(output, ensure_ascii=False)}"
    )


# ── LLM 调用与解析 ────────────────────────────────────────────────────────


def _parse_json(text: str) -> dict[str, Any]:
    """从模型文本中提取并解析 JSON 对象。

    Args:
        text: 模型返回的原始文本。

    Returns:
        解析出的字典。

    Raises:
        ValueError: 文本中无法解析出 JSON 对象时抛出。
    """
    cleaned = JSON_FENCE_PATTERN.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("无法解析模型 JSON 输出: %s", text)
        raise ValueError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON 根节点应为 object, 实际为 {type(data).__name__}")
    return data


def run_worker(task: str, feedback: str = "") -> dict[str, Any]:
    """运行 Worker Agent：让模型完成任务并解析为 JSON。

    Args:
        task: 原始任务描述。
        feedback: 上一轮反馈，非空时携带要求改进。

    Returns:
        Worker 产出的分析报告字典。

    Raises:
        RuntimeError: LLM 调用失败时抛出。
        ValueError: 输出无法解析为 JSON 时抛出。
    """
    prompt = build_worker_prompt(task, feedback)
    text, _ = chat(prompt)
    return _parse_json(text)


def run_supervisor(task: str, output: dict[str, Any]) -> dict[str, Any]:
    """运行 Supervisor 审核，输出 pass/score/feedback。

    Args:
        task: 原始任务描述。
        output: Worker 产出的分析报告。

    Returns:
        包含 passed / score / feedback 的审核结果字典。

    Raises:
        RuntimeError: LLM 调用失败时抛出。
        ValueError: 审核结果无法解析或字段缺失时抛出。
    """
    prompt = build_supervisor_prompt(task, output)
    text, _ = chat(prompt)
    verdict = _parse_json(text)

    if not isinstance(verdict.get("passed"), bool) or not isinstance(
        verdict.get("score"), int
    ):
        raise ValueError(f"Supervisor 返回字段缺失: {text}")

    return {
        "passed": verdict["passed"],
        "score": verdict["score"],
        "feedback": str(verdict.get("feedback") or ""),
    }


# ── 统一入口 ──────────────────────────────────────────────────────────────


def supervisor(task: str, max_retries: int = DEFAULT_MAX_RETRIES) -> dict[str, Any]:
    """Supervisor 监督模式主流程：Worker 产出 + Supervisor 审核循环。

    循环策略：每次让 Worker 产出 → Supervisor 审核。
    通过即返回；未通过则携带 feedback 重做；超过 max_retries 轮仍
    未通过时强制返回最后一次结果并附加 warning。

    Args:
        task: 要分析的原始任务描述。
        max_retries: 最大重做轮数；默认 3。

    Returns:
        包含以下键的字典：
        - ``output``: 最终 Worker 报告（最后一轮或通过轮的结果）
        - ``attempts``: 实际执行的审核轮数（含首轮）
        - ``final_score``: 最终轮评分；LLM 完全失败时为 None
        - ``warning``: 可选；多轮未通过或 LLM 失败时的告警文本
    """
    output: dict[str, Any] = {}
    final_score: int | None = None
    feedback = ""
    warning = None

    for attempt in range(1, max_retries + 2):  # 首轮 + max_retries 次重做
        try:
            output = run_worker(task, feedback)
            verdict = run_supervisor(task, output)
        except (RuntimeError, ValueError) as exc:
            logger.error("第 %d 轮执行失败: %s", attempt, exc)
            warning = f"执行失败：{exc}"
            break

        final_score = verdict["score"]
        if verdict["passed"] and final_score >= SCORE_PASS_THRESHOLD:
            logger.info("第 %d 轮通过, score=%s", attempt, final_score)
            break

        logger.info(
            "第 %d 轮未通过, score=%s: %s", attempt, final_score, verdict["feedback"]
        )
        if attempt > max_retries:
            warning = f"超过最大重做轮数（{max_retries}），强制返回最后结果"
            break
        feedback = verdict["feedback"]

    return {
        "output": output,
        "attempts": attempt,
        "final_score": final_score,
        "warning": warning,
    }


# ── 测试入口 ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    test_task = (
        "分析 DeepSeek-V3.2 的 MoE 架构特点，输出 JSON："
        '{"title": str, "key_points": list[str], "summary": str}'
    )

    result = supervisor(test_task)
    print("=" * 60)
    print("Supervisor 执行结果")
    print("-" * 60)
    print(f"attempts: {result['attempts']}")
    print(f"final_score: {result['final_score']}")
    if result["warning"]:
        print(f"warning: {result['warning']}")
    print("output:")
    print(json.dumps(result["output"], ensure_ascii=False, indent=2))
