---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# Tech Summary 分析技能

## 使用场景

- Collector 完成采集后，对 `knowledge/raw/` 中的原始数据进行深度分析
- 需要对一批技术项目/文章进行统一的评分、摘要、标签归类
- 发现当前技术趋势走向，识别新兴概念和重复主题

## 执行步骤

1. **读取原始数据**：读取 `knowledge/raw/` 目录下的最新采集文件（github-trending-YYYY-MM-DD.json 等），解析 items 数组
2. **逐条深度分析**：对每条 item 执行以下分析：
   - **摘要**：用 ≤ 50 字的中文概括核心要点
   - **技术亮点**：提取 2-3 个以事实和数据说话的技术亮点（如性能指标、架构特性、应用场景）
   - **评分**：按评分标准给出 1-10 分，必须附评分理由
   - **标签建议**：给出 2-5 个小写英文标签
3. **趋势发现**：对所有条目的分析结果进行横向归纳，识别：
   - 共同主题（如"Agent 框架"、"多模态"、"推理优化"）
   - 本周/本月新出现的概念或项目
   - 值得关注的技术方向
4. **输出分析结果 JSON**：写入 `knowledge/articles/tech-summary-YYYY-MM-DD.json`

## 评分标准

| 评分 | 含义 | 说明 |
|------|------|------|
| 9-10 | 改变格局 | 里程碑式发布、新范式论文、颠覆性工具 |
| 7-8 | 直接有帮助 | 可落地的新工具、实用的最佳实践、有参考价值的评测 |
| 5-6 | 值得了解 | 行业动态、常规更新、可拓展视野的内容 |
| 1-4 | 可略过 | 重复报道、低质量内容、非 AI 领域跑偏内容 |

## 约束

- 每批 15 个项目中，评分为 9-10 分的条目不超过 2 个（防止评分通胀）
- 摘要必须原创撰写，禁止直接翻译英文描述

## 注意事项

- 评分理由必须具体，不能写"感觉很好"等主观表述
- 标签统一使用小写英文，优先使用已有标签词表
- 亮点必须附带事实或数据，如"MMLU 提升 5.2%"而非"表现优秀"
- 趋势发现若无明显模式则不强制输出，避免牵强归纳
- LLM API Key 必须通过环境变量注入，严禁硬编码

## 输出格式

```json
{
  "source": "knowledge/raw/github-trending-2026-07-12.json",
  "skill": "tech-summary",
  "analyzed_at": "2026-07-12T00:05:00Z",
  "items": [
    {
      "name": "openai/gpt-5",
      "url": "https://github.com/openai/gpt-5",
      "summary": "GPT-5 多模态大模型，推理能力显著提升",
      "highlights": [
        "MMLU 得分 92.3%，较 GPT-4 提升 5.2 个百分点",
        "支持原生图片/音频/视频统一输入处理"
      ],
      "score": 9,
      "score_reason": "多模态架构突破性进展，MMLU 刷新 SOTA，对行业有范式级影响",
      "tags": ["llm", "multimodal", "openai", "benchmark"]
    }
  ],
  "trends": {
    "topics": ["多模态", "Agent 框架", "推理优化"],
    "emerging": ["基于 MCP 的工具调用标准化"],
    "note": "本周 Agent 框架类项目明显增多，值得持续跟踪"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | ✅ | 原始数据文件路径 |
| `skill` | string | ✅ | 固定为 `tech-summary` |
| `analyzed_at` | string | ✅ | ISO 8601 分析完成时间 |
| `items` | array | ✅ | 分析结果列表 |
| `items[].name` | string | ✅ | 项目名 |
| `items[].url` | string | ✅ | 原文链接 |
| `items[].summary` | string | ✅ | 中文摘要，≤ 50 字 |
| `items[].highlights` | array[string] | ✅ | 2-3 个基于事实的技术亮点 |
| `items[].score` | int | ✅ | 1-10 分 |
| `items[].score_reason` | string | ✅ | 评分具体理由 |
| `items[].tags` | array[string] | ✅ | 2-5 个小写英文标签 |
| `trends` | object | ❌ | 趋势发现（无可省略） |
| `trends.topics` | array[string] | ❌ | 共同主题列表 |
| `trends.emerging` | array[string] | ❌ | 新出现的概念或方向 |
| `trends.note` | string | ❌ | 趋势总结备注 |
