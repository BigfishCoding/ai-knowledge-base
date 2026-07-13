# Sub-Agent 联调测试记录

**测试日期**：2026-07-12
**测试场景**：采集 GitHub Trending 本周 AI Top 10 → 深度分析 → 整理入库
**数据源**：`github_trending`

---

## 1. Collector Agent（采集 Agent）

### 角色定义
`.opencode/agents/collector.md` — 负责从 GitHub Trending 采集数据，**禁止 Write/Edit/Bash**。

### 执行情况
| 检查项 | 结果 | 说明 |
|--------|:----:|------|
| 按角色执行 | ✅ | 使用 WebFetch 尝试抓取 GitHub Trending，因超时自动降级为 WebSearch 完成数据采集 |
| 越权行为 | ✅ 无 | 未使用 Write/Edit/Bash，仅使用 WebFetch + WebSearch 获取数据 |
| 产出质量 | ✅ 可接受 | 返回 10 条 AI 项目，含 title/url/source/popularity/summary/language/stars/forks/tags，字段完整 |
| 数据准确性 | ⚠️ 需关注 | 因 WebFetch 超时，数据来源为多个聚合源交叉验证，非 GitHub 页面直接抓取；star 数为近似值 |

### 需调整的地方
1. **WebFetch 超时容灾**：GitHub Trending 页面直接抓取超时（已自动降级到 WebSearch，但 WebSearch 数据精度不如直接抓取）
2. **采集源扩展**：建议增加 `ossinsight.io/trending/ai` 或 GitHub API 作为备用数据源
3. **数据新鲜度**：聚合来源的数据可能存在数小时延迟，建议标注 `scraped_at` 时间戳

---

## 2. Analyzer Agent（分析 Agent）

### 角色定义
`.opencode/agents/analyzer.md` — 负责对采集数据深度分析（摘要、亮点、评分、标签），**禁止 Write/Edit/Bash**。

### 执行情况
| 检查项 | 结果 | 说明 |
|--------|:----:|------|
| 按角色执行 | ✅ | 读取 raw 数据后按规则逐条分析，返回结构化 JSON |
| 越权行为 | ✅ 无 | 未使用 Write/Edit/Bash，仅以 JSON 代码块返回结果 |
| 产出质量 | ✅ 良好 | 10 条均包含完整 summary (≤200字)、highlights (1-3个)、score (1-10)、tags (≥2个)；评分理由详细 |
| 趋势洞察 | ✅ 加分 | 额外输出了本周主题总结（AI agent 走向规模化工程化） |

### 需调整的地方
1. **评分标准统一**：hermes-agent 获 9 分（改变格局），其余最高 8 分，区分度合理；但建议未来遇到里程碑项目时补充对比基线
2. **摘要长度**：多数 summary 在 120-180 字之间，符合 ≤200 字要求；部分可再精简
3. **亮点数量**：部分条目仅列出 2 个亮点，建议统一至少 2 个

---

## 3. Organizer Agent（整理 Agent）

### 角色定义
`.opencode/agents/organizer.md` — 负责去重、格式标准化、生成 ID、写入文件，**拥有 Write/Edit 权限，禁止 WebFetch/Bash**。

### 执行情况
| 检查项 | 结果 | 说明 |
|--------|:----:|------|
| 按角色执行 | ✅ | 执行了去重检查（空目录跳过）、ID 生成（kh_20260712_gh_001~010）、格式标准化、文件写入 |
| 越权行为 | ✅ 无 | 未使用 WebFetch 或 Bash |
| 产出质量 | ✅ 优秀 | 10 个文件全部通过 json.loads() 验证，必填字段完备，命名规范，ID 无冲突 |
| 字段映射 | ✅ 正确 | score→importance 映射（9→5, 8-7→4, 6→3）、category 分类（project/tool）均符合规则 |

### 需调整的地方
1. **author 提取**：当前简单从 title 的 `owner/name` 取了 owner 部分，但部分项目无明确组织信息，可考虑留空
2. **language 字段**：全部默认为 `en`，但如 Qwen-code 等国产项目实际为中文生态，后续应考虑根据项目特征动态判断
3. **slug 大小写**：文件名中 slug 使用了全小写（如 `desktopcommandermcp`），可读性略差，建议用连字符分隔（如 `desktop-commander-mcp`）

---

## 4. 全流程串联评估

### 4.1 数据流

```
Collector (WebSearch) ─→ Analyzer (分析) ─→ Organizer (写入)
     raw/                   分析结果              articles/
```

### 4.2 执行耗时

| 阶段 | Agent | 耗时 |
|------|-------|:----:|
| 采集 | Collector | ~15s（含 WebFetch 超时重试） |
| 分析 | Analyzer | ~20s |
| 整理入库 | Organizer | ~10s |
| **总计** | | **~45s** |

### 4.3 红线检查

| # | 红线要求 | 结果 |
|---|----------|:----:|
| 1 | 禁止硬编码 API Key/Token | ✅ 未涉及凭据 |
| 2 | 禁止使用 print() 输出日志 | ✅ 未使用 |
| 3 | 禁止直接覆盖他人输出文件 | ✅ articles/ 为空目录，无冲突 |
| 4 | 禁止分析阶段修改原始数据 | ✅ raw/ 文件未被修改 |
| 5 | 禁止删除 knowledge/ 下文件 | ✅ 未删除任何文件 |
| 6 | 禁止绕过 Agent 间通信接口 | ✅ 通过 Task 工具委派，接口合规 |
| 7 | 禁止提交未校验的 JSON | ✅ 全部通过格式校验 |

### 4.4 改进建议

1. **Collector 容灾增强**：为 WebFetch 配置备用源（如 OSSInsight / GitHub API），降低单点故障风险
2. **数据溯源标记**：非直接抓取的数据应标注 `confidence` 或 `source_quality` 字段
3. **Analyzer 上下文增强**：分析时可让 Analyzer 读取对应 GitHub 仓库的 README 以补充分析素材（当前仅基于标题和摘要）
4. **Organizer slug 规范化**：建议实现 slug 生成函数，将驼峰/点分命名转为连字符分隔
