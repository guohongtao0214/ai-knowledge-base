#!/usr/bin/env python3
"""MCP Server — 本地知识库搜索服务。

通过 JSON-RPC 2.0 over stdio 协议提供以下工具：
- search_articles: 按关键词搜索文章标题和摘要
- get_article: 按 ID 获取文章完整内容
- knowledge_stats: 返回知识库统计信息

用法: python3 mcp_knowledge_server.py
"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

SERVER_NAME = "mcp-knowledge-server"
SERVER_VERSION = "1.0.0"


def _load_articles() -> list[dict[str, Any]]:
    """加载所有 JSON 文章文件。"""
    articles: list[dict[str, Any]] = []
    if not ARTICLES_DIR.is_dir():
        return articles
    for filepath in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                articles.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return articles


def _search_articles(
    keyword: str,
    limit: int = 5,
    articles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """按关键词搜索文章（标题 + 摘要匹配）。"""
    if articles is None:
        articles = _load_articles()
    keyword_lower = keyword.lower()
    results: list[dict[str, Any]] = []
    for article in articles:
        title = (article.get("title") or "").lower()
        summary = (article.get("summary") or "").lower()
        if keyword_lower in title or keyword_lower in summary:
            results.append(
                {
                    "id": article.get("id"),
                    "title": article.get("title"),
                    "source": article.get("source"),
                    "source_url": article.get("source_url"),
                    "summary": article.get("summary"),
                    "score": article.get("score"),
                    "tags": article.get("tags"),
                    "category": article.get("category"),
                    "status": article.get("status"),
                }
            )
            if len(results) >= limit:
                break
    return results


def _get_article(
    article_id: str,
    articles: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """按 id 获取完整文章内容。"""
    if articles is None:
        articles = _load_articles()
    for article in articles:
        if article.get("id") == article_id:
            return article
    return None


def _knowledge_stats(
    articles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """返回知识库统计信息。"""
    if articles is None:
        articles = _load_articles()

    total = len(articles)

    source_dist: dict[str, int] = dict(
        Counter(a.get("source", "unknown") for a in articles)
    )

    all_tags: list[str] = []
    category_dist: dict[str, int] = {}
    score_sum = 0
    score_count = 0

    for a in articles:
        tags = a.get("tags")
        if isinstance(tags, list):
            all_tags.extend(tags)
        cat = a.get("category")
        if cat:
            category_dist[cat] = category_dist.get(cat, 0) + 1
        score = a.get("score")
        if isinstance(score, (int, float)):
            score_sum += score
            score_count += 1

    tag_counts = Counter(all_tags)
    top_tags = tag_counts.most_common(10)

    avg_score = round(score_sum / score_count, 2) if score_count > 0 else 0

    return {
        "total_articles": total,
        "source_distribution": source_dist,
        "category_distribution": category_dist,
        "top_tags": [{"tag": tag, "count": count} for tag, count in top_tags],
        "average_score": avg_score,
    }


def _send_response(response_id: int | str | None, result: Any) -> None:
    """发送 JSON-RPC 成功响应。"""
    msg = {"jsonrpc": "2.0", "id": response_id, "result": result}
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _send_error(response_id: int | str | None, code: int, message: str) -> None:
    """发送 JSON-RPC 错误响应。"""
    msg = {
        "jsonrpc": "2.0",
        "id": response_id,
        "error": {"code": code, "message": message},
    }
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _send_notification(method: str, params: dict[str, Any] | None = None) -> None:
    """发送 JSON-RPC 通知（无 id）。"""
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle_initialize(msg: dict[str, Any]) -> dict[str, Any]:
    """处理 initialize 请求。"""
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
        "capabilities": {"tools": {}},
    }


def _handle_tools_list() -> dict[str, Any]:
    """处理 tools/list 请求。"""
    tools = [
        {
            "name": "search_articles",
            "description": "按关键词搜索知识库文章（匹配标题和摘要），返回匹配文章的摘要信息",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，匹配标题和摘要字段",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量上限，默认 5",
                        "default": 5,
                    },
                },
                "required": ["keyword"],
            },
        },
        {
            "name": "get_article",
            "description": "按文章 ID 获取完整内容，包含 highlights、metadata 等全部字段",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "string",
                        "description": "文章唯一标识 ID",
                    },
                },
                "required": ["article_id"],
            },
        },
        {
            "name": "knowledge_stats",
            "description": "返回知识库统计信息：文章总数、来源分布、分类分布、热门标签、平均评分",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]
    return {"tools": tools}


def _handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    """处理 tools/call 请求。"""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {}) or {}

    articles = _load_articles()

    if tool_name == "search_articles":
        keyword = arguments.get("keyword", "")
        limit = arguments.get("limit", 5)
        if not keyword:
            raise ValueError("缺少 keyword 参数")
        results = _search_articles(keyword, limit=limit, articles=articles)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(results, ensure_ascii=False, indent=2),
                }
            ]
        }

    elif tool_name == "get_article":
        article_id = arguments.get("article_id", "")
        if not article_id:
            raise ValueError("缺少 article_id 参数")
        result = _get_article(article_id, articles=articles)
        text = (
            json.dumps(result, ensure_ascii=False, indent=2)
            if result
            else f'未找到文章: {article_id}'
        )
        return {
            "content": [
                {"type": "text", "text": text}
            ]
        }

    elif tool_name == "knowledge_stats":
        stats = _knowledge_stats(articles=articles)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(stats, ensure_ascii=False, indent=2),
                }
            ]
        }

    else:
        raise ValueError(f"未知工具: {tool_name}")


def _process_message(msg: dict[str, Any]) -> None:
    """处理单条 JSON-RPC 消息。"""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {}) or {}

    try:
        if method == "initialize":
            result = _handle_initialize(msg)
            _send_response(msg_id, result)
        elif method == "tools/list":
            result = _handle_tools_list()
            _send_response(msg_id, result)
        elif method == "tools/call":
            result = _handle_tools_call(params)
            _send_response(msg_id, result)
        elif method == "notifications/initialized":
            pass  # 无需响应
        else:
            _send_error(msg_id, -32601, f"方法未找到: {method}")
    except ValueError as e:
        _send_error(msg_id, -32602, f"参数错误: {e}")
    except Exception as e:
        _send_error(msg_id, -32603, f"内部错误: {e}")


def main() -> None:
    """主循环 — 读取 stdin 并按行处理 JSON-RPC 消息。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        _process_message(msg)


if __name__ == "__main__":
    main()
