---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能，自动搜索、筛选、去重并生成中文摘要
---

# GitHub Trending 采集技能

## 使用场景

- 用户需要搜集 GitHub 上热门的 AI/LLM/Agent 开源项目
- 需要生成结构化简报，包含项目摘要和元数据
- 需要定期（每日/每周）采集并归档到 `knowledge/raw/`

## 允许的工具

| 工具 | 用途 |
|------|------|
| `Read` | 读取已有的 local 快照，辅助去重 |
| `Grep` | 在已有数据中搜索关键字 |
| `Glob` | 查找 `knowledge/raw/` 下的历史文件 |
| `WebFetch` | 抓取 GitHub API 搜索结果 |

> 此技能不涉及 Write/Edit/Bash 操作，结果由调用方负责落盘。

## 执行步骤

### 第 1 步：搜索热门仓库

调用 GitHub Search API，搜索 AI/LLM 相关仓库，按最近一周更新排序：

```
https://api.github.com/search/repositories?q=topic:ai+topic:llm+topic:agent+language:python+language:typescript&sort=updated&order=desc&per_page=50
```

如无法使用 API（Token 未配置），回退到抓取 GitHub Trending 页面：

```
https://github.com/trending?since=weekly
```

### 第 2 步：提取信息

对每个仓库提取以下字段：
- **仓库全名**（`owner/repo`）
- **URL**（`https://github.com/{owner}/{repo}`）
- **Star 数**
- **主要语言**
- **Topics 标签**
- **Description 描述**

### 第 3 步：过滤筛选

**纳入标准**（仓库 topics 或 description 需命中以下至少一个关键字）：
- AI, LLM, GPT, Agent, Prompt, RAG, ChatBot
- 大模型, 大语言模型, 智能体, Transformer, Fine-tuning
- Embedding, Vector Database, Knowledge Base, Semantic Search

**排除标准**：
- Awesome-* 列表类仓库（聚合链接，非原创项目）
- 纯教程/课程类仓库（如 `awesome-llm-apps`）
- 非技术类、纯营销推广仓库

### 第 4 步：去重

与 `knowledge/raw/github-trending-*.json` 中已有的历史记录对比，按 `url` 精确匹配，排除 7 天内已采集过的仓库。

### 第 5 步：撰写中文摘要

按以下公式为每个仓库生成 30-80 字中文摘要：

```
{项目名} — {做什么} — {为什么值得关注}
```

- 第 1 句：一句话概括项目是做什么的
- 第 2 句：核心技术亮点或与同类项目的差异
- 基于仓库 Description 和 Topics 编写，**不编造信息**

示例：
> Firecrawl 是面向 AI 代理的网页抓取与内容转换工具，可将任意网页一键转为 LLM 就绪的 Markdown 格式。已发展为 RAG 和 Agent 联网搜索的主流选择，Star 16 万。

### 第 6 步：排序取 Top 15

按 Star 数从高到低排序，取前 15 条。如果过滤后不足 15 条，放宽关键字匹配条件或降低 Star 门槛（如从周趋势改为月趋势），确保至少 10 条。

### 第 7 步：输出 JSON

将结果输出为 JSON，由调用方保存到：

```
knowledge/raw/github-trending-YYYY-MM-DD.json
```

## 输出格式

```json
{
  "source": "github",
  "skill": "github-trending",
  "collected_at": "2026-08-10T10:00:00Z",
  "items": [
    {
      "name": "firecrawl/firecrawl",
      "url": "https://github.com/firecrawl/firecrawl",
      "summary": "Firecrawl 是面向 AI 代理的网页抓取工具，可将任意网页一键转为 LLM 就绪的 Markdown 格式。Star 16 万，已成为 RAG 和 Agent 联网搜索的主流选择。",
      "stars": 164606,
      "language": "TypeScript",
      "topics": ["ai", "web-scraping", "llm", "rag"]
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 固定值 `github` |
| `skill` | string | 固定值 `github-trending` |
| `collected_at` | string | 采集时间（ISO 8601） |
| `items[].name` | string | 仓库全名 `owner/repo` |
| `items[].url` | string | GitHub 仓库 URL |
| `items[].summary` | string | 中文摘要（30-80 字） |
| `items[].stars` | number | Star 数量 |
| `items[].language` | string | 主要编程语言 |
| `items[].topics` | string[] | 仓库 Topics 标签 |

## 注意事项

- **API 限流**：GitHub Search API 未认证每分钟 10 次请求，优先使用 API Key（`GITHUB_TOKEN` 环境变量）
- **时效性**：每次采集标注 `collected_at`，7 天内不重复采集同一仓库
- **质量优先**：宁可条目少（≥10），不为了凑数纳入低质量/不相关内容
- **不编造**：summary 严格基于 description 和 topics，不得臆造功能或效果
- **中文输出**：所有 summary 必须为中文
