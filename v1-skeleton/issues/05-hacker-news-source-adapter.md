## What to build

Add Hacker News as a second data source to the Collector agent. The HN adapter fetches the front page, extracts top stories, filters AI-related content, and outputs entries in the same format as the GitHub Trending adapter.

### Algorithm

1. Fetch `https://news.ycombinator.com/` (or use HN Firebase API: `https://hacker-news.firebaseio.com/v0/`)
2. Extract top stories: title, URL, points, author
3. Filter AI/LLM/Agent entries (same keyword list as GitHub adapter)
4. Sort by points descending
5. Merge output with GitHub Trending entries or write separate file

### Output file

`knowledge/raw/hacker-news-{YYYY-MM-DD}.json`

Schema matches collector standard:
```json
{
  "title": "...",
  "url": "https://news.ycombinator.com/item?id=xxx",
  "source": "hacker_news",
  "popularity": 342,
  "summary": "..."
}
```

### Implementation notes

- HN API provides JSON natively (no HTML parsing needed for API approach)
- Fallback to HTML scraping if API rate-limited
- Deduplication across sources: a project that appears on both GitHub and HN should only appear once in the final output (handled by organizer in #4)
- Reuse the keyword filter list from #2 as a shared module

## Acceptance criteria

- [ ] Fetches HN front page and extracts top stories (≥ 30)
- [ ] AI keyword filtering works (same configurable list as #2)
- [ ] Output JSON matches collector standard schema
- [ ] Output file at `knowledge/raw/hacker-news-{YYYY-MM-DD}.json`
- [ ] Falls back to HTML scraping if API unavailable
- [ ] Handles network errors with retry

## Blocked by

- #2 (collector) — for shared filter module and output conventions
