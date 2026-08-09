# AI Knowledge Base

自主运行的 AI 知识助手：每天定时从 GitHub（Search/Trending）采集 AI/LLM/Agent 领域技术动态，由多 Agent 协作完成**采集 → 分析 → 审核（回环修订）→ 整理 → 保存**，最终产出结构化知识条目（JSON + 索引），支持多渠道分发（Telegram / 飞书），让团队每天 5 分钟掌握领域全貌。

仓库按迭代阶段沉淀了多个版本，`v3-multi-agent` 是当前功能最完整、代码可直接运行的主实现，`v1/v2` 作为演进史保留。

---

## 版本演进

| 目录 | 阶段 | 定位 |
|------|------|------|
| `v1-skeleton/` | 第一版骨架 | PRD / 编码规范 / 任务拆解（issues）/ Agent 角色定义；`run_pipeline.py` 串行调度子 Agent，`run_daily.bat` + `setup_schedule.ps1` 实现 Windows 每日定时，产出首份独立审计报告 |
| `v1-skeleton02/` | v1 第二轮实验 | 07-20 全链路手工测试的数据副本，字段协议定稿，是 v2 的前身 |
| `v2-automation/` | 自动化阶段 | 引入质量钩子（`hooks/validate_json.py`、`hooks/check_quality.py`）与 OpenCode 插件（`plugins/validate.ts`），沉淀 Agent 角色 + 技能定义，完成 collector → analyzer → organizer 链路测试 |
| `v3-multi-agent/` | 多 Agent 正式实现 | 基于 LangGraph 的完整工作流：Planner 三档策略、五维加权审核 + 回炉修订回环、人工介入兜底、CostGuard 预算熔断、Security 安全防护、Router / Supervisor 模式、pytest 测试套件 |

## v3 多 Agent 工作流

用 LangGraph 组装 8 个节点（`v3-multi-agent/workflows/graph.py`），核心是一个带**审核回环**的有向图：

```
plan → collect → analyze → review ──passed=True──→ organize → save → END
                              │
                              ├──passed=False & iteration < plan.max_iterations → revise → review
                              │
                              └──passed=False & iteration >= plan.max_iterations → human_flag → END
```

| 节点 | 职责 | 实现 |
|------|------|------|
| **plan** | 按目标采集量选择策略（lite / standard / full 三档） | `workflows/planner.py` |
| **collect** | GitHub Search API 抓取 AI 相关仓库，入口清洗防注入，API 失败可 Mock 回退 | `workflows/nodes.py:collect_node` |
| **analyze** | 逐条 LLM 生成中文摘要、要点、0-1 评分、标签 | `workflows/nodes.py:analyze_node` |
| **review** | 五维度 LLM 评分（摘要/深度/相关性/原创性/格式），代码重算加权总分，≥7.0 通过 | `workflows/reviewer.py` |
| **revise** | 审核未通过时携带反馈定向改写 analyses（高温 0.4） | `workflows/reviser.py` |
| **organize** | 按相关性阈值过滤、URL 去重、应用反馈修正、出口 PII 掩码 | `workflows/nodes.py:organize_node` |
| **human_flag** | 审核超限仍不通过时写入 `knowledge/pending_review/` 供人工处理 | `workflows/human_flag.py` |
| **save** | 落盘 JSON + 重建 `index.json` 检索索引 | `workflows/nodes.py:save_node` |

关键设计：

- **报告式通信**：节点间只传结构化摘要（`workflows/state.py` 的 `KBState`），不传原始数据，控制上下文成本
- **审核闭环**：`reviewer` 权重 `0.25/0.25/0.20/0.15/0.15`，总分由代码重算（不信任模型算术），低温度 0.1 保证一致性
- **预算熔断**：`CostGuard`（`tests/cost_guard.py`）按 DeepSeek 计价（输入 ¥1/百万 token、输出 ¥2/百万 token）记账，超 `BUDGET_YUAN` 即抛异常中断，报告落盘 `knowledge/reports/cost_report-*.json`
- **安全防护**：`tests/security.py` 提供输入清洗（防 Prompt 注入）、输出 PII 掩码（手机号/邮箱/身份证/信用卡/IP）、滑动窗口限流、审计日志四类能力，已接入 collect / organize 生产路径

## 目录结构

```
ai-knowledge-base/
├── v1-skeleton/            # 骨架与 PRD
│   ├── issues/             # 任务分解（01-06）
│   ├── specs/              # agents-prd / coding-standards
│   ├── utils/              # github_api.py 采集工具
│   ├── run_pipeline.py     # 串行 pipeline 入口
│   ├── run_daily.bat       # Windows 每日定时启动
│   ├── setup_schedule.ps1  # 注册任务计划
│   └── knowledge/          # raw / articles / reports
├── v1-skeleton02/          # v1 第二轮实验副本
├── v2-automation/          # 自动化阶段
│   ├── hooks/              # validate_json / check_quality
│   ├── .opencode/          # agents / plugins / skills
│   ├── specs/              # 规范与测试日志
│   └── knowledge/
└── v3-multi-agent/         # ★ 主实现
    ├── workflows/          # LangGraph 工作流（graph/state/nodes/planner/reviewer/reviser/human_flag/model_client）
    ├── patterns/           # Router 路由 / Supervisor 监督模式
    ├── hooks/              # JSON 校验 + 5 维质量评分
    ├── tests/              # cost_guard / security / eval_test / verify_*
    ├── knowledge/          # raw / articles(+index.json) / reports / audit
    ├── .opencode/          # agents / skills / plugins
    └── .env.example        # 环境变量模板
```

## 快速开始（v3）

```bash
cd v3-multi-agent

# 1. 安装依赖（langgraph / openai / httpx / python-dotenv）
pip install langgraph openai httpx python-dotenv

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：填入 LLM_API_KEY（DeepSeek/GLM 均可，兼容 OpenAI SDK），
# 可选配置 GITHUB_TOKEN / GITHUB_API_MIRROR / BUDGET_YUAN

# 3. 运行完整流水线（含流式日志、成本摘要与报告落盘）
python workflows/graph.py

# 4. 单节点自检与安全验证
python tests/cost_guard.py        # 预算守卫自检
python tests/security.py          # 安全模块自检
python tests/verify_injection.py  # 注入拦截验证
python tests/verify_pii.py        # PII 掩码验证

# 5. 质量校验钩子
python hooks/validate_json.py knowledge/articles/*.json
python hooks/check_quality.py knowledge/articles/*.json
```

## 环境变量

| 变量 | 必填 | 说明 | 默认 |
|------|:----:|------|------|
| `LLM_API_KEY` | ✅ | 模型 API Key | - |
| `LLM_BASE_URL` | | Base URL | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | | 模型名 | `deepseek-chat` |
| `BUDGET_YUAN` | | 单次流水线总预算（元），超限熔断 | `1.0` |
| `PLANNER_TARGET_COUNT` | | 目标采集量，决定策略档位 | `10` |
| `GITHUB_TOKEN` | | GitHub API 鉴权（可选，提升限额） | 匿名 |
| `GITHUB_API_MIRROR` | | 镜像前缀，解决国内直连（自动追加 `/search/repositories`） | 空 |
| `GITHUB_MOCK_FALLBACK` | | API 失败时启用内置 Mock 数据 | 关 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | | Telegram 推送（可选） | - |
| `FEISHU_WEBHOOK_URL` | | 飞书推送（可选） | - |

## 质量门禁

- **JSON 校验**：`hooks/validate_json.py` 检查必填字段、ID 格式（`{source}-YYYYMMDD-NNN`）、status 值域、URL、摘要长度、标签数量
- **质量评分**：`hooks/check_quality.py` 五维评分（摘要 25 + 深度 25 + 格式 20 + 标签 15 + 空洞词 15），≥80 为 A、≥60 为 B、否则 C
- **Eval 评估**：`tests/eval_test.py` 正面/负面/边界用例 + LLM-as-Judge 评分，LLM 用例以 `-m "not slow"` 跳过
- **编码规范**：各版本 `AGENTS.md` 均含 PEP 8 / Black / ruff / mypy / 类型注解 / 禁止裸 `print()` 等红线

## 知识条目格式

`knowledge/articles/` 下每条一个 JSON 文件，字段见各版本 `AGENTS.md` §5：

```json
{
  "id": "gh-20260809-001",
  "title": "langchain-ai/langchain",
  "source_url": "https://github.com/langchain-ai/langchain",
  "source_type": "github_trending",
  "summary": "LangChain 是用于开发大语言模型应用的开源框架……",
  "key_points": ["支持多种大语言模型和向量数据库", "提供链、代理、记忆等核心组件"],
  "tags": ["LLM", "框架", "AI应用"],
  "status": "draft",
  "collected_at": "2026-08-09T03:36:33Z",
  "analyzed_at": "2026-08-09T03:36:33Z",
  "distributed_to": []
}
```

`index.json` 由 `save_node` 自动重建，汇总 id / title / summary / tags / source_url 供检索。

## 相关文档

- 各版本 Agent 规范与编码规范：`*/AGENTS.md`
- PRD 与任务拆解：`v1-skeleton/specs/`、`v1-skeleton/issues/`
- 全链路手工测试日志：`v2-automation/specs/sub-agent-test-log.md`
- 首份审计报告：`v1-skeleton/knowledge/reports/reviewer-report-20260713-1055.md`
- 预算成本报告：`v3-multi-agent/knowledge/reports/cost_report-*.json`
