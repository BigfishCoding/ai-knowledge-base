"""多 Agent 预算守卫（CostGuard）。

为 LangGraph 多 Agent 流水线提供三层成本保护：

1. ``record()``: 记录每次 LLM 调用的 token 用量并折算成本
2. ``check()``: 基于预算与预警阈值判定 ``ok`` / ``warning`` / ``exceeded``，
   超出预算时抛出 :class:`BudgetExceededError`
3. ``get_report()`` / ``save_report()``: 按节点分组的成本报告与 JSON 落盘

计价模型默认按 DeepSeek 官方价格（输入 ¥1.0 / 百万 token，输出 ¥2.0 /
百万 token），可在构造函数中按需覆盖。
"""

import json
import logging
import math
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

TOKENS_PER_MILLION = 1_000_000
DEFAULT_BUDGET_YUAN = 1.0
DEFAULT_ALERT_THRESHOLD = 0.8
DEFAULT_INPUT_PRICE = 1.0
DEFAULT_OUTPUT_PRICE = 2.0

# 状态枚举（check() 返回值的 status 字段）
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_EXCEEDED = "exceeded"

# 项目根目录：tests/cost_guard.py 向上两级
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "knowledge" / "reports"


# ── 数据类与异常 ──────────────────────────────────────────────────────────


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录。

    Attributes:
        timestamp: 调用发生时间（UTC ISO 8601）。
        node_name: 发起调用的节点名（如 ``analyze``）。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        cost_yuan: 折算成本（元）。
        model: 使用的模型名，默认空串。
    """

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class BudgetExceededError(RuntimeError):
    """累计成本超出预算时抛出的异常。"""


# ── 预算守卫 ──────────────────────────────────────────────────────────────


class CostGuard:
    """多 Agent 预算守卫：记录用量、判定预算状态、生成报告。

    Args:
        budget_yuan: 总预算（元），必须为正数。
        alert_threshold: 预警阈值（0,1]，成本达到预算该比例时进入
            ``warning`` 状态。
        input_price_per_million: 输入价格（元 / 百万 token）。
        output_price_per_million: 输出价格（元 / 百万 token）。

    Raises:
        ValueError: 当 ``budget_yuan`` 非正或 ``alert_threshold`` 不在
            (0, 1] 区间时抛出。
    """

    def __init__(
        self,
        budget_yuan: float = DEFAULT_BUDGET_YUAN,
        alert_threshold: float = DEFAULT_ALERT_THRESHOLD,
        input_price_per_million: float = DEFAULT_INPUT_PRICE,
        output_price_per_million: float = DEFAULT_OUTPUT_PRICE,
    ) -> None:
        if budget_yuan <= 0:
            raise ValueError(f"budget_yuan 必须为正数, 实际为 {budget_yuan}")
        if not 0 < alert_threshold <= 1:
            raise ValueError(
                f"alert_threshold 必须在 (0, 1] 区间, 实际为 {alert_threshold}"
            )
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.records: list[CostRecord] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_yuan: float = 0.0

    def record(
        self, node_name: str, usage: dict[str, Any], model: str = ""
    ) -> None:
        """记录一次 LLM 调用的 token 用量并折算成本。

        Args:
            node_name: 发起调用的节点名。
            usage: token 用量字典，含 ``prompt_tokens`` / ``completion_tokens``
                整数字段，缺失按 0 处理。
            model: 使用的模型名，默认空串。
        """
        prompt_tokens = max(0, int(usage.get("prompt_tokens", 0)))
        completion_tokens = max(0, int(usage.get("completion_tokens", 0)))
        cost_yuan = (
            prompt_tokens / TOKENS_PER_MILLION * self.input_price_per_million
            + completion_tokens / TOKENS_PER_MILLION * self.output_price_per_million
        )

        self.records.append(
            CostRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                node_name=node_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_yuan=cost_yuan,
                model=model,
            )
        )
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost_yuan += cost_yuan

        logger.debug(
            "[cost_guard] 记录调用 node=%s model=%s cost=%.6f 元, 累计=%.6f 元",
            node_name,
            model or "unknown",
            cost_yuan,
            self.total_cost_yuan,
        )

    def check(self) -> dict[str, Any]:
        """检查预算状态，返回状态字典；超出预算时抛出异常。

        Returns:
            状态字典：``status`` 为 ``ok`` / ``warning`` 之一，
            ``total_cost`` / ``budget`` / ``usage_ratio`` / ``message``
            补充数值与说明。

        Raises:
            BudgetExceededError: 当累计成本超过预算时抛出。
        """
        ratio = self.total_cost_yuan / self.budget_yuan
        if self.total_cost_yuan > self.budget_yuan:
            message = (
                f"累计成本 ¥{self.total_cost_yuan:.4f} 已超出预算 "
                f"¥{self.budget_yuan:.4f}"
            )
            logger.error("[cost_guard] %s", message)
            raise BudgetExceededError(message)
        if ratio >= self.alert_threshold:
            message = (
                f"累计成本 ¥{self.total_cost_yuan:.4f} 已达预算的 "
                f"{ratio:.1%}，请关注"
            )
            status = STATUS_WARNING
        else:
            message = (
                f"累计成本 ¥{self.total_cost_yuan:.4f}，占预算 "
                f"{ratio:.1%}，运行正常"
            )
            status = STATUS_OK
        return {
            "status": status,
            "total_cost": self.total_cost_yuan,
            "budget": self.budget_yuan,
            "usage_ratio": ratio,
            "message": message,
        }

    def get_report(self) -> dict[str, Any]:
        """生成按节点分组的成本报告。

        Returns:
            报告字典：总览（``total_calls`` / token 总量 / ``total_cost_yuan``
            / ``usage_ratio`` / ``budget_yuan`` / ``alert_threshold``）与
            ``nodes`` 分组统计（``llm_calls`` / ``prompt_tokens`` /
            ``completion_tokens`` / ``cost_yuan``）。
        """
        node_stats: dict[str, dict[str, Any]] = {}
        for record in self.records:
            stats = node_stats.setdefault(
                record.node_name,
                {
                    "llm_calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_yuan": 0.0,
                },
            )
            stats["llm_calls"] += 1
            stats["prompt_tokens"] += record.prompt_tokens
            stats["completion_tokens"] += record.completion_tokens
            stats["cost_yuan"] += record.cost_yuan

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "budget_yuan": self.budget_yuan,
            "alert_threshold": self.alert_threshold,
            "usage_ratio": (
                self.total_cost_yuan / self.budget_yuan if self.budget_yuan > 0 else 0.0
            ),
            "total_calls": len(self.records),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost_yuan": self.total_cost_yuan,
            "nodes": node_stats,
        }

    def save_report(self, path: str | Path | None = None) -> Path:
        """将成本报告保存为 JSON 文件。

        Args:
            path: 保存路径；None 时默认写入
                ``knowledge/reports/cost_report-{时间戳}.json``。

        Returns:
            实际写入的文件路径。
        """
        if path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
            path = REPORT_DIR / f"cost_report-{timestamp}.json"
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.get_report(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[cost_guard] 成本报告已保存到 %s", target)
        return target


# ── 自检 ──────────────────────────────────────────────────────────────────


def _run_self_check() -> None:
    """执行三项核心行为验证：追踪正确性、预警触发、超限检测。"""
    guard = CostGuard(budget_yuan=1.0, alert_threshold=0.8)

    # 1) 成本追踪正确性：输入 40 万 + 输出 10 万 token
    #    成本 = 0.4 * 1.0 + 0.1 * 2.0 = 0.6 元
    guard.record(
        "analyze",
        {"prompt_tokens": 400_000, "completion_tokens": 100_000},
        model="deepseek-chat",
    )
    assert guard.total_prompt_tokens == 400_000
    assert guard.total_completion_tokens == 100_000
    assert math.isclose(guard.total_cost_yuan, 0.6)
    assert len(guard.records) == 1
    assert guard.records[0].node_name == "analyze"
    print(
        f"[1] 成本追踪正确: prompt={guard.total_prompt_tokens} "
        f"completion={guard.total_completion_tokens} "
        f"cost={guard.total_cost_yuan:.4f} 元"
    )

    # 2) 预警阈值触发：再加 0.2 元（输入 10 万 + 输出 5 万）累计 0.8 元 = 预算 80%
    guard.record("review", {"prompt_tokens": 100_000, "completion_tokens": 50_000})
    status = guard.check()
    assert status["status"] == STATUS_WARNING
    assert math.isclose(status["usage_ratio"], 0.8)
    print(
        f"[2] 预警阈值触发: status={status['status']} "
        f"usage_ratio={status['usage_ratio']:.2f} {status['message']}"
    )

    # 3) 预算超限检测：再加 0.3 元（输入 10 万 + 输出 10 万）累计 1.1 元 > 1.0 元
    guard.record("revise", {"prompt_tokens": 100_000, "completion_tokens": 100_000})
    try:
        guard.check()
    except BudgetExceededError as exc:
        print(f"[3] 预算超限检测: 抛出 BudgetExceededError - {exc}")
    else:
        raise AssertionError("应抛出 BudgetExceededError 但未抛出")

    # 4) 分组报告与 JSON 落盘
    report = guard.get_report()
    assert set(report["nodes"].keys()) == {"analyze", "review", "revise"}
    assert report["nodes"]["analyze"]["llm_calls"] == 1
    assert report["total_calls"] == 3
    tmp_dir = Path(tempfile.mkdtemp())
    saved = guard.save_report(tmp_dir / "cost_report.json")
    assert saved.exists()
    persisted = json.loads(saved.read_text(encoding="utf-8"))
    assert persisted["total_cost_yuan"] == report["total_cost_yuan"]
    print(
        f"[4] 分组报告与落盘: nodes={sorted(report['nodes'])} "
        f"total_cost={report['total_cost_yuan']:.4f} 元 -> {saved}"
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _run_self_check()
