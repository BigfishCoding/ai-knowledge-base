---
name: weekly-digest
description: 当用户要"本周总结 / 周报 / 这周有什么 / weekly digest"时触发。典型用语:这周学了啥 / 本周知识汇总 / weekly summary。基于本地 kb,不需要联网。
allowed-tools:
  - Read
---

# 每周知识汇总

## 触发词

- 本周 / 这周 / 一周
- weekly / 周报 / 周总结
- 这周学了啥 / 本周有什么新东西

## 做法

1. Read knowledge/articles/index.json
2. 筛选最近 7 天的文章（根据 collected_at 字段）
3. 去重（同一个 title 只保留 score 最高的一条；score 相同时保留最新的）
4. 按 relevance_score 降序排序（无 score 的视为 0）
5. 取 top 10（或用户指定数量）
6. 回复格式:

   **情况 A：有 score >= 0.6 的文章**
   
   📅 本周知识汇总（MM-DD ~ MM-DD）:

   1. <title> · score <score> · <category>
      <summary 前 100 字>...
      id: <id>

   2. <title> · score <score> · <category>
      <summary 前 100 字>...
      id: <id>

   ...

   📊 本周统计：共 N 篇新文章，平均 score <avg_score>

   **情况 B：所有文章均无 score 或 score < 0.6**
   
   📅 本周知识汇总（MM-DD ~ MM-DD）:

   ⚠️ 本周新采集的文章尚未评分，按时间倒序展示：

   1. <title> · <category> · <collected_at MM-DD HH:mm>
      <summary 前 100 字>...
      id: <id>

   2. <title> · <category> · <collected_at MM-DD HH:mm>
      <summary 前 100 字>...
      id: <id>

   ...

   📊 本周统计：共 N 篇新文章（均无评分）

## 日期计算

- 从 index.json 的 collected_at 字段提取日期
- 筛选条件：collected_at >= 7 天前
- 显示日期范围：从最早到最新的文章日期

## 禁止

- 别 read 目录(EISDIR)
- 别说"我没有 glob 工具",你只需要 read index.json 一个文件
- 别展示完整 summary，只展示前 100 字 + 省略号
- 别因为所有文章都没 score 就返回空结果（必须兜底展示）
