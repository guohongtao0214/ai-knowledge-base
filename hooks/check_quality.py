#!/usr/bin/env python3
"""知识条目 5 维度质量评分脚本。

对知识库 JSON 文件从摘要质量、技术深度、格式规范、标签精度、
空洞词检测五个维度进行评分，输出可视化报告。
"""
import glob as glob_mod
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 空洞词黑名单
# ---------------------------------------------------------------------------
CHINESE_BUZZWORDS: list[str] = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的", "革命性的",
]

ENGLISH_BUZZWORDS: list[str] = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "best-in-class", "world-class", "next-generation", "disruptive",
    "unprecedented", "paradigm-shifting", "state-of-the-art",
    "bleeding-edge", "best-of-breed",
]

# 标准标签（合法的标签白名单）
VALID_TAGS: set[str] = {
    # 技术领域
    "LLM", "Agent", "RAG", "Multimodal", "Embedding", "Fine-tuning",
    "Prompt Engineering", "RLHF", "Transformer", "Knowledge Graph",
    # 应用类型
    "Tool", "Framework", "API", "Product", "Research", "Platform",
    "CLI", "WebUI", "SDK", "Plugin",
    # 模型/论文
    "Paper", "Benchmark", "Open Source", "Survey", "Dataset",
    # 厂商
    "OpenAI", "Google", "Meta", "Anthropic", "DeepSeek", "ByteDance",
    "HuggingFace", "Nous Research", "LangChain",
    # 概念
    "MCP", "Vibecoding", "Low-Code", "Self-Hosted", "OSINT",
    "Orchestration", "Multi-Agent", "SuperAgent", "Autonomous",
    "Token-Efficient", "Microkernel",
    # 通用
    "AI", "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
    "Python", "TypeScript", "Rust", "Go",
}


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass
class DimensionScore:
    """单个维度的评分结果。"""

    name: str
    score: int
    max_score: int
    details: str = ""


@dataclass
class QualityReport:
    """一份文件的质量评分报告。"""

    filepath: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    total: int = 0
    grade: str = "C"

    def max_total(self) -> int:
        return sum(d.max_score for d in self.dimensions)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def collect_files(paths: list[str]) -> list[Path]:
    """收集 JSON 文件路径，支持通配符。"""
    files: list[Path] = []
    for raw in paths:
        matched = [Path(p) for p in glob_mod.glob(raw, recursive=True)]
        if not matched:
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


def load_json(filepath: Path) -> dict[str, Any] | None:
    """加载 JSON 文件。"""
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def count_chinese_chars(text: str) -> int:
    """统计中文字符数量（含中文标点）。"""
    return len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))


# ---------------------------------------------------------------------------
# 维度 1：摘要质量（25 分）
# ---------------------------------------------------------------------------
def score_summary(data: dict[str, Any]) -> DimensionScore:
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        return DimensionScore("摘要质量", 0, 25, "summary 非字符串")

    char_count = count_chinese_chars(summary)
    score = 0
    parts: list[str] = []

    if char_count >= 50:
        score += 20
        parts.append(f"字数 {char_count}（≥50 满分）")
    elif char_count >= 20:
        score += 12
        parts.append(f"字数 {char_count}（≥20 基本分）")
    else:
        parts.append(f"字数仅 {char_count}（不达标）")

    # 技术关键词奖励（最多 +5）
    tech_kw = re.findall(
        r"LLM|Agent|RAG|模型|训练|微调|推理|开源|API|框架|架构|多模态|嵌入|向量",
        summary, re.IGNORECASE,
    )
    bonus = min(len(set(tech_kw)), 5)
    score += bonus
    if bonus:
        parts.append(f"技术关键词 +{bonus}")

    return DimensionScore("摘要质量", min(score, 25), 25, " | ".join(parts))


# ---------------------------------------------------------------------------
# 维度 2：技术深度（25 分）
# ---------------------------------------------------------------------------
def score_tech_depth(data: dict[str, Any]) -> DimensionScore:
    raw = data.get("score")
    if raw is None:
        return DimensionScore("技术深度", 0, 25, "缺少 score 字段")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return DimensionScore("技术深度", 0, 25, f"score 类型错误: {type(raw).__name__}")

    article_score = max(1, min(10, int(raw)))
    mapped = round((article_score - 1) / 9 * 25)
    return DimensionScore(
        "技术深度", mapped, 25,
        f"文章评分 {article_score}/10 → 映射 {mapped}/25",
    )


# ---------------------------------------------------------------------------
# 维度 3：格式规范（20 分）
# ---------------------------------------------------------------------------
ID_PATTERN = re.compile(r"^[a-z]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")
ISO8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?$"
)

FORMAT_CHECKS = {
    "id": lambda d: isinstance(d.get("id"), str) and bool(ID_PATTERN.match(d["id"])),
    "title": lambda d: isinstance(d.get("title"), str) and len(d["title"].strip()) > 0,
    "source_url": lambda d: isinstance(d.get("source_url"), str)
    and bool(URL_PATTERN.match(d["source_url"])),
    "status": lambda d: d.get("status") in {"draft", "review", "published", "archived"},
    "timestamp": lambda d: (
        isinstance(d.get("fetched_at"), str)
        and bool(ISO8601_PATTERN.match(d["fetched_at"]))
    )
    or (
        isinstance(d.get("published_at"), str)
        and bool(ISO8601_PATTERN.match(d["published_at"]))
    ),
}


def score_format(data: dict[str, Any]) -> DimensionScore:
    passed = 0
    failed: list[str] = []
    for name, check in FORMAT_CHECKS.items():
        if check(data):
            passed += 1
        else:
            failed.append(name)

    score = passed * 4  # 每项 4 分，共 5 项 = 20 分
    detail = f"{passed}/5 项通过"
    if failed:
        detail += f"，缺少: {', '.join(failed)}"
    return DimensionScore("格式规范", score, 20, detail)


# ---------------------------------------------------------------------------
# 维度 4：标签精度（15 分）
# ---------------------------------------------------------------------------
def score_tags(data: dict[str, Any]) -> DimensionScore:
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return DimensionScore("标签精度", 0, 15, "tags 非列表类型")

    score = 0
    parts: list[str] = []

    # 数量评分：1-3 个最佳，4-5 个次之
    tag_count = len(tags)
    if 1 <= tag_count <= 3:
        score += 8
        parts.append(f"{tag_count} 个标签（最佳）")
    elif 4 <= tag_count <= 5:
        score += 5
        parts.append(f"{tag_count} 个标签（可接受）")
    else:
        parts.append(f"{tag_count} 个标签（过多或过少）")

    # 合法性：标签是否在标准列表中
    valid_count = sum(1 for t in tags if isinstance(t, str) and t in VALID_TAGS)
    score += valid_count  # 每个合法标签 +1，最多 +7
    if valid_count < len(tags):
        invalid = [t for t in tags if isinstance(t, str) and t not in VALID_TAGS]
        parts.append(f"{len(invalid)} 个非标准标签: {invalid[:3]}")

    return DimensionScore("标签精度", min(score, 15), 15, " | ".join(parts))


# ---------------------------------------------------------------------------
# 维度 5：空洞词检测（15 分）
# ---------------------------------------------------------------------------
def score_buzzwords(data: dict[str, Any]) -> DimensionScore:
    texts = [
        data.get("summary", ""),
        data.get("title", ""),
    ]
    combined = " ".join(str(t) for t in texts if t)
    lower = combined.lower()

    found: list[str] = []
    for word in CHINESE_BUZZWORDS:
        if word in combined:
            found.append(word)
    for word in ENGLISH_BUZZWORDS:
        if word in lower:
            found.append(word)

    unique = list(dict.fromkeys(found))  # 去重保序
    penalty = len(unique) * 3
    score = max(0, 15 - penalty)

    detail = "无空洞词" if not unique else f"检测到: {', '.join(unique)}（扣 {penalty} 分）"
    return DimensionScore("空洞词检测", score, 15, detail)


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------
def progress_bar(value: int, total: int, width: int = 20) -> str:
    filled = round(value / total * width) if total > 0 else 0
    return "█" * filled + "░" * (width - filled)


def grade_label(score: int) -> str:
    if score >= 80:
        return "A"
    elif score >= 60:
        return "B"
    return "C"


def grade_color(grade: str) -> str:
    if grade == "A":
        return "\033[32m"  # green
    elif grade == "B":
        return "\033[33m"  # yellow
    return "\033[31m"  # red


# ---------------------------------------------------------------------------
# 主评分逻辑
# ---------------------------------------------------------------------------
def evaluate(filepath: Path) -> QualityReport | None:
    data = load_json(filepath)
    if data is None:
        return None

    dimensions = [
        score_summary(data),
        score_tech_depth(data),
        score_format(data),
        score_tags(data),
        score_buzzwords(data),
    ]

    total = sum(d.score for d in dimensions)
    grade = grade_label(total)

    return QualityReport(
        filepath=str(filepath),
        dimensions=dimensions,
        total=total,
        grade=grade,
    )


def print_report(report: QualityReport) -> None:
    max_total = report.max_total()
    bar = progress_bar(report.total, max_total)
    color = grade_color(report.grade)
    reset = "\033[0m"

    print(f"\n{'─' * 60}")
    print(f"📄 {report.filepath}")
    print(f"{'─' * 60}")

    for d in report.dimensions:
        bar_dim = progress_bar(d.score, d.max_score, 15)
        print(f"  {d.name:<10} {bar_dim} {d.score:>2}/{d.max_score:<2}  {d.details}")

    print(f"  {'─' * 45}")
    print(f"  {'总分':<10} {bar} {report.total}/{max_total}  等级: {color}{report.grade}{reset}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python hooks/check_quality.py <json_file> [json_file2 ...]")
        print("支持通配符，如: python hooks/check_quality.py knowledge/articles/*.json")
        return 1

    files = collect_files(sys.argv[1:])
    if not files:
        print("未找到任何 JSON 文件")
        return 1

    reports: list[QualityReport] = []
    for fp in files:
        report = evaluate(fp)
        if report is None:
            print(f"\n[SKIP] {fp} — JSON 解析失败")
            continue
        reports.append(report)
        print_report(report)

    # 汇总
    print(f"\n{'═' * 60}")
    grade_counts = {"A": 0, "B": 0, "C": 0}
    for r in reports:
        grade_counts[r.grade] += 1
    print(
        f"汇总: {len(reports)} 个文件 | "
        f"A(≥80): {grade_counts['A']} | "
        f"B(60-79): {grade_counts['B']} | "
        f"C(<60): {grade_counts['C']}"
    )

    # A/B/C 分布图
    total = len(reports) or 1
    a_pct = grade_counts["A"] / total
    b_pct = grade_counts["B"] / total
    c_pct = grade_counts["C"] / total
    bar_a = "█" * round(a_pct * 30)
    bar_b = "█" * round(b_pct * 30)
    bar_c = "█" * round(c_pct * 30)
    print(f"  A: \033[32m{bar_a}\033[0m {grade_counts['A']}")
    print(f"  B: \033[33m{bar_b}\033[0m {grade_counts['B']}")
    print(f"  C: \033[31m{bar_c}\033[0m {grade_counts['C']}")

    return 1 if grade_counts["C"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
