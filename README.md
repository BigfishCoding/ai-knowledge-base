# AI Knowledge Base

自主运行的 AI 知识助手，每日定时从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的高质量技术动态，通过多 Agent 协作完成采集、分析、整理和审计，最终多渠道推送，助团队每日 5 分钟掌握领域全貌。

## 工作流程

```
collector (采集) → analyzer (分析) → organizer (整理)
                                    ↓
                              reviewer (审计) ← 独立巡审
```

- **collector**: 抓取 GitHub Trending & Hacker News，过滤 AI 相关，存为原始 JSON
- **analyzer**: 调用大模型（DeepSeek / GLM）去重、摘要、分类、重要性评分
- **organizer**: 格式标准化、生成唯一 ID、分类入库、输出 Markdown 日报
- **reviewer**: 独立巡审，并行检查各环节格式校验、数据一致性、内容真实性、安全审计

## 项目结构

```
ai-knowledge-base/
├── v1-skeleton/           # 项目骨架
│   ├── .opencode/         # Agent 定义与技能
│   │   ├── agents/        #  collector / analyzer / organizer / reviewer 配置
│   │   └── skills/        # 技能 prompt 定义
│   ├── knowledge/         # 数据存储
│   │   ├── raw/           # 采集原始数据 (JSON)
│   │   ├── articles/      # 分析后知识条目 (JSON)
│   │   └── reports/       # 审计报告 (Markdown)
│   ├── issues/            # 任务分解与跟踪
│   ├── specs/             # PRD 与编码规范
│   └── utils/             # 工具脚本
└── README.md
```

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12 | 后端 / 数据采集与分析 |
| OpenCode | Agent 编排框架 |
| DeepSeek / GLM | 内容分析、摘要、标签 |
| LangGraph | Agent 工作流编排 |
| OpenClaw | 网页抓取 |

## Agent 角色

| 角色 | 代号 | 颜色 | 职责 | 输出 |
|------|------|------|------|------|
| **采集** | collector | `#3b82f6` | 抓取 GitHub Trending / Hacker News，过滤 AI 相关 | `knowledge/raw/*.json` |
| **分析** | analyzer | `#10b981` | 调用大模型去重、摘要、分类、评分 | `knowledge/articles/tech-summary-*.json` |
| **整理** | organizer | `#f59e0b` | 格式标准化、生成 ID、分类入库、输出日报 | `knowledge/articles/*.json` |
| **审计** | reviewer | `#ec4899` | 独立巡审格式/一致性/真实性/安全 | `knowledge/reports/reviewer-report-*.md` |

## 质量审计

Reviewer Agent 每次巡审输出一份审计报告，覆盖四大维度：

| 维度 | 检查内容 |
|------|----------|
| **格式校验** | 各环节输出的 JSON 必填字段完整性 |
| **数据一致性** | ID 格式/唯一性、score↔importance 映射、分类合法性、status 流转 |
| **内容真实性** | 摘要/亮点是否基于原始内容，杜绝编造 |
| **安全审计** | 扫描 API Key、Token、密码、内网 IP 等敏感信息 |

### 评分等级

| 综合评分 | 结论 | 说明 |
|----------|------|------|
| ≥ 90 | ✅ 通过 | 质量合格，可直接发布 |
| 70–89 | ⚠️ 需复查 | 存在警告问题，建议人工确认 |
| < 70 | ❌ 未通过 | 存在严重问题，必须修复后重新审计 |

### 最新审计结果

见 `v1-skeleton/knowledge/reports/reviewer-report-20260713-1055.md`

详细规范见 [AGENTS.md](v1-skeleton/AGENTS.md)。
