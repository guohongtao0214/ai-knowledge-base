#!/usr/bin/env python3
"""知识条目 JSON 校验脚本。

支持单文件和多文件（含通配符）输入，校验 JSON 格式、必填字段、字段值合规性。
校验通过 exit 0，失败 exit 1 并输出错误详情和汇总统计。
"""
import glob as glob_mod
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = frozenset({"draft", "review", "published", "archived"})
VALID_AUDIENCES = frozenset({"beginner", "intermediate", "advanced"})
ID_PATTERN = re.compile(r"^[a-z]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")


def collect_files(paths: list[str]) -> list[Path]:
    """收集所有待校验的 JSON 文件路径（支持通配符和绝对/相对路径）。

    Args:
        paths: 命令行传入的文件路径列表，可含 glob 通配符。

    Returns:
        展开后的 Path 列表。
    """
    files: list[Path] = []
    for raw in paths:
        # 使用 glob 模块处理通配符，同时兼容绝对路径
        matched = sorted(Path(p) for p in glob_mod.glob(raw, recursive=True))
        if not matched:
            # 尝试作为直接文件路径
            p = Path(raw)
            if p.is_file():
                matched = [p]
            else:
                print(f"[WARNING] 未找到匹配文件: {raw}")
                continue
        for p in matched:
            if p.is_file():
                files.append(p)
    return files


def parse_json(filepath: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """解析 JSON 文件，返回数据和解析错误列表。

    Args:
        filepath: JSON 文件路径。

    Returns:
        (data, errors) 元组。解析失败时 data 为 None。
    """
    errors: list[str] = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError as e:
        return None, [f"无法读取文件: {e}"]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [f"JSON 解析失败: {e}"]
    if not isinstance(data, dict):
        return None, ["根元素必须是 JSON 对象（dict）"]
    return data, errors


def validate_required_fields(
    data: dict[str, Any], filepath: Path
) -> list[str]:
    """校验必填字段的存在性和类型。

    Args:
        data: 解析后的 JSON 数据。
        filepath: 文件路径（用于错误信息）。

    Returns:
        错误信息列表。
    """
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"缺少必填字段: {field}")
            continue
        actual = data[field]
        if not isinstance(actual, expected_type):
            actual_name = type(actual).__name__
            expected_name = expected_type.__name__
            errors.append(
                f"字段 '{field}' 类型错误: 期望 {expected_name}，实际 {actual_name}"
            )
    return errors


def validate_id_format(entry_id: str) -> list[str]:
    """校验 ID 格式是否为 {source}-{YYYYMMDD}-{NNN}。

    Args:
        entry_id: 条目 ID 字符串。

    Returns:
        错误信息列表。
    """
    errors: list[str] = []
    if not ID_PATTERN.match(entry_id):
        errors.append(
            f"ID 格式错误: '{entry_id}'，期望格式: {{source}}-{{YYYYMMDD}}-{{NNN}}"
            "（如 github-20260317-001）"
        )
    return errors


def validate_status(status: str) -> list[str]:
    """校验 status 是否为允许的枚举值。

    Args:
        status: 状态字符串。

    Returns:
        错误信息列表。
    """
    if status not in VALID_STATUSES:
        return [
            f"status 取值错误: '{status}'，允许值: {sorted(VALID_STATUSES)}"
        ]
    return []


def validate_url(url: str) -> list[str]:
    """校验 URL 格式。

    Args:
        url: URL 字符串。

    Returns:
        错误信息列表。
    """
    if not URL_PATTERN.match(url):
        return [f"source_url 格式无效: '{url}'"]
    return []


def validate_summary(summary: str) -> list[str]:
    """校验摘要是否满足最低字数要求。

    Args:
        summary: 摘要字符串。

    Returns:
        错误信息列表。
    """
    errors: list[str] = []
    text = summary.strip()
    if len(text) < 20:
        errors.append(f"summary 字数不足: 当前 {len(text)} 字，最少 20 字")
    return errors


def validate_tags(tags: list) -> list[str]:
    """校验标签列表是否非空。

    Args:
        tags: 标签列表。

    Returns:
        错误信息列表。
    """
    if len(tags) == 0:
        return ["tags 至少需要 1 个标签"]
    for i, tag in enumerate(tags):
        if not isinstance(tag, str):
            return [f"tags[{i}] 类型错误: 期望 str，实际 {type(tag).__name__}"]
    return []


def validate_optional_fields(data: dict[str, Any]) -> list[str]:
    """校验可选字段的值合规性（score、audience）。

    Args:
        data: 解析后的 JSON 数据。

    Returns:
        错误信息列表。
    """
    errors: list[str] = []
    if "score" in data:
        score = data["score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            errors.append(
                f"score 类型错误: 期望 int/float，实际 {type(score).__name__}"
            )
        elif not (1 <= score <= 10):
            errors.append(f"score 取值越界: {score}，允许范围 1-10")
    if "audience" in data:
        audience = data["audience"]
        if audience not in VALID_AUDIENCES:
            errors.append(
                f"audience 取值错误: '{audience}'，"
                f"允许值: {sorted(VALID_AUDIENCES)}"
            )
    return errors


def validate_file(filepath: Path) -> list[str]:
    """对单个 JSON 文件执行全部校验规则。

    Args:
        filepath: JSON 文件路径。

    Returns:
        错误信息列表，空列表表示校验通过。
    """
    errors: list[str] = []

    data, parse_errors = parse_json(filepath)
    if parse_errors:
        return [f"{e}" for e in parse_errors]

    errors.extend(validate_required_fields(data, filepath))
    if data is None:
        return errors

    entry_id = data.get("id")
    if isinstance(entry_id, str):
        errors.extend(validate_id_format(entry_id))

    status = data.get("status")
    if isinstance(status, str):
        errors.extend(validate_status(status))

    source_url = data.get("source_url")
    if isinstance(source_url, str):
        errors.extend(validate_url(source_url))

    summary = data.get("summary")
    if isinstance(summary, str):
        errors.extend(validate_summary(summary))

    tags = data.get("tags")
    if isinstance(tags, list):
        errors.extend(validate_tags(tags))

    errors.extend(validate_optional_fields(data))

    return errors


def main() -> int:
    """主入口。

    Returns:
        0 表示全部校验通过，1 表示存在错误。
    """
    if len(sys.argv) < 2:
        print("用法: python hooks/validate_json.py <json_file> [json_file2 ...]")
        print("支持通配符，如: python hooks/validate_json.py knowledge/articles/*.json")
        return 1

    files = collect_files(sys.argv[1:])
    if not files:
        print("未找到任何 JSON 文件")
        return 1

    print(f"校验文件数: {len(files)}")
    print("=" * 60)

    total_errors = 0
    passed_count = 0
    failed_count = 0

    for filepath in files:
        errors = validate_file(filepath)
        if errors:
            failed_count += 1
            total_errors += len(errors)
            print(f"\n[FAIL] {filepath}")
            for err in errors:
                print(f"  ✗ {err}")
        else:
            passed_count += 1
            print(f"[PASS] {filepath}")

    print("\n" + "=" * 60)
    print(f"汇总: 总计 {len(files)} 个文件 | "
          f"通过 {passed_count} | 失败 {failed_count} | 错误 {total_errors} 条")

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
