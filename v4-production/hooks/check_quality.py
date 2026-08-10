"""知识条目 5 维度质量评分脚本。

对 knowledge/articles/ 下的 JSON 条目进行质量评估，
输出每维度得分、加权总分和 A/B/C 等级。

Usage:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py knowledge/articles/*.json
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────────────

HOLLOW_WORDS_CN = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的", "革命性的",
]

HOLLOW_WORDS_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "next-generation", "disruptive", "paradigm-shifting", "best-in-class",
    "state-of-the-art", "unprecedented",
]

HOLLOW_PATTERN = re.compile(
    "|".join(re.escape(w) for w in HOLLOW_WORDS_CN + HOLLOW_WORDS_EN),
    re.IGNORECASE,
)

TECH_KEYWORDS = [
    "LLM", "GPT", "Claude", "DeepSeek", "Qwen", "transformer",
    "attention", "RAG", "fine-tune", "embedding", "vector",
    "agent", "tool call", "function call", "MoE", "quantization",
    "benchmark", "SWE-bench", "MMLU", "API", "SDK", "model",
    "training", "inference", "token", "context window",
]

STANDARD_TAGS = {
    "LLM", "Agent", "RAG", "Fine-tuning", "Embedding", "Transformer",
    "MoE", "Quantization", "Benchmark", "Code Generation", "NLP",
    "Computer Vision", "Multimodal", "Open Source", "API", "SDK",
    "DevOps", "MLOps", "Data Pipeline", "Security", "Performance",
}

VALID_STATUSES = {"draft", "review", "published", "archived"}

# ── 数据结构 ──────────────────────────────────────────────────────────


@dataclass
class DimensionScore:
    """单个维度的评分结果。

    Attributes:
        name: 维度名称。
        score: 实际得分。
        max_score: 满分。
        detail: 评分说明。
    """

    name: str
    score: float
    max_score: int
    detail: str = ""


@dataclass
class QualityReport:
    """单条知识条目的质量报告。

    Attributes:
        filepath: 来源文件路径。
        entry_id: 条目 ID。
        dimensions: 各维度评分列表。
        total_score: 加权总分。
        grade: 等级 (A/B/C)。
    """

    filepath: str
    entry_id: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    grade: str = "C"


# ── 评分函数 ──────────────────────────────────────────────────────────


def score_summary(entry: dict) -> DimensionScore:
    """摘要质量评分 (满分 25)。

    - >= 50 字: 20 分基础分
    - >= 20 字: 10 分基础分
    - < 20 字: 0 分
    - 每含一个技术关键词 +1 分（上限 5 分）
    """
    summary = entry.get("summary", "")
    length = len(summary.strip())

    if length >= 50:
        base = 20
    elif length >= 20:
        base = 10
    else:
        base = 0

    bonus = 0
    found_keywords: list[str] = []
    for kw in TECH_KEYWORDS:
        if kw.lower() in summary.lower():
            found_keywords.append(kw)
            bonus += 1
    bonus = min(bonus, 5)

    total = min(base + bonus, 25)
    detail = f"{length}字, 基础{base}分 + 关键词{bonus}分"
    if found_keywords:
        detail += f" ({', '.join(found_keywords[:3])})"

    return DimensionScore("摘要质量", total, 25, detail)


def score_depth(entry: dict) -> DimensionScore:
    """技术深度评分 (满分 25)。

    基于 score 字段 (1-10) 线性映射到 0-25。
    无 score 字段时给 12 分（中等）。
    """
    score = entry.get("score")

    if score is None:
        return DimensionScore("技术深度", 12, 25, "无 score 字段, 默认 12 分")

    if not isinstance(score, (int, float)):
        return DimensionScore("技术深度", 0, 25, f"score 类型错误: {type(score).__name__}")

    if not (1 <= score <= 10):
        return DimensionScore("技术深度", 0, 25, f"score 超出范围: {score}")

    mapped = round((score - 1) / 9 * 25, 1)
    return DimensionScore("技术深度", mapped, 25, f"score={score} → {mapped}分")


def score_format(entry: dict) -> DimensionScore:
    """格式规范评分 (满分 20)。

    id、title、source_url、status、时间戳 五项各 4 分。
    """
    points = 0
    details: list[str] = []

    # id: 非空字符串
    if isinstance(entry.get("id"), str) and entry["id"].strip():
        points += 4
        details.append("id ✓")
    else:
        details.append("id ")

    # title: 非空字符串
    if isinstance(entry.get("title"), str) and entry["title"].strip():
        points += 4
        details.append("title ✓")
    else:
        details.append("title ✗")

    # source_url: 以 http:// 或 https:// 开头
    url = entry.get("source_url", "")
    if isinstance(url, str) and re.match(r"^https?://", url):
        points += 4
        details.append("source_url ✓")
    else:
        details.append("source_url ✗")

    # status: 合法值
    status = entry.get("status", "")
    if isinstance(status, str) and status in VALID_STATUSES:
        points += 4
        details.append("status ✓")
    else:
        details.append("status ✗")

    # 时间戳: collected_at 或 analyzed_at 存在
    has_ts = (
        isinstance(entry.get("collected_at"), str)
        or isinstance(entry.get("analyzed_at"), str)
    )
    if has_ts:
        points += 4
        details.append("timestamp ✓")
    else:
        details.append("timestamp ✗")

    return DimensionScore("格式规范", points, 20, ", ".join(details))


def score_tags(entry: dict) -> DimensionScore:
    """标签精度评分 (满分 15)。

    - 1-3 个标签: 10 分基础分
    - 4-5 个标签: 7 分
    - > 5 个标签: 4 分
    - 0 个标签: 0 分
    - 每有一个标准标签 +1 分（上限 5 分）
    """
    tags = entry.get("tags", [])

    if not isinstance(tags, list):
        return DimensionScore("标签精度", 0, 15, f"tags 类型错误: {type(tags).__name__}")

    count = len(tags)

    if count == 0:
        base = 0
    elif count <= 3:
        base = 10
    elif count <= 5:
        base = 7
    else:
        base = 4

    bonus = 0
    matched: list[str] = []
    for tag in tags:
        if isinstance(tag, str) and tag in STANDARD_TAGS:
            matched.append(tag)
            bonus += 1
    bonus = min(bonus, 5)

    total = min(base + bonus, 15)
    detail = f"{count}个标签, 基础{base}分 + 标准标签{bonus}分"
    if matched:
        detail += f" ({', '.join(matched[:3])})"

    return DimensionScore("标签精度", total, 15, detail)


def score_hollow(entry: dict) -> DimensionScore:
    """空洞词检测评分 (满分 15)。

    不含任何空洞词: 15 分
    每含一个空洞词 -3 分，最低 0 分。
    """
    text = " ".join([
        str(entry.get("summary", "")),
        str(entry.get("title", "")),
    ])

    found = HOLLOW_PATTERN.findall(text)
    penalty = len(found) * 3
    total = max(15 - penalty, 0)

    if found:
        unique = list(set(w.lower() for w in found))
        detail = f"发现 {len(found)} 个空洞词: {', '.join(unique[:5])}"
    else:
        detail = "未检测到空洞词"

    return DimensionScore("空洞词检测", total, 15, detail)


# ── 报告生成 ──────────────────────────────────────────────────────────


def evaluate_entry(entry: dict, filepath: str) -> QualityReport:
    """对单条知识条目进行 5 维度评分。

    Args:
        entry: 解析后的 JSON 字典。
        filepath: 来源文件路径。

    Returns:
        QualityReport 质量报告。
    """
    dimensions = [
        score_summary(entry),
        score_depth(entry),
        score_format(entry),
        score_tags(entry),
        score_hollow(entry),
    ]

    total = sum(d.score for d in dimensions)

    if total >= 80:
        grade = "A"
    elif total >= 60:
        grade = "B"
    else:
        grade = "C"

    return QualityReport(
        filepath=filepath,
        entry_id=entry.get("id", "<unknown>"),
        dimensions=dimensions,
        total_score=total,
        grade=grade,
    )


# ── 可视化 ────────────────────────────────────────────────────────────


def render_bar(score: float, max_score: int, width: int = 20) -> str:
    """渲染文本进度条。

    Args:
        score: 实际得分。
        max_score: 满分。
        width: 进度条字符宽度。

    Returns:
        格式化的进度条字符串。
    """
    ratio = score / max_score if max_score > 0 else 0
    filled = int(ratio * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {score:.1f}/{max_score}"


def print_report(report: QualityReport) -> None:
    """打印单条知识条目的质量报告。

    Args:
        report: QualityReport 质量报告。
    """
    grade_symbol = {"A": "🅐", "B": "🅑", "C": ""}
    symbol = grade_symbol.get(report.grade, report.grade)

    print(f"\n{'─' * 56}")
    print(f"  {symbol} {report.entry_id}  ({report.filepath})")
    print(f"{'─' * 56}")

    for dim in report.dimensions:
        bar = render_bar(dim.score, dim.max_score)
        print(f"  {dim.name:<8s} {bar}  {dim.detail}")

    print(f"{'─' * 56}")
    total_bar = render_bar(report.total_score, 100, 24)
    print(f"  {'总分':<8s} {total_bar}  等级: {report.grade}")


def print_summary(reports: list[QualityReport]) -> None:
    """打印汇总统计。

    Args:
        reports: 所有质量报告列表。
    """
    if not reports:
        print("\n无有效条目可评估。")
        return

    total = len(reports)
    grade_a = sum(1 for r in reports if r.grade == "A")
    grade_b = sum(1 for r in reports if r.grade == "B")
    grade_c = sum(1 for r in reports if r.grade == "C")
    avg_score = sum(r.total_score for r in reports) / total

    print(f"\n{'═' * 56}")
    print(f"  汇总统计")
    print(f"{'═' * 56}")
    print(f"  条目总数: {total}")
    print(f"  平均分:   {avg_score:.1f}")
    print(f"  等级分布: A={grade_a}  B={grade_b}  C={grade_c}")

    has_c = any(r.grade == "C" for r in reports)
    if has_c:
        print(f"\n  ⚠ 存在 C 级条目，请改进后重新评估。")
    else:
        print(f"\n  ✓ 所有条目质量达标。")
    print(f"{'═' * 56}")


# ── 主入口 ────────────────────────────────────────────────────────────


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="知识条目 5 维度质量评分"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="JSON 文件路径，支持通配符 *.json",
    )
    args = parser.parse_args()

    reports: list[QualityReport] = []

    for pattern in args.files:
        paths = sorted(Path.cwd().glob(pattern)) if "*" in pattern else [Path(pattern)]

        if not paths:
            print(f"未匹配到文件: {pattern}", file=sys.stderr)
            continue

        for filepath in paths:
            if not filepath.is_file():
                print(f"文件不存在: {filepath}", file=sys.stderr)
                continue

            try:
                content = filepath.read_text(encoding="utf-8")
                data = json.loads(content)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[{filepath}] 读取/解析失败: {exc}", file=sys.stderr)
                continue

            entries: list[dict]
            if isinstance(data, dict):
                entries = [data]
            elif isinstance(data, list):
                entries = data
            else:
                print(f"[{filepath}] JSON 根节点应为 object 或 array", file=sys.stderr)
                continue

            for entry in entries:
                if isinstance(entry, dict):
                    report = evaluate_entry(entry, str(filepath))
                    reports.append(report)
                    print_report(report)

    print_summary(reports)

    has_c = any(r.grade == "C" for r in reports)
    sys.exit(1 if has_c else 0)


if __name__ == "__main__":
    main()
