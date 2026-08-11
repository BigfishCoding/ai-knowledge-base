# AI 知识库助手 V4

自动从 GitHub Trending 采集 AI/LLM/Agent 领域技术动态，经 AI 分析后结构化存储，并支持多渠道分发（Telegram / 飞书）的智能知识库系统。

## 项目架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         V4 Pipeline (pipeline.py)                       │
│                                                                         │
│   ┌───────┐    ┌─────────┐    ┌─────────┐    ┌────────┐    ┌────────┐ │
│   │ Plan  │───▶│ Collect │───▶│ Analyze │───▶│ Review │───▶│Organize│ │
│   └───────┘    └─────────┘    └─────────┘    └───┬────┘    └───┬────┘ │
│                                                   │           │       │
│                                        ┌──────────┘           │       │
│                                        │ failed,              │       │
│                                        │ retry < max          │       │
│                                        ▼                      ▼       │
│                                   ┌─────────┐            ┌────────┐   │
│                                   │ Revise  │            │  Save  │   │
│                                   └────┬────┘            └───┬────┘   │
│                                        │                    │        │
│                                        └──── retry ─────────┘        │
│                                        │                             │
│                                        │ failed ≥ max                │
│                                        ▼                             │
│                                   ┌───────────┐                      │
│                                   │Human Flag │──▶ END                │
│                                   └───────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Distribution Layer                               │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │                    Formatter                                  │     │
│   │   Article JSON  ──▶  Markdown / Telegram MDv2 / Feishu Card  │     │
│   └──────────────────────────────────────────────────────────────┘     │
│                              │                                         │
│                              ▼                                         │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │                    Publisher                                  │     │
│   │   TelegramPublisher ──▶ Telegram Bot API                     │     │
│   │   FeishuPublisher   ──▶ 飞书 Webhook                          │     │
│   │   OpenClawPublisher ──▶ OpenClaw Gateway (微信)               │     │
│   └──────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Bot Layer (常驻 Telegram 轮询)                    │
│                                                                         │
│   telegram_bot.py ──▶ KnowledgeBot ──▶ KnowledgeSearchEngine            │
│                           │                   SubscriptionManager      │
│                           │                   PermissionManager        │
│                           ▼                                            │
│                    /search  /today  /top  /subscribe  /help             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 工作流说明

| 节点 | 职责 | 关键输出 |
|------|------|----------|
| **Plan** | 根据目标采集量选择 lite/standard/full 三档策略 | `plan` 策略字典 |
| **Collect** | 调用 GitHub Search API 采集 AI 相关仓库 | `sources` 列表 |
| **Analyze** | LLM 生成中文摘要、标签、技术评分 | `analyses` 列表 |
| **Review** | 五维度评分（摘要/深度/相关性/原创性/格式），加权总分 ≥ 7.0 通过 | `review_passed` |
| **Revise** | 审核未通过时依据反馈定向改写，最多 3 轮迭代 | 修正后的 `analyses` |
| **Organize** | 过滤低分、URL 去重、应用审核反馈修正 | `articles` 列表 |
| **Save** | 写入 `knowledge/articles/` JSON 文件并重建索引 | 落盘文件 + `index.json` |
| **Human Flag** | 审核超限仍未通过时写入 `pending_review/` 供人工处理 | `needs_human_review` |

## 项目结构

```
ai-knowledge-base/
├── pipeline/
│   └── pipeline.py          # V4 完整执行入口（被 cron 触发）
├── workflows/               # V3 LangGraph 工作流核心
│   ├── graph.py             # StateGraph 组装与条件路由
│   ├── nodes.py             # collect / analyze / organize / save 节点
│   ├── planner.py           # 计划策略选择
│   ├── reviewer.py          # 五维度审核节点
│   ├── reviser.py           # 审核反馈修订节点
│   ├── human_flag.py        # 人工介入兜底节点
│   ├── state.py             # KBState 共享状态定义
│   └── model_client.py      # LLM 调用封装 + 成本熔断
├── distribution/
│   ├── formatter.py         # 多平台格式化（Markdown / Telegram / 飞书）
│   └── publisher.py         # 异步多渠道发布器
├── bot/
│   ├── telegram_bot.py      # Telegram 长轮询常驻进程
│   └── knowledge_bot.py     # 搜索 / 订阅 / 权限 Bot 引擎
├── tests/
│   ├── cost_guard.py        # 成本熔断测试
│   ├── eval_test.py         # 评估测试
│   ├── security.py          # 安全过滤与 PII 掩码
│   ├── verify_injection.py  # Prompt 注入检测
│   └── verify_pii.py        # PII 泄露检测
├── knowledge/               # 运行时数据（已 gitignore）
│   ├── articles/            # 结构化知识条目 JSON
│   └── raw/                 # 原始采集数据
├── hooks/
│   ├── check_quality.py     # 代码质量检查
│   └── validate_json.py     # JSON 校验
├── .env.example             # 环境变量模板
├── Dockerfile               # 多阶段构建
├── docker-compose.yml       # bot + pipeline 服务编排
├── daily_digest.py          # 每日简报推送入口
└── requirements.txt         # Python 依赖
```

## 快速开始

### 前置要求

- Python 3.12+
- 一个 LLM API Key（支持 DeepSeek / Qwen 等兼容 OpenAI SDK 的模型）
- （可选）GitHub Token — 提高搜索接口速率限制
- （可选）Telegram Bot Token — 用于推送
- （可选）飞书 Webhook URL — 用于推送

### 1. 克隆并安装依赖

```bash
git clone <repo-url>
cd ai-knowledge-base

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入真实 API Key：

```ini
# LLM API 配置（必填）
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# GitHub API（可选，提高搜索速率限制）
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx

# Telegram 推送（可选）
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_CHAT_ID=-1001234567890

# 飞书推送（可选）
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx
```

### 3. 运行流水线

```bash
# 执行一次完整采集 → 分析 → 审核 → 保存 → 分发
python -m pipeline.pipeline
```

### 4. 查看知识条目

```bash
# 生成的条目保存在 knowledge/articles/ 目录下
ls knowledge/articles/

# 生成并推送当日简报
python daily_digest.py
```

### 5. 启动 Telegram Bot（常驻）

```bash
# 确保已配置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID
python -m bot.telegram_bot
```

Bot 支持的命令：

| 命令 | 说明 |
|------|------|
| `/search <关键词> [标签:xx] [日期:2026-07-01~07-31]` | 搜索知识条目 |
| `/today` | 查看今日新增 |
| `/top [N]` | 相关性 Top N |
| `/subscribe <主题>` | 订阅主题 |
| `/help` | 帮助 |

### 6. Docker 部署

```bash
# 构建镜像
docker compose build

# 启动 Bot 服务（常驻）
docker compose up -d bot

# 手动执行一次流水线
docker compose run --rm pipeline
```

## 知识条目格式

每条知识条目存储在 `knowledge/articles/` 下，示例：

```json
{
  "id": "gh-20260711-001",
  "title": "DeepSeek-V3.2 发布：MoE 架构新突破",
  "source_url": "https://github.com/deepseek-ai/DeepSeek-V3.2",
  "source_type": "github_trending",
  "collected_at": "2026-07-11T08:00:00Z",
  "analyzed_at": "2026-07-11T08:05:00Z",
  "summary": "DeepSeek 发布 V3.2 模型，采用混合专家架构，在代码生成和推理任务上取得显著提升。",
  "key_points": [
    "MoE 架构，671B 参数，激活 37B",
    "128K 上下文窗口",
    "代码生成 SWE-bench 得分 74%"
  ],
  "tags": ["LLM", "MoE", "DeepSeek", "code-generation"],
  "status": "published",
  "distributed_to": ["telegram", "feishu"]
}
```

## 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.12 |
| AI 框架 | OpenCode + 国产大模型（DeepSeek / Qwen） |
| 工作流编排 | LangGraph |
| 数据采集 | GitHub Search API |
| 多渠道分发 | Telegram Bot API / 飞书 Webhook / OpenClaw |
| 容器化 | Docker + Compose |