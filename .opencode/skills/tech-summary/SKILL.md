---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能，自动提取亮点、评分并发现趋势
---

# 技术内容分析总结技能

## 使用场景

- 需要对新采集的技术动态进行深度分析和评分
- 需要提取关键亮点、辅助团队快速决策关注哪些内容
- 需要识别当前技术趋势和新兴方向

## 允许的工具

| 工具 | 用途 |
|------|------|
| `Read` | 读取 `knowledge/raw/` 下的采集数据文件 |
| `Grep` | 在原始数据中搜索关键字，辅助内容理解 |
| `Glob` | 查找最新的采集文件和已分析的历史条目 |
| `WebFetch` | 必要时回查原文链接，获取更详细背景信息 |

> 此技能不涉及 Write/Edit/Bash 操作，分析结果由调用方负责落盘。

## 执行步骤

### 第 1 步：读取最新采集数据

用 Glob 匹配 `knowledge/raw/github-trending-*.json`，取日期最近的文件。读取文件内容，获取 items 列表。

### 第 2 步：逐条深度分析

对每条项目进行以下四个维度的分析：

**2.1 摘要提炼（≤50 字）**

比采集阶段的原始 summary 更进一步——提炼核心技术主张，用一句话说清"这个项目解决了什么问题、用什么方式"。不重复原始 description 的措辞。

示例：
> 将复杂网页自动清洗为 LLM 可消费的结构化数据，支撑 RAG 和 Agent 联网搜索能力。

**2.2 技术亮点（2-3 条，用事实说话）**

每条亮点必须是可验证的具体事实，禁止空洞的概括。格式：

```
✅ "在 MMLU 上超越 GPT-4 12 个百分点"        ← 好：具体数据
✅ "首个使用 Rust 重写的 LangChain 替代品"     ← 好：明确差异
❌ "性能大幅提升"                              ← 差：空洞
❌ "架构设计优秀"                              ← 差：主观
```

**2.3 评分（1-10，附理由）**

| 分数 | 等级 | 说明 | 示例 |
|------|------|------|------|
| 9-10 | 改变格局 | 重大突破、行业标杆、开源生态里程碑 | GPT-5 发布、Llama 4 开源 |
| 7-8 | 直接有帮助 | 对日常工作有实际价值，值得团队深入研究试用 | 成熟的 RAG 框架、Agent 工具链 |
| 5-6 | 值得了解 | 有一定参考意义，可泛读了解趋势 | 新兴框架、实验性项目 |
| 1-4 | 可略过 | 信息量低、营销性质强、或与团队方向关联度弱 | 列表聚合、课程仓库、纯概念 |

评分约束：**15 个项目中，9-10 分不超过 2 个**。如果多个项目候选 9 分，只取意义最重大的 1-2 个，其余降为 8 分。

评分理由必须 1-2 句话，具体说明：为什么该分数？（技术价值/创新性/生态影响/与团队关联度）

**2.4 标签建议**

为每条项目建议 3-5 个标签，覆盖技术领域 + 应用类型 + 厂商组织（如适用）：

- 技术：`LLM`, `Agent`, `RAG`, `Multimodal`, `Embedding`, `Fine-tuning`
- 应用：`Tool`, `Framework`, `API`, `Product`, `Research`
- 模型/论文：`Paper`, `Benchmark`, `Open Source`, `Survey`
- 厂商：`OpenAI`, `Google`, `Meta`, `Anthropic`, `DeepSeek`

### 第 3 步：趋势发现

对全部分析条目进行横向归纳，识别：

**3.1 共同主题（≥2 条）**

哪些技术方向被多个项目覆盖？例如：
- 本周 5 个项目涉及 Multi-Agent 架构 → 标注为"本周热点方向"
- 3 个新框架是 LangChain 替代品 → 标注为"工具链迁移趋势"

**3.2 新概念**

首次出现在采集数据中的新术语、新范式、新框架。与历史分析记录对比（可选），标记哪些是本周新出现的概念。

### 第 4 步：输出分析结果

将分析结果输出为 JSON，由调用方保存到：

```
knowledge/raw/tech-summary-YYYY-MM-DD.json
```

## 输出格式

```json
{
  "source": "tech-summary",
  "skill": "tech-summary",
  "analyzed_at": "2026-08-10T11:00:00Z",
  "data_source": "knowledge/raw/github-trending-2026-08-10.json",
  "items": [
    {
      "name": "firecrawl/firecrawl",
      "url": "https://github.com/firecrawl/firecrawl",
      "summary": "将复杂网页自动清洗为 LLM 可消费的结构化数据，支撑 RAG 和 Agent 联网搜索能力。",
      "highlights": [
        "支持 JavaScript 渲染页面抓取，覆盖 SPA 等动态站点",
        "提供自托管和云服务双模式，Star 16 万生态成熟"
      ],
      "score": 8,
      "score_reason": "AI Agent 联网搜索的基础设施组件，16 万星证明广泛采用，对 RAG 和 Agent 开发者有直接价值。但非突破性创新，更多是成熟产品化。",
      "tags": ["RAG", "Agent", "Tool", "Web Scraping"]
    }
  ],
  "trends": {
    "common_themes": [
      "Multi-Agent 架构成为本周热点：5 个项目涉及多 Agent 协作与编排",
      "AI 编码工具链持续扩展：3 个项目面向编码 Agent 生态"
    ],
    "new_concepts": [
      "RLM（强化学习模型）驱动的自进化编码代理",
      "图原生基础设施支持 AI 可问责性"
    ]
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 固定值 `tech-summary` |
| `skill` | string | 固定值 `tech-summary` |
| `analyzed_at` | string | 分析完成时间（ISO 8601） |
| `data_source` | string | 被分析数据源的文件路径 |
| `items[].name` | string | 仓库全名 `owner/repo` |
| `items[].url` | string | GitHub 仓库 URL |
| `items[].summary` | string | 技术摘要（≤50 字） |
| `items[].highlights` | string[] | 技术亮点，2-3 条，用事实说话 |
| `items[].score` | number | 推荐指数 1-10 |
| `items[].score_reason` | string | 评分理由（1-2 句话） |
| `items[].tags` | string[] | 标签建议，3-5 个 |
| `trends.common_themes` | string[] | 本周共同主题，≥2 条 |
| `trends.new_concepts` | string[] | 本周新出现的概念/术语 |

## 注意事项

- **摘要长度**：每条 summary 严格控制在 50 字以内，精炼核心主张
- **9-10 分限制**：15 条中最多 2 条达到 9-10 分，宁缺毋滥
- **亮点可验证**：所有 highlights 必须基于原始描述中的具体信息，不得编造数据和功能
- **标签一致性**：同一个概念在不同条目中使用相同的标签名称（如统一用 `Agent` 而非混用 `Agent`/`AI Agent`/`AI-Agent`）
- **趋势发现**：common_themes 必须至少有 2 个条目支撑，不基于单一条目臆测趋势
