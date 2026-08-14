# 上线前 Checklist — V4 知识库系统（10 项完整版）

> 验证日期：2026-08-14
> 验证工具：OpenCode（Windows 本机）
> 说明：`[x]` 已在本机验证通过；`[~]` 需要服务器 / Docker / OpenClaw / 线上环境验证。

## 1. API Keys 环境变量

- [x] `.env` 文件存在（v4-production/.env，1173 B）
- [x] `.env` 已加入 .gitignore，`git ls-files .env` 无输出，未被 Git 跟踪
- [x] `.env.example` 存在，且包含必需变量（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / GITHUB_TOKEN / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / FEISHU_WEBHOOK_URL）

## 2. 权限策略

- [x] 4 个 Skill（category-summary / daily-digest / top-rated / weekly-digest）的 `allowed-tools` 均只有 `Read`
- [x] Skill 正文 / AGENTS.md 中虽出现 glob/grep/exec 字样，均为「不要使用」的说明性文本（category-summary:50、daily-digest:17,25、top-rated:33、weekly-digest:68、openclaw/AGENTS.md:3,19）；AGENTS.md:156 为「禁止 eval/exec」红线规则，无害
- [x] 全局 `tools.alsoAllow = ["read"]` — 本机 `openclaw config get tools.alsoAllow` 返回 `["read"]`，未开放 bash/write
- [x] 无 Skill 写入 knowledge/（allowed-tools 仅 Read，写权限集中在 pipeline）

## 3. 备份策略

- [x] `knowledge/articles/` 有数据（708 个 JSON 文件）
- [x] Docker 镜像打了版本标签 — `docker images` 显示 `kb-v4:v4.0`（另有 `kb-v4:latest`、`python:3.12-slim`）；compose 默认引用 `kb-v4:latest`，`v4.0` 标签用于回滚（配置检查 8）
- [x] Git 仓库推送到 GitHub（origin = github.com/BigfishCoding/ai-knowledge-base）
- [x] 另有手动备份：`v4-production/backup-20260814.zip`、`kb-v4-v4.0.tar`

## 4. 日志轮转

- [x] `max-size: "10m"`（docker-compose.yml:19）
- [x] `max-file: "3"`（docker-compose.yml:20）
- [x] 日志不含敏感信息 — 项目无独立 `logs/` 目录（容器用 json-file driver），本机日志为 `data/cron.log`(2.9MB) + `data/run-screenshot.log`；grep 扫描 `sk-`/`ghp_`/`BOT_TOKEN`/`webhook`/`Authorization`/长 token 等模式，仅命中变量名警告（"TELEGRAM_BOT_TOKEN 未配置"），无真实密钥值

## 5. 成本预算

- [x] CostGuard daily_budget 已设置：新增 `daily_budget_yuan=3.0`（环境变量 `BUDGET_DAILY_YUAN`），按 UTC 日期自动重置（tests/cost_guard.py:102；model_client.py:49,141）；自检 [5] 验证今日成本超日预算即抛异常
- [x] 熔断器 max_calls 已设置：新增 `max_calls=50`（环境变量 `MAX_LLM_CALLS`），达到上限即中断（tests/cost_guard.py:104；model_client.py:50,144）；自检 [6] 验证 2 次即熔断
- [x] 单次预算 `budget_yuan=1.0`（`BUDGET_YUAN`）＋ 超出抛 `BudgetExceededError`（自检 [3]）
- [x] 月度成本预估合理：流水线每日 1 次（cron 00:00 UTC），每次 ≤1.0 元 → 硬上限 30 元/月；按实际用量（DeepSeek 输入 ¥1/百万 token、输出 ¥2/百万 token）典型单次约 0.6–0.9 元 → 预计 18–27 元/月

## 6. 版本固定

- [x] requirements.txt 全部带版本号（aiohttp==3.14.1、langgraph==1.2.6、openai==2.40.0 等 8 项）
- [x] Docker 基础镜像 `python:3.12-slim`（非 latest）

## 7. 测试通道

- [x] `python -m pytest tests/` → 6 passed（tests/eval_test.py：结构校验 + 正/负/边界用例 + LLM-as-Judge）
- [x] `python tests/security.py` 自检 → 退出码 0，所有检查通过（注入防护 / PII 脱敏 / 审计落盘）
- [x] `python tests/cost_guard.py` 自检 → 退出码 0，成本追踪 / 预警阈值 / 熔断 / 分组报告全通过
- [~] 手动跑一次完整 Pipeline — 本机未跑（需 API Key 且消耗预算）；可执行 `python -m pipeline.pipeline`
- [x] 推送渠道已从 Telegram 改为飞书 Webhook，并完成实测推送（2026-08-14，git commit 3b2dcc0）

## 8. 回滚方案

- [x] 回滚步骤已记录（docker compose down → 改 image 为上个版本标签 → up -d）
- [~] 恢复数据备份 — 保留 backup-20260814.zip，需人工按需恢复

## 9. OpenClaw Bot 接管 Telegram（V4 新增）

- [x] daemon 监听 18789 — 本机 `netstat -ano` 确认 0.0.0.0:18789 LISTENING（gateway.port=18789）
- [x] 默认模型非 gpt-5.5 占位符 — `openclaw config get agents.defaults.model.primary` = `deepseek/deepseek-v4-flash`；gpt-5.5 占位符条目已从 `agents.defaults.models` 清除
- [x] 模型可调用 — 注册 `models.providers.deepseek`（baseUrl=https://api.deepseek.com/v1，apiKey=SecretRef DEEPSEEK_API_KEY，api=openai-completions）后，`capability model run --model deepseek/deepseek-v4-flash --prompt ping` 返回 HTTP 200 + `outputs: 1`
- [x] workspace = v4-production/openclaw — `openclaw config get agents.defaults.workspace` = `E:\openCode\ai-knowledge-base\v4-production\openclaw`

## 10. GitHub Actions 自动采集（V4 新增）

- [x] DEEPSEEK_API_KEY secret 已配 — run #1 成功完成即证明 secret 可读且 LLM 调用通过
- [x] daily-collect-v4 最近有 success — GitHub API 确认 run #1（workflow_dispatch，2026-08-14T06:25Z）completed + success；产物 artifact `knowledge-articles` 12,956B 已生成（run id=31776211092）
- [~] 知识库每天有新文章入库 — 今日手工触发已产出文章 artifact；「每天」还需 00:00 UTC 的 cron 定时首跑来最终确认
- 注：workflow 是把产物传 Actions artifact + 运行时推送飞书，不 commit 回仓库，故 git log 看不到 chore 提交属正常

## 汇总

```
[✓] [✓] [~] ... 10 项中本机已硬验证 14 个子项
```

### 待线上环境补充验证（[~] 项）

检查 7（完整 pipeline 实测）、8（数据恢复演练）、10 中「每日 cron 定时入库」（今日已手工触发成功，等 00:00 UTC 定时首跑）。

### 本机发现的问题（非阻塞）

1. tests/cost_guard.py 与 tests/security.py 的 `print` 含中文字符与 `¥`，在 Windows GBK 控制台直接运行时崩溃（UnicodeEncodeError）；加 `PYTHONIOENCODING=utf-8` 后正常。Linux/Docker 环境（默认 UTF-8）不受影响。

### 阻塞问题（[!!] 须修复）

无。检查 9（OpenClaw 模型 provider）与检查 10（Actions 自动采集）均已修复并验证通过。