## What to build

Implement the Organizer agent: read analyzed entries, deduplicate against existing `knowledge/articles/`, generate standardized IDs, persist as JSON, and produce a Markdown daily report.

### Steps

1. **Read input**: Analyzer's output (from stdin or temp file, per #1)
2. **Deduplicate**: Compare with existing `knowledge/articles/*.json` by `url` and `title`. Skip duplicates.
3. **Generate ID**: Format `kh_{yyyymmdd}_{source}_{seq}` where:
   - `{yyyymmdd}` = crawl date
   - `{source}` = `gh` for github_trending, `hn` for hacker_news
   - `{seq}` = 3-digit zero-padded counter (001, 002, ...)
4. **Map score to importance**: 9-10→5, 7-8→4, 5-6→3, 1-4→2 or 1
5. **Classify category**: `paper` / `project` / `tool` / `article` / `discussion`
6. **Write JSON**: Save each entry as `knowledge/articles/{date}-{source}-{slug}.json`
7. **Generate Markdown daily report**: Filter importance ≥ 3, group by importance tier

### Markdown report format

```markdown
# AI 知识日报 — 2026-07-12

## 🔥 精选（重要性 ≥ 4）

### [title](url)
- **摘要**：summary
- **标签**：`tag1` `tag2`
- **来源**：source

## 📌 值得关注（重要性 = 3）

...
```

### Existing assets

- 10 sample articles in `knowledge/articles/` — use for dedup testing
- Standard JSON schema defined in `AGENTS.md` §5

## Acceptance criteria

- [ ] Reads analyzed entries and deduplicates by URL and title
- [ ] Generates `kh_` IDs that do not conflict with existing entries
- [ ] Score-to-importance mapping is correct
- [ ] Each JSON file validates against schema (all required fields, correct types)
- [ ] Markdown daily report generated with correct heading hierarchy
- [ ] Only importance ≥ 3 entries appear in the MD report
- [ ] If no new entries after dedup, still produces an empty-issue daily report
- [ ] Uses `logging` not `print()`

## Blocked by

- #3 (analyzer) — needs analyzed data as input
- #1 (orchestration) — for data passing conventions
