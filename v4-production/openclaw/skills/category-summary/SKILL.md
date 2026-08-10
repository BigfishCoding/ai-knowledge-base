---
name: category-summary
description: 当用户要"按分类看 / 分类统计 / category 汇总 / 各分类有多少"时触发。典型用语:各分类有多少 / 按 category 统计 / framework 分类有哪些。基于本地 kb,不需要联网。
allowed-tools:
  - Read
---

# 分类汇总

## 触发词

- 按分类 / 分类统计 / category 汇总
- 各分类有多少 / 每个分类
- framework 分类 / agent 分类 / rag 分类
- 分类概览 / 分类列表

## 做法

1. Read knowledge/articles/index.json
2. 按 category 分组统计:
   - 每个分类的文章数量
   - 每个分类的平均 relevance_score
   - 每个分类的 top 3 文章（按 score 降序）
3. 按文章数量降序排序分类
4. 回复格式:

   📊 知识库分类汇总（共 N 篇）:

   🤖 framework（15篇 · 均分 0.82）
   1. <title> · score <score>
   2. <title> · score <score>
   3. <title> · score <score>

   🧠 agent（10篇 · 均分 0.75）
   1. <title> · score <score>
   ...

## 分类 emoji 映射

- framework: 🤖
- agent: 🧠
- rag: 📚
- tool: 🛠️
- mcp: 🔌
- 其他: 📌

## 禁止

- 别 read 目录(EISDIR)
- 别说"我没有 glob 工具",你只需要 read index.json 一个文件
- 别返回低于 0.5 score 的文章到 top 列表（质量太低）
