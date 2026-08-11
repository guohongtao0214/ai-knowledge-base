"""AI 知识库自动化流水线。

四步流程：采集 → 分析 → 整理 → 保存
支持 GitHub Search API 和 RSS 源两种采集通道。

用法:
    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from model_client import create_provider, chat_with_retry

logger = logging.getLogger(__name__)

# ─────────────────────────── 路径常量 ───────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "knowledge" / "raw"
RAW_GITHUB_DIR = RAW_DIR / "github"
RAW_RSS_DIR = RAW_DIR / "rss"
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"
RSS_CONFIG_PATH = Path(__file__).resolve().parent / "rss_sources.yaml"

# ─────────────────────────── 常量 ───────────────────────────

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_AI_QUERY = "agent OR llm OR mcp OR rag"
GITHUB_SORT = "stars"
GITHUB_ORDER = "desc"

GITHUB_TOKEN = ""
DEFAULT_LIMIT = 20

REQUIRED_FIELDS = (
    "id",
    "title",
    "source",
    "source_url",
    "summary",
    "tags",
    "category",
    "language",
    "status",
    "fetched_at",
)
VALID_CATEGORIES = {"llm", "agent", "tool", "paper", "benchmark", "product"}
AI_KEYWORDS = re.compile(
    r"ai|llm|agent|mcp|rag|langchain|prompt|gpt|transformer|"
    r"deep.learning|neural|reinforcement|nlp|computer.vision|"
    r"embedding|vector|fine.tun|quantiz|openai|anthropic|"
    r"人工智能|大模型|智能体|机器学习|深度学习|自然语言"
    r"|多模态|推理|生成式|预训练|对齐",
    re.IGNORECASE,
)

# ─────────────────────────── Article Schema ───────────────────────────

ARTICLE_FIELDS = {
    "id": str,
    "title": str,
    "source": str,
    "source_url": str,
    "source_id": str,
    "summary": str,
    "tags": list,
    "category": str,
    "language": str,
    "status": str,
    "fetched_at": str,
    "published_at": str,
    "analyzed_at": str,
    "metadata": dict,
    "score": (int, type(None)),
    "highlights": list,
    "score_reason": str,
}


# ─────────────────────────── Step 1: 采集 ───────────────────────────


def _load_rss_sources() -> list[dict[str, Any]]:
    """加载 RSS 数据源配置，仅返回已启用的源。

    Returns:
        已启用的 RSS 源配置列表。
    """
    if not RSS_CONFIG_PATH.exists():
        logger.warning(f"RSS 配置文件不存在: {RSS_CONFIG_PATH}")
        return []

    with open(RSS_CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", [])
    enabled = [s for s in sources if s.get("enabled", True)]
    logger.info(f"加载了 {len(enabled)}/{len(sources)} 个已启用的 RSS 源")
    return enabled


def _fetch_github_trending(limit: int) -> list[dict[str, Any]]:
    """从 GitHub Search API 采集 AI 相关的热门仓库。

    Args:
        limit: 最大采集数量。

    Returns:
        仓库信息列表。
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-knowledge-base",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    params = {
        "q": GITHUB_AI_QUERY,
        "sort": GITHUB_SORT,
        "order": GITHUB_ORDER,
        "per_page": min(limit, 100),
    }

    logger.info(f"正在搜索 GitHub: q={GITHUB_AI_QUERY}, limit={limit}")

    items: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(30)) as client:
        resp = client.get(GITHUB_SEARCH_URL, headers=headers, params=params)
        if not resp.is_success:
            logger.error(
                f"GitHub API 返回 {resp.status_code}: "
                f"{resp.text[:300]}"
            )
            resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            items.append(
                {
                    "source": "github",
                    "source_id": item.get("full_name", ""),
                    "source_url": item.get("html_url", ""),
                    "title": item.get("name", ""),
                    "description": item.get("description", ""),
                    "metadata": {
                        "stars": item.get("stargazers_count", 0),
                        "forks": item.get("forks_count", 0),
                        "language": item.get("language", ""),
                        "topics": item.get("topics", []),
                    },
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "published_at": item.get("created_at", ""),
                }
            )

    logger.info(f"GitHub 搜索返回 {len(items)} 条结果")
    return items


def _parse_rss_feed(text: str, source_config: dict[str, Any]) -> list[dict[str, Any]]:
    """用简易正则解析 RSS/Atom Feed，提取条目信息。

    同时支持 RSS 2.0 和 Atom 格式。

    Args:
        text: Feed 原始文本。
        source_config: RSS 源配置（包含 name、category 等）。

    Returns:
        解析后的条目列表。
    """
    items: list[dict[str, Any]] = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    item_pattern = re.compile(r"<(item|entry)>(.*?)</\1>", re.DOTALL)

    title_pat = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL)
    link_pat = re.compile(r'<link[^>]*href="([^"]*)"', re.DOTALL)
    link_pat2 = re.compile(r"<link[^>]*>(.*?)</link>", re.DOTALL)
    desc_pat = re.compile(r"<(?:description|summary|content)[^>]*>(.*?)</\1>", re.DOTALL)
    date_pat = re.compile(r"<(?:pubDate|published|updated)[^>]*>(.*?)</\1>", re.DOTALL)
    author_pat = re.compile(
        r"<(?:dc:creator|author|name)[^>]*>(.*?)</\1>", re.DOTALL
    )
    html_tag_pat = re.compile(r"<[^>]+>")
    entity_pat = re.compile(r"&[a-zA-Z]+;")

    entity_map = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&apos;": "'",
        "&#39;": "'",
        "&nbsp;": " ",
    }

    def _clean_html(raw: str) -> str:
        """去除 HTML 标签和实体。"""
        text = raw.strip()
        for ent, char in entity_map.items():
            text = text.replace(ent, char)
        text = html_tag_pat.sub("", text)
        text = entity_pat.sub("", text)
        return " ".join(text.split())

    def _extract(pattern: re.Pattern, content: str) -> str:
        m = pattern.search(content)
        if m:
            groups = m.groups()
            if groups and groups[0] is not None:
                return _clean_html(groups[0])
        return ""

    for match in item_pattern.finditer(text):
        block = match.group(2)

        title = _extract(title_pat, block)
        link = _extract(link_pat, block)
        if not link:
            link = _extract(link_pat2, block)
        description = _extract(desc_pat, block)
        pub_date = _extract(date_pat, block)
        author = _extract(author_pat, block)

        if not title and not link:
            continue

        if description and len(description) > 500:
            description = description[:500] + "..."

        items.append(
            {
                "source": "rss",
                "source_id": link,
                "source_url": link,
                "title": title,
                "description": description,
                "author": author,
                "metadata": {
                    "rss_source": source_config.get("name", ""),
                    "rss_category": source_config.get("category", ""),
                },
                "fetched_at": fetched_at,
                "published_at": pub_date or fetched_at,
            }
        )

    return items


async def _fetch_rss_feeds(
    limit: int,
) -> list[dict[str, Any]]:
    """异步抓取所有已启用的 RSS 源。

    Args:
        limit: 每个源的最大条目数。

    Returns:
        所有 RSS 条目的合并列表。
    """
    sources = _load_rss_sources()
    if not sources:
        logger.info("没有已启用的 RSS 源")
        return []

    all_items: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
        for src in sources:
            url = src["url"]
            name = src["name"]
            logger.info(f"正在抓取 RSS: {name} ({url})")

            try:
                resp = await client.get(url)
                resp.raise_for_status()
                items = _parse_rss_feed(resp.text, src)

                ai_items = [
                    item
                    for item in items
                    if AI_KEYWORDS.search(
                        f"{item.get('title', '')} {item.get('description', '')}"
                    )
                ]

                if ai_items:
                    logger.info(f"  {name}: {len(ai_items)}/{len(items)} 条匹配 AI 关键词")
                else:
                    logger.info(f"  {name}: {len(items)} 条，0 条匹配 AI 关键词")

                all_items.extend(ai_items[:limit])
            except httpx.HTTPError as e:
                logger.error(f"  抓取 {name} 失败: {e}")

    logger.info(f"RSS 共计采集 {len(all_items)} 条 AI 相关内容")
    return all_items


async def collect(
    sources: list[str],
    limit: int,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """采集阶段：从指定来源抓取 AI 相关内容。

    Args:
        sources: 采集来源列表（github / rss）。
        limit: 每个源的最大条目数。
        dry_run: 是否为干跑模式。

    Returns:
        所有采集到的原始条目列表。
    """
    all_items: list[dict[str, Any]] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")

    if "github" in sources:
        logger.info("=" * 50)
        logger.info(f"【Step 1 采集】GitHub Search API (limit={limit})")
        logger.info("=" * 50)

        github_items = _fetch_github_trending(limit)
        ai_items = [
            item
            for item in github_items
            if AI_KEYWORDS.search(
                f"{item.get('title', '')} {item.get('description', '')}"
            )
        ]
        logger.info(
            f"GitHub AI 过滤: {len(ai_items)}/{len(github_items)} 条匹配"
        )

        if not dry_run:
            RAW_GITHUB_DIR.mkdir(parents=True, exist_ok=True)
            raw_file = RAW_GITHUB_DIR / f"github-{timestamp}.json"
            raw_file.write_text(
                json.dumps(ai_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"原始数据已保存: {raw_file}")

        all_items.extend(ai_items)

    if "rss" in sources:
        logger.info("=" * 50)
        logger.info(f"【Step 1 采集】RSS Feeds (limit={limit})")
        logger.info("=" * 50)

        rss_items = await _fetch_rss_feeds(limit)

        if not dry_run and rss_items:
            RAW_RSS_DIR.mkdir(parents=True, exist_ok=True)
            raw_file = RAW_RSS_DIR / f"rss-{timestamp}.json"
            raw_file.write_text(
                json.dumps(rss_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"原始数据已保存: {raw_file}")

        all_items.extend(rss_items)

    logger.info(f"【Step 1 完成】共采集 {len(all_items)} 条原始内容")
    return all_items


# ─────────────────────────── Step 2: 分析 ───────────────────────────


ANALYZE_SYSTEM_PROMPT = """你是一个 AI 技术分析专家。请分析以下技术内容，输出一个严格的 JSON 对象，不要包含 markdown 代码块或额外文字。

JSON 结构：
{
  "title": "经你整理的中文标题（精炼准确，15-30字）",
  "summary": "中文摘要，100-200字，概括核心技术点、创新点和应用场景",
  "tags": ["标签1", "标签2", "标签3"],
  "category": "llm|agent|tool|paper|benchmark|product",
  "score": 7,
  "highlights": ["亮点1（一句话）", "亮点2（一句话）", "亮点3（一句话）"],
  "score_reason": "评分理由（50字以内）"
}

标签建议（不限于此）：Agent, MCP, LLM, RAG, Framework, Tool, Open Source, Multi-Agent, Autonomous, Vector DB, Fine-tuning, Prompt Engineering, API, CLI, Python, TypeScript

分类定义：
- llm: 大语言模型相关（训练、推理、架构、量化等）
- agent: AI Agent 框架、多智能体系统
- tool: AI 开发工具、SDK、基础设施
- paper: 学术论文、技术报告
- benchmark: 评测基准、数据集
- product: AI 产品、应用平台

评分标准（1-10）：
- 1-3: 小众工具、简单包装
- 4-6: 有实用价值的中等规模项目
- 7-8: 创新性强、影响力大的优质项目
- 9-10: 里程碑式的突破、行业标杆
"""


async def _analyze_single(
    item: dict[str, Any],
    provider: Any,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """对单条内容调用 LLM 进行分析。

    Args:
        item: 原始条目。
        provider: LLMProvider 实例。
        dry_run: 是否为干跑模式。

    Returns:
        分析后的结构化条目，失败返回 None。
    """
    title = item.get("title", "")
    source = item.get("source", "")
    description = item.get("description", "")
    metadata = item.get("metadata", {})

    user_prompt_parts = [
        f"来源平台: {source}",
        f"标题: {title}",
    ]
    if description:
        user_prompt_parts.append(f"描述: {description}")
    if isinstance(metadata, dict):
        stars = metadata.get("stars", 0)
        topics = metadata.get("topics", [])
        if stars:
            user_prompt_parts.append(f"Stars: {stars}")
        if topics:
            user_prompt_parts.append(f"Topics: {', '.join(topics[:10])}")

    user_prompt = "\n".join(user_prompt_parts)

    if dry_run:
        logger.info(f"  [dry-run] 跳过 LLM 分析: {title[:50]}")
        fallback = description or title or ""
        desc_text = f"。内容简介：{fallback[:120]}" if fallback else ""
        summary = (
            f"干跑模式采集内容，尚未经过 AI 分析生成详细中文摘要。该内容通过自动化流水线采集，"
            f"来源于 RSS 或 GitHub Trending，已自动标记标签和分类，"
            f"评分和质量分析有待后续 AI 处理{desc_text}"
        )
        return {
            **item,
            "title": title or "Untitled",
            "summary": summary,
            "tags": ["AI", "Tool", "Open Source"],
            "category": "tool",
            "language": "zh",
            "status": "draft",
            "score": 6,
            "highlights": ["干跑模式未进行 LLM 分析"],
            "score_reason": "干跑模式默认评分",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    messages = [
        {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await chat_with_retry(provider, messages, temperature=0.3)
        raw_content = response.content.strip()

        if raw_content.startswith("```"):
            raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content)
            raw_content = re.sub(r"\s*```$", "", raw_content)

        analysis = json.loads(raw_content)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"  分析失败: {title[:50]} — {e}")
        return None

    result = dict(item)
    result["title"] = analysis.get("title", title)
    raw_summary = str(analysis.get("summary", "") or description or "")
    if len(raw_summary.strip()) < 20:
        raw_summary = f"{raw_summary}。{title}。" if raw_summary.strip() else title
    result["summary"] = raw_summary[:200]
    result["tags"] = analysis.get("tags", [])
    result["category"] = analysis.get("category", "tool")
    result["score"] = analysis.get("score")
    result["highlights"] = analysis.get("highlights", [])
    result["score_reason"] = str(analysis.get("score_reason", ""))[:100]
    result["language"] = "zh"
    result["status"] = "draft"
    result["analyzed_at"] = datetime.now(timezone.utc).isoformat()

    if result["category"] not in VALID_CATEGORIES:
        result["category"] = "tool"

    return result


async def analyze(
    items: list[dict[str, Any]],
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """分析阶段：调用 LLM 对每条内容生成摘要、评分和标签。

    Args:
        items: 采集到的原始条目。
        dry_run: 是否为干跑模式。

    Returns:
        分析后的条目列表。
    """
    if not items:
        logger.info("【Step 2 分析】无内容需要分析")
        return []

    logger.info("=" * 50)
    logger.info(f"【Step 2 分析】对 {len(items)} 条内容进行 AI 分析")
    logger.info("=" * 50)

    provider = None
    if not dry_run:
        try:
            provider = create_provider()
        except ValueError as e:
            logger.warning(f"无法创建 LLM Provider: {e}. 切换到干跑模式。")
            dry_run = True

    results: list[dict[str, Any]] = []
    for i, item in enumerate(items, 1):
        logger.info(f"  分析 [{i}/{len(items)}]: {item.get('title', '')[:60]}")
        result = await _analyze_single(item, provider, dry_run)
        if result:
            results.append(result)

        if not dry_run and i < len(items):
            await asyncio.sleep(1)

    if provider:
        provider.close()

    logger.info(f"【Step 2 完成】成功分析 {len(results)}/{len(items)} 条")
    return results


# ─────────────────────────── Step 3: 整理 ───────────────────────────


def _load_existing_article_ids() -> set[str]:
    """加载已有文章的 ID 集合，用于去重。

    Returns:
        已有 ID 的集合。
    """
    ids: set[str] = set()
    if not ARTICLES_DIR.is_dir():
        return ids
    for fpath in ARTICLES_DIR.glob("*.json"):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                ids.add(data["id"])
        except (json.JSONDecodeError, OSError):
            continue
    return ids


def _load_existing_urls() -> set[str]:
    """加载已有文章的 URL 集合，用于去重。

    Returns:
        已有 source_url 的集合。
    """
    urls: set[str] = set()
    if not ARTICLES_DIR.is_dir():
        return urls
    for fpath in ARTICLES_DIR.glob("*.json"):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                url = data.get("source_url", "")
                if url:
                    urls.add(url)
        except (json.JSONDecodeError, OSError):
            continue
    return urls


def _validate_article(article: dict[str, Any]) -> list[str]:
    """校验文章字段完整性。

    Args:
        article: 文章字典。

    Returns:
        缺失或不合法的字段错误列表，空列表表示校验通过。
    """
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in article or not article[field]:
            errors.append(f"缺少必填字段: {field}")

    if article.get("tags") is not None and not isinstance(article.get("tags"), list):
        errors.append(f"tags 必须是列表类型")

    cat = article.get("category")
    if cat and cat not in VALID_CATEGORIES:
        errors.append(f"无效分类 '{cat}'，合法值: {VALID_CATEGORIES}")

    summary = article.get("summary", "")
    if isinstance(summary, str) and len(summary.strip()) < 20:
        errors.append(f"summary 字数不足: 当前 {len(summary.strip())} 字，最少 20 字")

    return errors


def _generate_id(source: str, date_str: str, counter: int) -> str:
    """生成文章唯一 ID。

    格式: {source}-{YYYYMMDD}-{NNN}

    Args:
        source: 来源标识（github / rss）。
        date_str: 日期字符串 YYYYMMDD。
        counter: 序号。

    Returns:
        唯一 ID。
    """
    return f"{source}-{date_str}-{counter:03d}"


def organize(
    items: list[dict[str, Any]],
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """整理阶段：去重、校验、生成 ID、标准化格式。

    Args:
        items: 分析后的条目。
        dry_run: 是否为干跑模式。

    Returns:
        通过整理后的有效文章列表。
    """
    if not items:
        logger.info("【Step 3 整理】无内容需要整理")
        return []

    logger.info("=" * 50)
    logger.info(f"【Step 3 整理】对 {len(items)} 条内容进行去重和标准化")
    logger.info("=" * 50)

    existing_urls = _load_existing_urls()
    existing_ids = _load_existing_article_ids()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter = 0

    validated: list[dict[str, Any]] = []
    skipped_dup = 0
    skipped_invalid = 0

    for i, item in enumerate(items, 1):
        source = item.get("source", "unknown")
        source_url = item.get("source_url", "")
        source_id = item.get("source_id", "")

        # 去重：按 URL
        if source_url and source_url in existing_urls:
            logger.info(f"  [{i}] 跳过重复: {source_url}")
            skipped_dup += 1
            continue

        # 生成 ID
        while True:
            counter += 1
            article_id = _generate_id(source, today, counter)
            if article_id not in existing_ids:
                break

        # 构建标准化文章
        article: dict[str, Any] = {
            "id": article_id,
            "title": item.get("title", ""),
            "source": source,
            "source_url": source_url,
            "source_id": source_id,
            "summary": item.get("summary", ""),
            "tags": item.get("tags", []),
            "category": item.get("category", "tool"),
            "language": item.get("language", "zh"),
            "status": "draft",
            "fetched_at": item.get("fetched_at", datetime.now(timezone.utc).isoformat()),
            "published_at": item.get("published_at", ""),
            "analyzed_at": item.get("analyzed_at", ""),
            "metadata": item.get("metadata", {}),
            "score": item.get("score"),
            "highlights": item.get("highlights", []),
            "score_reason": item.get("score_reason", ""),
        }

        # 校验
        errors = _validate_article(article)
        if errors:
            logger.info(f"  [{i}] 校验失败: {article_id} — {', '.join(errors)}")
            skipped_invalid += 1
            continue

        validated.append(article)
        existing_urls.add(source_url)
        existing_ids.add(article_id)
        logger.info(
            f"  [{i}] 通过: {article_id} — {article['title'][:40]} "
            f"[{article['category']}]"
        )

    logger.info(
        f"【Step 3 完成】通过 {len(validated)} 条，"
        f"跳过 {skipped_dup} 条重复、{skipped_invalid} 条无效"
    )
    return validated


# ─────────────────────────── Step 4: 保存 ───────────────────────────


def save(
    articles: list[dict[str, Any]],
    dry_run: bool = False,
) -> list[Path]:
    """保存阶段：将文章写入独立的 JSON 文件。

    Args:
        articles: 整理后的标准化文章列表。
        dry_run: 是否为干跑模式。

    Returns:
        已保存的文件路径列表（dry-run 模式下为空）。
    """
    if not articles:
        logger.info("【Step 4 保存】无文章需要保存")
        return []

    logger.info("=" * 50)
    logger.info(f"【Step 4 保存】保存 {len(articles)} 篇文章")
    logger.info("=" * 50)

    if dry_run:
        for article in articles:
            logger.info(
                f"  [dry-run] 将保存: {article['id']} — {article['title'][:50]}"
            )
        logger.info(f"【Step 4 完成】{len(articles)} 篇 (干跑模式，未实际写入)")
        return []

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for article in articles:
        filepath = ARTICLES_DIR / f"{article['id']}.json"
        filepath.write_text(
            json.dumps(article, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        saved.append(filepath)
        logger.info(f"  已保存: {filepath.name}")

    logger.info(f"【Step 4 完成】已保存 {len(saved)} 篇文章到 {ARTICLES_DIR}")
    return saved


# ─────────────────────────── 主流程 ───────────────────────────


async def run_pipeline(
    sources: list[str],
    limit: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """执行完整的四步流水线。

    Args:
        sources: 采集来源列表。
        limit: 每个源的最大采集数量。
        dry_run: 是否为干跑模式。

    Returns:
        流水线执行统计信息。
    """
    logger.info("=" * 60)
    logger.info("AI 知识库自动化流水线 启动")
    logger.info(f"  来源: {', '.join(sources)}")
    logger.info(f"  数量限制: {limit}/源")
    logger.info(f"  干跑模式: {'是' if dry_run else '否'}")
    logger.info("=" * 60)

    # Step 1: 采集
    raw_items = await collect(sources, limit, dry_run)

    # Step 2: 分析
    analyzed_items = await analyze(raw_items, dry_run)

    # Step 3: 整理
    articles = organize(analyzed_items, dry_run)

    # Step 4: 保存
    saved_paths = save(articles, dry_run)

    stats = {
        "collected": len(raw_items),
        "analyzed": len(analyzed_items),
        "organized": len(articles),
        "saved": len(saved_paths),
        "dry_run": dry_run,
    }

    logger.info("=" * 60)
    logger.info("流水线执行完毕")
    logger.info(f"  采集: {stats['collected']}")
    logger.info(f"  分析成功: {stats['analyzed']}")
    logger.info(f"  整理通过: {stats['organized']}")
    logger.info(f"  保存文件: {stats['saved']}")
    logger.info("=" * 60)

    return stats


# ─────────────────────────── CLI ───────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表，默认使用 sys.argv。

    Returns:
        解析后的命名空间。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库自动化流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pipeline/pipeline.py --sources github,rss --limit 20
  python pipeline/pipeline.py --sources github --limit 5
  python pipeline/pipeline.py --sources rss --limit 10
  python pipeline/pipeline.py --sources github --limit 5 --dry-run
  python pipeline/pipeline.py --verbose
        """,
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="github",
        help="采集来源，逗号分隔 (github, rss)。默认: github",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"每个源的最大采集数量。默认: {DEFAULT_LIMIT}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式，跳过 LLM 调用和文件写入",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志输出 (DEBUG 级别)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """主入口，解析参数并执行流水线。

    Args:
        argv: 命令行参数列表。
    """
    global GITHUB_TOKEN

    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    valid_sources = {"github", "rss"}
    sources = [s for s in sources if s in valid_sources]

    if not sources:
        logger.error(f"无效的 sources 参数，合法值: {', '.join(valid_sources)}")
        sys.exit(1)

    try:
        asyncio.run(
            run_pipeline(
                sources=sources,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        )
    except KeyboardInterrupt:
        logger.info("用户中断流水线执行")
        sys.exit(0)
    except Exception as e:
        logger.error(f"流水线执行异常: {e}", exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
