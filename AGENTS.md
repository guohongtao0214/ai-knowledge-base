# AI Knowledge Base Assistant

## 项目概述

自动采集 GitHub Trending 和 Hacker News 上 AI/LLM/Agent 领域的技术动态，经 AI 分析后结构化存储为 JSON，并支持多渠道（Telegram / 飞书）分发推送，帮助团队高效跟进 AI 领域前沿进展。

## 技术栈

- **运行环境**: Python 3.12
- **AI 编排**: OpenCode + 国产大模型
- **工作流引擎**: LangGraph
- **多渠道分发**: OpenClaw

## 编码规范

- **PEP 8** — 严格遵循，使用 `ruff` / `black` 自动格式化
- **命名** — 变量/函数 `snake_case`，类名 `PascalCase`，常量 `UPPER_CASE`
- **Docstring** — Google 风格（`Args:` / `Returns:` / `Raises:`）
- **日志** — 统一使用 `logging` 模块，**禁止裸 `print()`**

## 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/          # OpenCode Agent 定义
│   │   ├── collector.agent.md       # 采集 Agent
│   │   ├── analyzer.agent.md        # 分析 Agent
│   │   └── curator.agent.md         # 整理 Agent
│   └── skills/          # OpenCode Skill 定义
│       ├── fetch-trending.skill.md
│       ├── analyze-article.skill.md
│       └── distribute.skill.md
├── knowledge/
│   ├── raw/             # 采集原始数据（Markdown / HTML / JSON 快照）
│   │   ├── github/
│   │   └── hackernews/
│   └── articles/        # AI 分析后的结构化知识条目（JSON）
├── src/                 # 应用核心代码
│   ├── collector/       # 数据采集模块
│   ├── analyzer/        # AI 分析模块
│   │   └── prompts/     # Prompt 模板
│   ├── distributor/     # 分发模块（Telegram / 飞书）
│   └── models/          # 数据模型（Pydantic）
├── tests/               # 测试
├── config/              # 配置文件
│   └── settings.yaml
├── AGENTS.md
└── README.md
```

## 知识条目 JSON 格式

```json
{
  "id": "github-20260317-001",
  "title": "OpenAI 发布 GPT-5 技术报告",
  "source": "github",
  "source_url": "https://github.com/openai/gpt-5",
  "source_id": "openai/gpt-5",
  "summary": "GPT-5 技术报告详细阐述了新一代架构设计与多模态能力提升方案，在 MMLU、HumanEval 等基准上全面超越前代。",
  "tags": ["LLM", "OpenAI", "GPT-5", "多模态"],
  "category": "llm",
  "language": "zh",
  "status": "published",
  "fetched_at": "2026-08-06T10:30:00Z",
  "published_at": "2026-08-05T18:00:00Z",
  "analyzed_at": "2026-08-06T10:35:00Z",
  "metadata": {
    "stars": 15200,
    "description": "GPT-5 technical report",
    "topics": ["llm", "transformer", "multimodal"]
  }
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 唯一标识，格式 `{source}-{YYYYMMDD}-{NNN}`，如 `github-20260317-001` |
| `title` | string | 是 | 经 AI 整理的中文标题 |
| `source` | string | 是 | 来源：`github` / `hackernews` |
| `source_url` | string | 是 | 原始链接 |
| `source_id` | string | 否 | 来源平台 ID（如 GitHub 仓库全名） |
| `summary` | string | 是 | AI 生成的中文摘要（100-200 字） |
| `tags` | string[] | 是 | 标签列表 |
| `category` | string | 是 | 分类：`llm` / `agent` / `tool` / `paper` / `benchmark` / `product` |
| `language` | string | 是 | 摘要语言 `zh` / `en` |
| `status` | string | 是 | 状态：`draft` / `review` / `published` / `archived` |
| `fetched_at` | string | 是 | 采集时间（ISO 8601） |
| `published_at` | string | 否 | 原文发布时间 |
| `analyzed_at` | string | 否 | AI 分析完成时间 |
| `metadata` | object | 否 | 来源平台原始元数据（stars、description 等） |

## Agent 角色概览

| Agent | 职责 | 输入 | 输出 | 触发方式 |
|-------|------|------|------|----------|
| **Collector** (采集) | 每日抓取 GitHub Trending、Hacker News 首页中 AI/LLM/Agent 相关条目 | HTTP 请求 / RSS | `knowledge/raw/` 下的原始快照 | Cron 定时 / 手动触发 |
| **Analyzer** (分析) | 读取原始数据，调用 LLM 生成中文摘要、打标签、分类，产出结构化 JSON | `knowledge/raw/` | `knowledge/articles/{id}.json` | Collector 完成后自动触发 |
| **Curator** (整理) | 对已分析条目去重、归档过期内容、生成每日/每周简报、推送到 Telegram / 飞书 | `knowledge/articles/` | 简报消息 + 推送 | Analyzer 完成后 / 定时简报 |

## Agent 协作流程

```
Cron Trigger
     │
     ▼
  Collector ──► knowledge/raw/
     │
     ▼
  Analyzer  ──► knowledge/articles/{id}.json
     │
     ▼
  Curator   ──► Telegram / 飞书 推送
```

## 红线（绝对禁止）

1. **禁止提交 API Key / Token / 密钥到版本库** — 所有敏感凭证必须通过环境变量或 `config/settings.yaml` 注入，且 `settings.yaml` 必须加入 `.gitignore`
2. **禁止修改历史知识条目** — `knowledge/articles/` 中的 JSON 文件一旦状态变为 `published`，除 `Curator` Agent 的归档操作外，任何人/Agent 不得直接修改内容。如需修正，应创建新条目并标注 `revision_of`
3. **禁止绕过状态机** — 采集 → 分析 → 分发 必须按流水线流转，禁止跳过中间步骤直接将原始数据推送到渠道
4. **禁止在 Prompt 中硬编码业务逻辑** — 所有 Prompt 模板统一放在 `src/analyzer/prompts/` 目录下，使用模板引擎加载，禁止在 Agent 代码中内嵌长 Prompt
5. **禁止裸 `print()`** — 所有输出必须通过 `logging` 模块，带合适的日志级别（DEBUG/INFO/WARNING/ERROR）
6. **禁止未经校验的数据入库** — 所有写入 `knowledge/articles/` 的 JSON 必须经过 Pydantic 模型校验，确保字段类型和必填项完整
7. **禁止抓取非 AI/LLM/Agent 相关的内容** — Collector 必须按 `tags` 或 `title` 关键字过滤，避免噪音数据污染知识库
