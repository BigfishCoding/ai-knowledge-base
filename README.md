# AI 知识库系统

基于多 Agent 协作的 AI 技术知识库——自动采集、智能分析、定时推送。

每天定时从 GitHub（Search / Trending）采集 AI/LLM/Agent 领域技术动态，由多 Agent 协作完成 **采集 → 分析 → 审核（回环修订）→ 整理 → 入库**，产出结构化知识条目（JSON + 索引），并多渠道分发到 Telegram / 飞书，同时通过 OpenClaw ClawBot 提供知识库检索问答。帮助团队每天 5 分钟掌握领域全貌。

---

## 1. 架构概览

四层架构：**Agent 层**（角色分工）→ **Pipeline 层**（LangGraph 编排）→ **工程层**（质量与成本护栏）→ **分发层**（多渠道出口）。

```
┌──────────────────────────────────────────────────────────────────────┐
│  Agent 层 · 角色协作（OpenCode 子 Agent）                              │
│                                                                      │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                      │
│   │ collector│───▶│ analyzer │───▶│ organizer│                      │
│   │ 采集     │    │ 分析摘要 │    │ 去重整理 │                      │
│   └──────────┘    └──────────┘    └──────────┘                      │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Pipeline 层 · LangGraph 工作流（V4 薄封装 = V3 核心 + V4 分发）        │
│                                                                      │
│   plan → collect → analyze → review ──passed──→ organize → save → END│
│                               │                                     │
│                     ┌─────────┴─────────┐                           │
│                     ▼                   ▼                           │
│              revise(回炉修订)      human_flag(人工兜底)               │
│                                                                      │
│   产物落盘 knowledge/articles/*.json + index.json                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  工程层 · 质量与成本护栏                                             │
│                                                                      │
│   CostGuard 预算熔断 │ Security 注入/PII/限流 │ hooks 质量门禁         │
│   pytest 覆盖率 ≥80% │ GitHub Actions CI（每日 cron 自动化）           │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  分发层 · 多渠道出口                                                 │
│                                                                      │
│   Telegram Bot ──▶ 每日简报推送                                       │
│   飞书 Webhook ──▶ 群内通知                                           │
│   OpenClaw ClawBot ──▶ 知识库检索问答（只读 index.json）              │
└──────────────────────────────────────────────────────────────────────┘
```

数据流：`采集 Agent → Pipeline 处理 → 落盘 knowledge/ → 分发推送 + ClawBot 检索`。形成「**流水线写、Bot 读**」的知识闭环。

## 2. 快速开始

三步即可在本地跑起完整系统：

```bash
# 1. 克隆仓库
git clone https://github.com/BigfishCoding/ai-knowledge-base.git
cd ai-knowledge-base

# 2. 配置环境变量（复制模板并填入真实值）
cp v4-production/.env.example v4-production/.env
#   必填：LLM_API_KEY（DeepSeek / GLM 均可，OpenAI 兼容）
#   可选：GITHUB_TOKEN / GITHUB_API_MIRROR / BUDGET_YUAN
#         TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / FEISHU_WEBHOOK_URL
#   ⚠️ .env 已被 .gitignore 排除，禁止提交

# 3. 容器化启动（Bot + Pipeline）
cd v4-production
docker compose --profile bot up -d

# 4.（可选）手动跑一次完整采集流水线
docker compose --profile bot run --rm pipeline
```

> 说明：`docker-compose.yml` 中 Bot / Pipeline 均挂在 `manual` profile 下，`--profile bot` 才会实际启动，避免 `compose up` 误启后台任务。OpenClaw 网关跑在宿主机（`openclaw daemon start`），通过 `./knowledge` 目录与容器共享数据。

## 3. 目录结构

| 目录 | 说明 | 版本 |
|------|------|:----:|
| `v1-skeleton/` | 骨架与 PRD：任务拆解、Agent 角色定义、串行 pipeline、Windows 定时 | V1 |
| `v1-skeleton02/` | v1 第二轮实验副本（全链路手工测试数据） | V1 |
| `v2-automation/` | 自动化阶段：质量钩子、OpenCode 插件、collector→analyzer→organizer 链路 | V2 |
| `v3-multi-agent/` | 多 Agent 正式实现：LangGraph 工作流、审核回环、CostGuard、Security、pytest | V3 |
| `v4-production/` | ★ 生产主实现：分发层 + Bot + Docker 容器化 + OpenClaw 知识图谱 | V4 |
| `v4-production/workflows/` | LangGraph 核心：graph / nodes / planner / reviewer / reviser / model_client | V4 |
| `v4-production/patterns/` | 模式库：Router 路由、Supervisor 监督 | V4 |
| `v4-production/distribution/` | 多渠道分发：formatter 格式化、publisher 异步推送 | V4 |
| `v4-production/bot/` | Telegram Bot：knowledge_bot 知识库交互 | V4 |
| `v4-production/pipeline/` | V4 一次完整执行入口（cron 触发） | V4 |
| `v4-production/openclaw/` | OpenClaw 工作区：ClawBot 检索入口 + skills（daily-digest 等 4 个） | V4 |
| `v4-production/tests/` | cost_guard / security / eval_test 测试套件 | V4 |
| `.github/workflows/` | CI 流水线（每日 UTC 0:00 自动采集） | V4 |

## 4. 技术栈

| 类别 | 选型 |
|------|------|
| Agent 编排 | **OpenCode**（子 Agent 角色定义 + 技能库） |
| 工作流编排 | **LangGraph**（8 节点有向图 + 审核回环） |
| 大模型 | **DeepSeek**（`deepseek-chat`，OpenAI 兼容 SDK，可切 GLM） |
| 容器化 | **Docker / Docker Compose**（多阶段构建 + 非 root 运行） |
| 推送渠道 | **Telegram Bot API**、飞书 Webhook |
| 知识图谱 | OpenClaw（ClawBot 检索问答） |
| 质量保障 | pytest（覆盖率 ≥80%）+ ruff / mypy / black + GitHub Actions |

## 5. 版本历史

| 版本 | 目录 | 核心能力 |
|------|------|----------|
| **V1** | `v1-skeleton/` | 项目骨架与 PRD、任务拆解（issues）、Agent 角色定义；`run_pipeline.py` 串行调度子 Agent，`run_daily.bat` + `setup_schedule.ps1` 实现 Windows 每日定时 |
| **V2** | `v2-automation/` | 引入质量钩子（`validate_json` / `check_quality`）与 OpenCode 插件，沉淀 Agent 角色 + 技能定义，跑通 collector → analyzer → organizer 链路测试 |
| **V3** | `v3-multi-agent/` | LangGraph 完整工作流：Planner 三档策略、五维加权审核 + 回炉修订回环、人工介入兜底、CostGuard 预算熔断、Security 安全防护、Router / Supervisor 模式、pytest 测试套件 |
| **V4** | `v4-production/` | ★ 生产主实现：在 V3 基础上新增分发层（Telegram / 飞书）、常驻 Telegram Bot、Docker 容器化部署、OpenClaw 知识图谱工作区；`.gitignore` 强制红线（`knowledge/` 与 `.env` 禁止入库） |

## 6. 月度成本估算

> 默认配置：`BUDGET_YUAN=1.0`（每日流水线预算），`PLANNER_TARGET_COUNT=10`（standard 档），每月 30 次运行。

| 项目 | 单价 / 估算 | 月成本 |
|------|-------------|:------:|
| **大模型**（DeepSeek `deepseek-chat`：输入 ¥1 / 百万 token，输出 ¥2 / 百万 token） | 默认 1.0 元 / 天预算 | ≈ **¥30** |
| 大模型（放宽场景：full 档、更高采集量） | 按需上调 `BUDGET_YUAN` | ¥30–90 |
| **服务器**（2C2G 轻量云主机，跑 Docker + OpenClaw） | ≈ ¥2–3 / 天 | ≈ **¥60–90** |
| 服务器（本机运行，仅演示） | 0 | **¥0** |
| **合计（云部署）** | | **≈ ¥90–120 / 月** |

**省钱建议**：GitHub 采集走匿名配额即可（可选 `GITHUB_TOKEN` 提升限额）；仅需日报推送时把 `BUDGET_YUAN` 调到 0.5；对推送实时性无要求可本机跑 Cron，服务器费用归零。

## 7. License

本项目基于 **MIT License** 开源。
