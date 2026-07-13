# AGENTS.md — AI Knowledge Base

## 1. 项目概述

AI Knowledge Base 是一个自主运行的 AI 知识助手，每天定时从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的高质量技术动态，由多 Agent 协作完成采集、分析和结构化存储，最终通过 Telegram/飞书等多渠道推送给团队成员，让每个人每天只需 5 分钟即可掌握领域全貌，不再遗漏关键信息。

## 2. 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12 | 后端运行时 / 数据采集与分析 |
| Node.js 22+ | 前端工具链 / API 服务 |
| TypeScript 5.x | 前端 / API 层静态类型 |
| OpenCode | Agent 开发与编排框架 |
| 国产大模型（DeepSeek / GLM） | 内容分析、摘要生成、分类打标 |
| LangGraph | 多 Agent 工作流图编排 |
| OpenClaw | 网页抓取与数据源适配 |

## 3. 编码规范

### 3.1 通用

- **缩进**：Python 使用 4 空格，TypeScript 使用 2 空格
- **行尾**：一律 LF（Unix），禁止 CRLF
- **文件末尾**：保留一个空行
- **行宽**：Python 88 字符（兼容 Black），TypeScript 100 字符（兼容 Prettier）
- **错误处理**：禁止捕获异常后 `pass` 或空 `catch`，必须记录日志或重新抛出
- **日志**：禁止裸 `print()` / `console.log()`，Python 使用 `logging`，TS 使用统一 logger 工具
- **凭据**：严禁硬编码 API Key / Token / 密码，必须通过环境变量注入（Python 用 `os.environ`，TS 用 `process.env`）
- **魔法字符串**：同一字面量在代码中重复 ≥2 处必须提取为模块级常量

### 3.2 Python 规范

| 工具 | 职责 |
|------|------|
| Black | 自动格式化（行宽 88） |
| ruff | 代码 lint、import 排序、最佳实践检测 |
| mypy | 静态类型检查 |

- **命名**：变量/函数/方法 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`
- **文档**：所有公开函数必须写 Google 风格 docstring（含 `__init__`、`@property`、`@overload` 重载、一行简单函数）
- **类型**：所有函数参数和返回值必须标注 type hints，优先使用 `list[X]` / `dict[K, V]` 而非 `typing.List[X]` / `typing.Dict[K, V]`
- **导入**：标准库 → 第三方库 → 本地模块，三段式分组，每组内按字母序排列
- **单测**：pytest + coverage.py，line/branch/function 均 ≥80%，测试放在 `tests/`

```python
# ✅ 正确示例
import logging
import os
from collections.abc import Iterator

import requests
from langgraph.graph import StateGraph

from knowledge.models import Article

logger = logging.getLogger(__name__)


def fetch_trending(language: str = "python", max_results: int = 30) -> list[dict]:
    """Fetch trending repositories from GitHub.

    Args:
        language: Programming language filter.
        max_results: Maximum number of results to return.

    Returns:
        List of raw repository dicts.
    """
    ...
```

### 3.3 TypeScript 规范

| 工具 | 职责 |
|------|------|
| Prettier | 自动格式化（行宽 100，单引号，尾随逗号） |
| ESLint | 代码 lint，配合 `typescript-eslint` |
| vitest | 单元测试 |

- **命名**：变量/函数/方法 `camelCase`，类/接口/类型 `PascalCase`，常量 `UPPER_CASE`，文件 `kebab-case`
- **类型**：`strict: true`，禁用 `any`，优先 `interface` 而非 `type`
- **文档**：所有公开函数必须写 JSDoc（含 `get` / 简单函数 / 重载声明）
- **导入**：external → internal，每组内按字母序；禁止 `import *`
- **异步**：优先 `async/await`，并行请求使用 `Promise.all()`
- **单测**：vitest，line/branch/function 均 ≥80%，测试放在 `tests/`

```typescript
// ✅ 正确示例
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import axios from "axios";
import { z } from "zod";

import type { Article } from "@/types";
import { logger } from "@/utils/logger";

const CACHE_TTL = 3_600_000; // 1 hour

interface FetchOptions {
  url: string;
  timeout?: number;
}

export async function fetchArticle(
  options: FetchOptions,
): Promise<Article> {
  const { url, timeout = 10_000 } = options;

  logger.info(`Fetching article from ${url}`);
  const response = await axios.get(url, { timeout });

  return response.data;
}
```

### 3.4 TODO 管理

- 本地拦截：**pre-commit hook**（`git commit` 前 grep 拦截）
- 拦截：`TODO` / `FIXME` / `HACK` / `XXX`
- 放行：`TODO(#issue-number)`（带 issue 引用的不拦）

### 3.5 pre-commit 钩子

- 配置入口：`.pre-commit-config.yaml`
- 必须包含：ruff、prettier、eslint、TODO 拦截检查
- CI 中 `pre-commit run --all-files` 验证全部文件

### 3.6 提交规范

采用 Conventional Commits，可选 scope，允许 6 种 type：

```
feat:     新功能
fix:      修复 bug
refactor: 重构（非功能、非修复）
chore:    杂项（CI、依赖、配置）
docs:     文档变更
test:     测试变更
```

示例：`feat(collector): add hacker news source adapter`

## 4. 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/              # Agent 定义与配置
│   │   ├── collector.json   # 采集 Agent
│   │   ├── analyzer.json    # 分析 Agent
│   │   └── publisher.json   # 发布 Agent
│   └── skills/              # Agent 技能（prompt / tool 定义）
│       ├── github.md
│       ├── hackernews.md
│       └── telegram.md
├── knowledge/
│   ├── raw/                 # 采集后的原始数据（JSON）
│   └── articles/            # 分析整理后的知识条目（JSON）
├── AGENTS.md                # 本文件
└── README.md
```

## 5. 知识条目 JSON 格式

```json
{
  "id": "kh_20260712_gh_001",
  "title": "OpenAI 发布 GPT-5 性能评估报告",
  "source": "github_trending",
  "source_url": "https://github.com/openai/gpt-5",
  "author": "openai",
  "summary": "OpenAI 正式发布 GPT-5，在推理、编程和多模态任务上相比 GPT-4 提升显著，MMLU 得分达 92.3%。",
  "tags": ["llm", "openai", "gpt-5", "benchmark"],
  "importance": 5,
  "category": "paper",
  "language": "en",
  "crawled_at": "2026-07-12T08:00:00Z",
  "analyzed_at": "2026-07-12T08:05:00Z",
  "status": "published"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 唯一标识，格式：`kh_{yyyymmdd}_{source}_{seq}` |
| `title` | string | ✅ | 标题（可保留原文，中文源则为中文） |
| `source` | string | ✅ | 数据源：`github_trending` / `hacker_news` |
| `source_url` | string | ✅ | 原文链接 |
| `author` | string | ❌ | 作者/组织 |
| `summary` | string | ✅ | AI 生成的中文摘要，≤ 300 字 |
| `tags` | array[string] | ✅ | 标签，至少 2 个，使用小写 |
| `importance` | int | ✅ | 重要性 1-5，仅当 ≥ 3 时进入精选 |
| `category` | string | ✅ | 分类：`paper` / `project` / `tool` / `article` / `discussion` |
| `language` | string | ❌ | 原文语言（默认 `en`） |
| `crawled_at` | string | ✅ | ISO 8601 采集时间 |
| `analyzed_at` | string | ❌ | ISO 8601 分析完成时间 |
| `status` | string | ✅ | `raw` → `analyzed` → `published` / `discarded` |

## 6. Agent 角色概览

| 角色 | 代号 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|------|
| **采集** | collector | 定时抓取 GitHub Trending 和 Hacker News，解析为结构化原始数据 | 数据源 URL + 调度信号 | `knowledge/raw/{source}_{date}.json` | OpenClaw、网络可达 |
| **分析** | analyzer | 读取原始数据，调用大模型去重、摘要、分类、重要性评分 | `knowledge/raw/*.json` | `knowledge/articles/{date}.json` | 国产大模型 API |
| **发布** | publisher | 从已分析条目中筛选 importance ≥ 3 的条目，推送到 Telegram/飞书 | `knowledge/articles/{date}.json` | 渠道消息推送 | Telegram Bot API / 飞书 Open API |

## 7. 红线（绝对禁止）

> 以下行为一旦发现，Agent 将被立即停用并触发告警。

| # | 红线 |
|---|------|
| 1 | **严禁在代码、配置或日志中硬编码 API Key、Token、密码等敏感凭据**，必须通过环境变量或 OpenCode Secret 注入 |
| 2 | **严禁使用 `print()` 输出日志或调试信息**，一律使用 `logging` 模块 |
| 3 | **严禁直接覆盖他人输出文件**，写入前必须校验 `id` 是否冲突，冲突则更新而非覆盖 |
| 4 | **严禁在分析阶段修改原始数据**，`knowledge/raw/` 下的文件采集 Agent 写入后为只读 |
| 5 | **严禁删除 `knowledge/` 目录下任意文件**，废弃条目通过 `status: discarded` 标记 |
| 6 | **严禁绕过 Agent 间通信接口直接操作数据库/文件系统**，必须通过定义的 Agent 接口协作 |
| 7 | **严禁在提交前未对 JSON 输出执行格式校验**，确保合法性 |
