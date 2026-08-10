---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

## 使用场景

- 每日 UTC 0:00 定时采集 GitHub Trending 热门项目
- 临时需要查阅当前 GitHub 上 AI/LLM/Agent 领域的热点动态
- 补充知识库数据源，确保覆盖最新的开源项目趋势

## 执行步骤

1. **搜索热门仓库**：调用 GitHub API（`GET /search/repositories`）搜索 `stars:>100 pushed:>2026-01-01`，同时抓取 `https://github.com/trending` 页面补充热门项目
2. **提取信息**：从每个仓库提取 name（owner/repo）、description、url、stars、language、topics（GitHub Topics）
3. **过滤**：保留与 AI/LLM/Agent 技术相关的仓库（通过 description 和 topics 匹配关键词）。**排除**名字或描述匹配 Awesome 列表的仓库（如 `awesome-*` 前缀的项目）
4. **去重**：按 `name`（owner/repo）去重，同一仓库只保留一条
5. **撰写中文摘要**：每条使用公式 `项目名 + 做什么 + 为什么值得关注` 撰写，长度 ≤ 100 字
6. **排序取 Top 15**：按 stars 数降序排列，截取前 15 条
7. **输出 JSON**：写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`

## 注意事项

- GitHub API 未认证时每小时限 60 次，建议使用 `GITHUB_TOKEN` 环境变量认证（提升至 5000 次/h）
- API Key 严禁硬编码，必须通过环境变量注入
- 过滤时排除 Awesome 列表（模板名含 `awesome` 或描述以 `Awesome` / `Curated list` 开头）
- 摘要必须使用中文撰写，禁止机翻英文摘要
- 输出文件路径中的日期使用 UTC 日期

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-07-12T00:00:00Z",
  "items": [
    {
      "name": "openai/gpt-5",
      "url": "https://github.com/openai/gpt-5",
      "summary": "GPT-5 是 OpenAI 最新大语言模型，MMLU 达 92.3%，值得关注其在推理和多模态能力的重大突破。",
      "stars": 15200,
      "language": "Python",
      "topics": ["llm", "openai", "gpt-5", "transformer"]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | ✅ | 固定为 `github_trending` |
| `skill` | string | ✅ | 固定为 `github-trending` |
| `collected_at` | string | ✅ | ISO 8601 采集完成时间 |
| `items` | array | ✅ | 项目列表，最多 15 条 |
| `items[].name` | string | ✅ | `owner/repo` 格式 |
| `items[].url` | string | ✅ | 仓库完整 URL |
| `items[].summary` | string | ✅ | 中文摘要，≤ 100 字 |
| `items[].stars` | int | ✅ | star 数量 |
| `items[].language` | string | ❌ | 主要编程语言 |
| `items[].topics` | array[string] | ❌ | GitHub Topics 标签 |
