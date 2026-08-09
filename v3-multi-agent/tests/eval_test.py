"""Eval 评估测试 — AI 知识库质量验证。

核心原则：
- 不测精确内容，测行为边界：用 ``>=`` / ``<=`` / ``in`` 代替 ``==``
- 正面 + 负面 + 边界 = 最小 Eval 集
- LLM-as-Judge 对分析质量做 1-10 分量化评分

本地结构验证不消耗 token；LLM 测试标记 ``slow``，可通过
``-m "not slow"`` 选择性跳过。
"""

import os
import re
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

# 项目根目录：tests/eval_test.py 向上两级
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env，让 pytest 能读到 LLM_API_KEY
load_dotenv(PROJECT_ROOT / ".env")

# 屏蔽自定义 slow 标记触发的 PytestUnknownMarkWarning
warnings.filterwarnings("ignore", category=pytest.PytestUnknownMarkWarning)

from workflows.model_client import chat

# ── 常量 ──────────────────────────────────────────────────────────────────

ANALYZE_SYSTEM = "你是技术分析师。"
FILTER_SYSTEM = "你是技术内容筛选器。"
JUDGE_SYSTEM = "你只输出一个 1-10 之间的整数评分，不输出其他任何内容。"

ANALYZE_PROMPT = "请分析以下技术内容，输出 200 字以内的中文摘要：\n{text}"
FILTER_PROMPT = (
    "请判断以下内容是否与 AI 技术相关。若无关，请明确指出“不相关”：\n{text}"
)
JUDGE_PROMPT = """请对以下技术分析的质量打分（1-10分）。

分析内容：
{analysis}

评分标准：
- 准确性：信息是否正确
- 深度：是否有洞察
- 实用性：读者能否据此行动

只返回一个整数（1-10），不要解释。"""

IRRELEVANT_KEYWORDS = ("不相关", "无关", "与 AI 无关")

# LLM 测试在未配置 API Key 时整体跳过，避免 CI 硬失败
NEEDS_LLM = pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"),
    reason="LLM_API_KEY 未配置，跳过 LLM 评估用例",
)


# ── 评估用例定义 ──────────────────────────────────────────────────────────


EVAL_CASES: list[dict[str, Any]] = [
    {
        "name": "正面案例 — 技术项目分析",
        "mode": "analyze",
        "input": "LangGraph 是一个基于有向图的多 Agent 工作流编排框架，支持条件分支和循环。",
        "expected": {
            "min_length": 50,
            "max_length": 1000,
            "must_contain_any": ["LangGraph", "工作流", "Agent", "图"],
        },
    },
    {
        "name": "正面案例 — 英文技术内容",
        "mode": "analyze",
        "input": "OpenAI released GPT-5 with 1M token context window and native tool use.",
        "expected": {
            "min_length": 30,
            "max_length": 1000,
            "must_contain_any": ["GPT-5", "OpenAI", "token", "context"],
        },
    },
    {
        "name": "负面案例 — 无关内容",
        "mode": "filter",
        "input": "今天天气真好，适合出去野餐，带上三明治和果汁。",
        "expected": {
            "max_length": 500,
            "should_mention_irrelevant": True,
        },
    },
    {
        "name": "边界案例 — 极短输入",
        "mode": "analyze",
        "input": "AI",
        "expected": {
            "min_length": 1,
            "max_length": 2000,
            "no_crash": True,
        },
    },
]


# ── 本地验证（不调 LLM）───────────────────────────────────────────────────


def test_eval_cases_structure() -> None:
    """验证 EVAL_CASES 结构完整性（不消耗 token）。"""
    assert len(EVAL_CASES) >= 3, "至少需要 3 个评估用例"

    names = [case["name"] for case in EVAL_CASES]
    assert any("正面" in name for name in names), "缺少正面案例"
    assert any("负面" in name for name in names), "缺少负面案例"
    assert any("边界" in name for name in names), "缺少边界案例"

    for case in EVAL_CASES:
        assert "name" in case, "用例缺少 name 字段"
        assert "input" in case, f"用例 {case.get('name')} 缺少 input"
        assert "expected" in case, f"用例 {case.get('name')} 缺少 expected"
        assert "mode" in case, f"用例 {case.get('name')} 缺少 mode"


# ── LLM 评估辅助 ──────────────────────────────────────────────────────────


def _build_prompt(case: dict[str, Any]) -> tuple[str, str]:
    """根据用例模式构建提示词与系统角色。

    Args:
        case: 单个评估用例（含 ``mode`` / ``input``）。

    Returns:
        ``(prompt, system)`` 元组，供 ``chat()`` 使用。
    """
    if case["mode"] == "filter":
        return FILTER_PROMPT.format(text=case["input"]), FILTER_SYSTEM
    return ANALYZE_PROMPT.format(text=case["input"]), ANALYZE_SYSTEM


def _assert_expected(case: dict[str, Any], result: str) -> None:
    """对 LLM 输出应用范围断言（>=, <=, in），不测精确内容。

    Args:
        case: 单个评估用例。
        result: LLM 返回的分析结果文本。

    Raises:
        AssertionError: 任一范围条件不满足时抛出。
    """
    expected = case["expected"]

    if "min_length" in expected:
        assert len(result) >= expected["min_length"], (
            f"输出太短: {len(result)} < {expected['min_length']}"
        )
    if "max_length" in expected:
        assert len(result) <= expected["max_length"], (
            f"输出太长: {len(result)} > {expected['max_length']}"
        )
    if "must_contain_any" in expected:
        found = any(keyword in result for keyword in expected["must_contain_any"])
        assert found, (
            f"输出应包含以下关键词之一: {expected['must_contain_any']}"
        )
    if expected.get("should_mention_irrelevant"):
        found = any(keyword in result for keyword in IRRELEVANT_KEYWORDS)
        assert found, f"无关内容应被识别为低相关: {IRRELEVANT_KEYWORDS}"
    if expected.get("no_crash"):
        assert isinstance(result, str) and len(result) > 0, "边界输入不应产生空输出"


# ── LLM 评估测试（消耗 token）────────────────────────────────────────────


@NEEDS_LLM
@pytest.mark.slow
@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
def test_eval_case(case: dict[str, Any]) -> None:
    """对每个评估用例执行行为边界断言。

    Args:
        case: 单个评估用例。
    """
    prompt, system = _build_prompt(case)
    try:
        result, _usage = chat(prompt, system=system)
    except Exception as exc:
        pytest.fail(f"LLM 调用失败: {exc}")

    _assert_expected(case, result)


@NEEDS_LLM
@pytest.mark.slow
def test_llm_as_judge() -> None:
    """LLM-as-Judge：让 LLM 对分析结果打分并断言 >= 5。"""
    analysis, _usage = chat(
        "请分析 LangGraph 框架的核心优势和适用场景",
        system=ANALYZE_SYSTEM,
    )

    judge_text, _usage = chat(
        JUDGE_PROMPT.format(analysis=analysis),
        system=JUDGE_SYSTEM,
        temperature=0.0,
    )

    match = re.search(r"\d+", judge_text.strip())
    assert match is not None, f"评审未返回数字评分，实际输出: {judge_text!r}"
    score = int(match.group())

    assert 1 <= score <= 10, f"评分应在 1-10 范围内，实际: {score}"
    assert score >= 5, f"分析质量评分过低: {score}/10"


# ── 运行入口 ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=== 本地验证（不消耗 token）===")
    test_eval_cases_structure()
    print(f"[OK] EVAL_CASES 结构验证通过，共 {len(EVAL_CASES)} 个用例")
    for case in EVAL_CASES:
        print(f"  - {case['name']}")

    print("\n提示：运行 LLM 测试请使用:")
    print("  pytest tests/eval_test.py -m slow -v")
