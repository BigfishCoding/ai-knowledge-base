# AI Knowledge Base

自主运行的 AI 知识助手，每日定时从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的高质量技术动态，通过多 Agent 协作完成采集、分析和结构化存储，最终多渠道推送，助团队每日 5 分钟掌握领域全貌。

## 工作流程

```
collector (采集) → analyzer (分析) → publisher (发布)
```

- **collector**: 抓取 GitHub Trending & Hacker News，过滤 AI 相关，存为原始 JSON
- **analyzer**: 调用大模型（DeepSeek / GLM）去重、摘要、分类、重要性评分
- **publisher**: 筛选 importance ≥ 3 的条目，推送至 Telegram / 飞书

## 项目结构

```
ai-knowledge-base/
├── v1-skeleton/           # 项目骨架
│   ├── .opencode/         # Agent 定义与技能
│   │   ├── agents/        #  collector / analyzer / organizer 配置
│   │   └── skills/        # 技能 prompt 定义
│   ├── knowledge/         # 数据存储
│   │   ├── raw/           # 采集原始数据 (JSON)
│   │   └── articles/      # 分析后知识条目 (JSON)
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

详细规范见 [AGENTS.md](v1-skeleton/AGENTS.md)。
