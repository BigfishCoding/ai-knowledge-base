"""校验知识条目 JSON 文件的合法性。

支持单文件和多文件（通配符 *.json）输入，检查字段存在性、类型、
ID 格式、URL 格式、摘要长度、标签数量等。

Usage:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py knowledge/articles/*.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCE = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-z]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://.+")


def validate_entry(entry: dict, filepath: str) -> list[str]:
    """校验单条知识条目，返回错误信息列表。

    Args:
        entry: 解析后的 JSON 字典。
        filepath: 来源文件路径，用于错误提示。

    Returns:
        错误信息字符串列表，空列表表示校验通过。
    """
    errors: list[str] = []
    prefix = f"[{filepath}]"

    # 1. 必填字段存在性与类型检查
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            errors.append(f"{prefix} 缺少必填字段: {field}")
        elif not isinstance(entry[field], expected_type):
            errors.append(
                f"{prefix} 字段 '{field}' 类型错误: "
                f"期望 {expected_type.__name__}, "
                f"实际 {type(entry[field]).__name__}"
            )

    # 2. ID 格式检查
    if "id" in entry and isinstance(entry["id"], str):
        if not ID_PATTERN.match(entry["id"]):
            errors.append(
                f"{prefix} ID 格式错误: '{entry['id']}', "
                f"期望格式 {{source}}-YYYYMMDD-NNN (如 github-20260317-001)"
            )

    # 3. status 值域检查
    if "status" in entry and isinstance(entry["status"], str):
        if entry["status"] not in VALID_STATUSES:
            errors.append(
                f"{prefix} status 值无效: '{entry['status']}', "
                f"允许值: {', '.join(sorted(VALID_STATUSES))}"
            )

    # 4. URL 格式检查
    if "source_url" in entry and isinstance(entry["source_url"], str):
        if not URL_PATTERN.match(entry["source_url"]):
            errors.append(
                f"{prefix} source_url 格式错误: '{entry['source_url']}', "
                f"期望以 http:// 或 https:// 开头"
            )

    # 5. 摘要最少 20 字
    if "summary" in entry and isinstance(entry["summary"], str):
        if len(entry["summary"].strip()) < 20:
            errors.append(
                f"{prefix} 摘要过短: 当前 {len(entry['summary'].strip())} 字, "
                f"最少 20 字"
            )

    # 6. 标签至少 1 个
    if "tags" in entry and isinstance(entry["tags"], list):
        if len(entry["tags"]) < 1:
            errors.append(f"{prefix} 标签为空, 至少需要 1 个标签")

    # 7. score 可选字段检查 (1-10)
    if "score" in entry:
        score = entry["score"]
        if not isinstance(score, (int, float)):
            errors.append(
                f"{prefix} score 类型错误: "
                f"期望 int/float, 实际 {type(score).__name__}"
            )
        elif not (1 <= score <= 10):
            errors.append(
                f"{prefix} score 超出范围: {score}, 应在 1-10 之间"
            )

    # 8. audience 可选字段检查
    if "audience" in entry:
        audience = entry["audience"]
        if not isinstance(audience, str):
            errors.append(
                f"{prefix} audience 类型错误: "
                f"期望 str, 实际 {type(audience).__name__}"
            )
        elif audience not in VALID_AUDIENCE:
            errors.append(
                f"{prefix} audience 值无效: '{audience}', "
                f"允许值: {', '.join(sorted(VALID_AUDIENCE))}"
            )

    return errors


def validate_file(filepath: Path) -> tuple[int, list[str]]:
    """校验单个 JSON 文件，返回 (条目数, 错误列表)。

    Args:
        filepath: JSON 文件路径。

    Returns:
        (条目数量, 错误信息列表) 的元组。
    """
    errors: list[str] = []
    count = 0

    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        return 0, [f"[{filepath}] 无法读取文件: {exc}"]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return 0, [f"[{filepath}] JSON 解析失败: {exc}"]

    # 支持单条 dict 或多条 list
    entries: list[dict]
    if isinstance(data, dict):
        entries = [data]
    elif isinstance(data, list):
        entries = data
    else:
        return 0, [f"[{filepath}] JSON 根节点应为 object 或 array"]

    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"[{filepath}] 条目不是 JSON 对象")
            continue
        count += 1
        errors.extend(validate_entry(entry, str(filepath)))

    return count, errors


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="校验知识条目 JSON 文件的合法性"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="JSON 文件路径，支持通配符 *.json",
    )
    args = parser.parse_args()

    all_errors: list[str] = []
    total_files = 0
    total_entries = 0

    for pattern in args.files:
        paths = sorted(Path.cwd().glob(pattern)) if "*" in pattern else [Path(pattern)]

        if not paths:
            all_errors.append(f"未匹配到文件: {pattern}")
            continue

        for filepath in paths:
            if not filepath.is_file():
                all_errors.append(f"文件不存在: {filepath}")
                continue

            total_files += 1
            count, errors = validate_file(filepath)
            total_entries += count
            all_errors.extend(errors)

    # 输出结果
    if all_errors:
        print(f"校验失败，共 {len(all_errors)} 个错误：\n")
        for error in all_errors:
            print(f"   {error}")
        print(
            f"\n汇总: {total_files} 个文件, "
            f"{total_entries} 条记录, "
            f"{len(all_errors)} 个错误"
        )
        sys.exit(1)
    else:
        print(
            f"校验通过 ✓  "
            f"({total_files} 个文件, {total_entries} 条记录)"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
