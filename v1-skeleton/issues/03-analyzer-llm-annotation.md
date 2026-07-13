## What to build

Implement the Analyzer agent that reads raw entries from `knowledge/raw/`, calls a Chinese LLM (DeepSeek / GLM) to annotate each entry, and produces structured output ready for the organizer.

### 3 dimensions of annotation (from PRD)

1. **Summary**: ≤ 200 character Chinese summary highlighting technical core
2. **Scoring**: 1-10 scale per rubric (9-10 = game-changing, 7-8 = directly useful, 5-6 = worth knowing, 1-4 = skippable)
3. **Tags**: 2-5 lowercase English tags (e.g. `llm`, `fine-tune`, `open-source`, `benchmark`)
4. **Highlights**: 1-3 technical highlights (optional)

### Input

Array of raw entries from `knowledge/raw/github-trending-{YYYY-MM-DD}.json`

### Output

Array of analyzed entries written to stdout or a temp file (per #1's data passing decision), schema:
```json
{
  "title": "...",
  "url": "https://github.com/owner/repo",
  "source": "github_trending",
  "source_type": "github",
  "summary": "中文摘要 ≤ 200 字",
  "highlights": ["highlight 1", "highlight 2"],
  "score": 9,
  "tags": ["llm", "openai"]
}
```

### Implementation notes

- LLM API key must come from environment variable (per AGENTS.md §7 red line #1)
- Use `logging` module, no `print()` (per red line #2)
- Caching: avoid re-analyzing entries with same `url` within the same run
- Batch LLM calls where possible to reduce API cost

## Acceptance criteria

- [ ] Reads raw JSON from `knowledge/raw/` and processes each entry
- [ ] Calls LLM (DeepSeek / GLM) for each entry with structured prompt
- [ ] Output JSON matches schema exactly (all required fields)
- [ ] Summary ≤ 200 Chinese characters
- [ ] Score is integer 1-10
- [ ] Tags ≥ 2, all lowercase English
- [ ] Handles LLM API failure gracefully (retry per #1 strategy)
- [ ] No hardcoded API keys (env var only)
- [ ] Uses `logging` not `print()`

## Blocked by

- #2 (collector) — needs raw data to process
- #1 (orchestration) — for data passing and error handling conventions
