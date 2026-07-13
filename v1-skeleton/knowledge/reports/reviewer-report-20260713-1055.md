# AI 知识审计报告 — 2026-07-13 10:55

## 📊 总览

| 检查项 | 通过 | 警告 | 失败 | 通过率 |
|--------|------|------|------|--------|
| 格式校验 | 22 | 6 | 0 | 100% |
| 数据一致性 | 149 | 2 | 0 | 98.7% |
| 内容真实性 | 5 | 0 | 0 | 100% |
| 安全审计 | 39 | 0 | 0 | 100% |

**综合评分**: 76/100
**结论**: ⚠️ 需复查 — 存在字段命名偏离规范和评分映射不一致问题，建议人工确认

---

## 🚨 严重问题（失败）

无严重问题。

---

## ⚠️ 警告问题

| # | 类型 | 环节 | 条目/文件 | 问题描述 |
|---|------|------|-----------|----------|
| 1 | format | collector | `knowledge/raw/github-trending-2026-07-12.json` | 条目字段使用 `name` 而非规范要求的 `title` |
| 2 | format | collector | `knowledge/raw/github-trending-2026-07-12.json` | 条目字段使用 `stars` 而非规范要求的 `popularity` |
| 3 | format | collector | `knowledge/raw/github-trending-2026-07-12.json` | 条目缺少 `source` 字段（source 仅在顶层） |
| 4 | format | analyzer | `knowledge/articles/tech-summary-2026-07-12.json` | 条目字段使用 `name` 而非规范要求的 `title` |
| 5 | format | analyzer | `knowledge/articles/tech-summary-2026-07-12.json` | 条目缺少 `source` 字段 |
| 6 | format | analyzer | `knowledge/articles/tech-summary-2026-07-12.json` | 条目缺少 `source_type` 字段 |
| 7 | consistency | organizer | `kh_20260712_gh_004` (system_prompts_leaks) | analyzer 评分为 6 → 应映射 importance 3，实际为 importance 4 |
| 8 | consistency | organizer | `knowledge/articles/` | analyzer 输出 15 条，organizer 输出 22 条，条目数量不一致（7 条来源不明） |

---

## ✅ 通过项摘要

### 格式校验

- **Organizer**: 全部 22 个文件 ✅ 必填字段完整（id / title / source / source_url / summary / tags / importance / category / status）
- Collector 和 Analyzer 存在字段命名偏离，但数据结构完整，内容可用

### 数据一致性

- **ID 格式**: 22/22 通过 — 全部匹配 `kh_{yyyymmdd}_{source}_{seq}` ✅
- **ID 唯一性**: 22/22 通过 — 无重复 ID，序列 001-022 连续无跳号 ✅
- **importance 范围**: 22/22 通过 — 均在 1-5 范围内 ✅
- **category 合法性**: 22/22 通过 — 全部属于 `paper` / `project` / `tool` ✅
- **status 流转**: 22/22 通过 — 全部为 `published` ✅
- **score→importance 映射**: 14/15 通过 — 1 项偏离（system_prompts_leaks: score 6 → imp 4，应为 3）

### 内容真实性

抽样 5 条比对 collector → analyzer → organizer 三环节摘要一致性：

| 条目 | collector 摘要 | analyzer 摘要 | organizer 摘要 | 一致性 |
|------|---------------|---------------|----------------|--------|
| hermes-agent | 213k stars, 闭环学习 | 213k stars, 闭环学习 | 213k 星标, 闭环学习 | ✅ |
| opencode | 176k stars, MCP/技能/编排 | 176k stars, MCP/技能/编排 | 176k stars, MCP/技能/编排 | ✅ |
| caveman | 87k stars, token 减 65% | 87k stars, token 减 65% | — | ✅ |
| qwen-agentworld | MoE 35B/3B, 七域, 超越 GPT-5.4 | 超越 GPT-5.4, MoE, 七域 | 超越 GPT-5.4, MoE, 七域 | ✅ |
| agent-skills | 24 工作流, Chrome 团队 | 24 流程, Addy Osmani | — | ✅ |

### 安全审计

- **扫描文件数**: 39（1 raw + 1 analyzer + 22 organizer + 15 collector items）
- **命中可疑模式**: 0 — 未发现 API Key、Token、密码、内网 IP 等敏感信息 ✅

---

## 📋 检查明细

### 格式校验

**collector / github-trending-2026-07-12.json**: name ⚠️ / url ✅ / source ⚠️ / stars ⚠️ / summary ✅ / language ✅ / topics ✅

**analyzer / tech-summary-2026-07-12.json**: name ⚠️ / url ✅ / source ⚠️ / source_type ⚠️ / summary ✅ / score ✅ / tags ✅

**organizer 全部 22 个文件**: id ✅ / title ✅ / source ✅ / source_url ✅ / summary ✅ / tags ✅ / importance ✅ / category ✅ / status ✅

### 数据一致性

- **ID 格式**: 22/22 通过
- **ID 唯一性**: 22/22 通过
- **importance 范围**: 22/22 通过
- **category 合法性**: 22/22 通过
- **status 流转**: 22/22 通过
- **score→importance 映射**: 14/15 通过 ⚠️
- **条目数量一致性**: collector 15 → analyzer 15 → organizer 22 ⚠️

### 安全审计

- 扫描文件数: 39
- 命中可疑模式: 0

---

## 📝 改进建议

1. **Collector/Analyzer 字段对齐**: 考虑统一使用 `title`/`popularity`/`source` 字段名，或同步更新 agent 规范文档以反映实际实现
2. **score→importance 映射校验**: organizer 应增加自动化检查，确保 analyzer 的 score 与 organizer 的 importance 映射一致
3. **条目数量一致性**: 建议增加 trace ID 追踪每条数据从 collector → analyzer → organizer 的完整流转，避免数据丢失或重复
