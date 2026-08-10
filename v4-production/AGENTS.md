# AI 知识库助手 — Agent 规范

## 1. 项目概述

本项目是一个 AI 知识库助手，自动从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的技术动态，经 AI 分析后结构化存储为 JSON，并支持多渠道分发（Telegram / 飞书），帮助开发者持续追踪前沿技术趋势。

## 2. 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.12 |
| AI 框架 | OpenCode + 国产大模型（DeepSeek / Qwen） |
| 工作流编排 | LangGraph |
| 知识图谱 | OpenClaw |
| 数据采集 | GitHub Trending API、Hacker News API |
| 分发渠道 | Telegram Bot API、飞书 Webhook |

## 3. 编码规范

### 3.1 通用原则

- **PEP 8** 为基准规范，**Black** 作为自动格式化工具执行（近乎 PEP 8 超集，行长 88 字符例外）
- 变量/函数名: **snake_case**
- 类名: **PascalCase**
- 常量: **UPPER_SNAKE_CASE**
- 导入顺序：标准库 → 第三方库 → 项目内部模块（每组之间空行分隔）
- 类型注解：所有函数参数和返回值必须标注类型（Python 3.12+ 语法）
- **禁止裸 `print()`**，统一使用 `logging` 模块

### 3.2 文档要求

- **所有函数**（含私有 `_helper`）必须包含 **Google 风格 docstring**
- 模块/包须有模块级 docstring 说明职责
- 复杂逻辑须在函数体内附加行内注释，说明"为什么这样做"而非"做了什么"

```python
# 示例
def fetch_trending_repos(topic: str, limit: int = 30) -> list[dict]:
    """从 GitHub Trending 获取指定主题的热榜仓库。

    Args:
        topic: 筛选主题，如 "machine-learning"。
        limit: 返回数量上限，默认 30。

    Returns:
        包含仓库信息的字典列表。
    """
    ...
```

### 3.3 禁止魔法字符串

业务逻辑中禁止出现裸字面量，以下场景例外：

- HTTP status code 等既定标准值（`200`, `404`, `500`）
- 日志模板字符串（如 `"Processing %s items"`）
- 测试断言中的预期值（如 `assert x == "success"`）
- 常量定义自身的字面量（如 `MAX_RETRIES = 3` 中的 `3`）

> 上述例外若在代码中重复出现 ≥2 次，也应提取为命名常量。

### 3.4 禁止 TODO 泄漏到主分支

- CI 层硬拦截：`rg 'TODO|FIXME|HACK|XXX' --type py src/ tests/`，匹配则 pipeline fail
- 开发阶段允许 TODO，但合并前必须清理或转为 Issue 跟踪
- 如需临时遗留未完成工作，必须关联 Issue 编号，如 `#123: refactor this later`

### 3.5 TypeScript / 前端代码

后续引入前端时启用以下规范：

- `tsconfig.json` 中开启 `strict: true`
- ESLint + Prettier 格式化
- 所有公开接口必须包含 JSDoc

## 4. 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/          # Agent 定义与角色配置
│   └── skills/          # 可复用技能模块
├── knowledge/
│   ├── raw/             # 原始采集数据（JSON）
│   ├── articles/        # AI 分析后的结构化知识条目
├── src/
│   ├── collectors/      # 数据采集模块
│   ├── analyzers/       # AI 分析模块
│   ├── distributors/    # 多渠道分发模块
│   └── pipeline.py      # LangGraph 工作流入口
├── AGENTS.md            # 本文件
└── opencode.json        # OpenCode 配置
```

## 5. 知识条目 JSON 格式

每条知识条目存储在 `knowledge/articles/` 下，格式如下：

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

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 唯一标识，格式 `{source}-{date}-{seq}` |
| `title` | string | 知识条目标题 |
| `source_url` | string | 原始来源链接 |
| `source_type` | string | 来源类型：`github_trending` / `hacker_news` |
| `collected_at` | string | 采集时间（ISO 8601） |
| `analyzed_at` | string | AI 分析时间（ISO 8601） |
| `summary` | string | AI 生成的摘要（≤200 字） |
| `key_points` | string[] | 关键要点列表 |
| `tags` | string[] | 标签，用于分类检索 |
| `status` | string | 状态：`draft` / `review` / `published` / `archived` |
| `distributed_to` | string[] | 已分发的渠道列表 |

## 6. Agent 角色概览

| 角色 | 名称 | 职责 | 输入 | 输出 |
|------|------|------|------|------|
| **采集 Agent** | `collector` | 定时抓取 GitHub Trending 和 Hacker News 的 AI 相关内容 | 无（定时触发） | 原始数据 → `knowledge/raw/` |
| **分析 Agent** | `analyzer` | 对原始数据进行 AI 摘要、提取要点、打标签 | `knowledge/raw/` 中的 JSON | 结构化条目 → `knowledge/articles/` |
| **整理 Agent** | `distributor` | 将已审核的知识条目推送到 Telegram 和飞书 | `knowledge/articles/` 中 `status=published` 的条目 | 渠道推送结果 |

### 工作流

```
[定时触发] → collector → raw/ → analyzer → articles/ → distributor → [Telegram / 飞书]
```

## 7. 红线（绝对禁止）

1. **禁止硬编码 API Key / Token** — 必须通过环境变量或 `.env` 文件加载
2. **禁止将 `knowledge/` 目录提交到 Git** — 已加入 `.gitignore`
3. **禁止在生产代码中使用 `print()`** — 统一使用 `logging`
4. **禁止跳过 AI 分析直接分发原始数据** — 所有条目必须经过 `analyzer` 处理
5. **禁止在 `collector` 中修改 `knowledge/articles/` 目录** — 职责分离，采集只写 `raw/`
6. **禁止使用 `eval()` 或 `exec()`** — 存在注入风险
7. **禁止在未经用户确认的情况下自动发布到分发渠道** — 必须经过 `review` 状态

## 8. 质量门禁

### 8.1 测试覆盖率

- **行覆盖率 ≥ 80%**（使用 pytest-cov 度量，`--cov-report=term-missing --cov-fail-under=80`）
- 必须覆盖核心业务流程（采集 → 分析 → 分发）
- AI 分析模块中 LLM 调用必须通过 mock 隔离测试

### 8.2 CI 流水线

每次 push / PR 自动执行（GitHub Actions）：

| 步骤 | 命令 |
|------|------|
| 格式化检查 | `black --check src/ tests/` |
| Lint | `ruff check src/ tests/` |
| 类型检查 | `mypy src/` |
| 测试 + 覆盖率 | `pytest --cov=src --cov-report=term-missing --cov-fail-under=80` |
| TODO 检查 | `rg 'TODO|FIXME|HACK|XXX' --type py src/ tests/ && exit 1 || exit 0` |

### 8.3 Lint Suppress 规则

- 允许 `# noqa: XXXX`，但必须在同行附加注释说明原因
- 禁止无注释的 `# noqa`、`# type: ignore`（除非是因 mypy 自身 bug 不得不绕过）
- 禁止对整个文件或整个模块 suppress
