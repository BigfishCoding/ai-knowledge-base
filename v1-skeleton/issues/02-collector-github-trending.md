## What to build

Implement the Collector agent's core pipeline: fetch GitHub Trending top 50 repos, filter AI/LLM/Agent related entries, and persist to `knowledge/raw/{source}_{date}.json`.

The collector is currently an OpenCode subagent with web access. This issue adds a proper Python implementation that can run both as a standalone script and be invoked by the orchestrator.

### Algorithm

1. Fetch `https://github.com/trending` (optionally with `?since=daily`)
2. Parse HTML to extract repo list: name, description, stars, language, today's stars
3. Filter: keep only entries where title or description contains AI/LLM/Agent related keywords (configurable list)
4. Sort by stars descending
5. Write to `knowledge/raw/github-trending-{YYYY-MM-DD}.json` in the format:
   ```json
   {
     "title": "...",
     "url": "https://github.com/owner/repo",
     "source": "github_trending",
     "popularity": 15200,
     "summary": "..."
   }
   ```

### Existing assets

- `utils/github_api.py` — basic GitHub API wrapper (can be extended)
- sampling test data exists in `knowledge/raw/github-trending-2026-07-12.json`

## Acceptance criteria

- [ ] Python script fetches GitHub Trending page and parses repo list
- [ ] AI keyword filter is configurable (env var or config file)
- [ ] Output JSON matches the schema defined in `.opencode/agents/collector.md`
- [ ] Output file path follows `knowledge/raw/github-trending-{YYYY-MM-DD}.json`
- [ ] Script handles network errors with retry (backoff per ADR from #1)
- [ ] If no AI-related entries found, writes empty array (does not crash)
- [ ] Idempotent: re-running on same day overwrites existing file without error

## Blocked by

- #1 (orchestration decisions) — for retry strategy and file path conventions
