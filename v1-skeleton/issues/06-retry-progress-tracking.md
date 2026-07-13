## What to build

Implement retry logic and progress tracking for the daily pipeline. This builds on the error handling decisions from #1 and adds concrete retry mechanisms and observability.

### Retry strategy

Per ADR from #1:
- Exponential backoff: base delay 5s, multiplier 2, max 3 retries
- Which stages are retryable vs fatal
- Dead-letter handling for persistently failing entries

### Progress tracking

Each pipeline run should produce a structured execution log:

```
# knowledge/runs/2026-07-12.json
{
  "date": "2026-07-12",
  "started_at": "2026-07-12T00:00:00Z",
  "finished_at": "2026-07-12T00:05:32Z",
  "stages": {
    "collector": {
      "status": "success",
      "duration_seconds": 12.3,
      "entries_found": 45,
      "entries_kept": 12
    },
    "analyzer": {
      "status": "success",
      "duration_seconds": 180.5,
      "entries_processed": 12,
      "llm_calls": 12,
      "llm_errors": 0
    },
    "organizer": {
      "status": "success",
      "duration_seconds": 2.1,
      "new_entries": 10,
      "duplicates_skipped": 2
    }
  },
  "errors": []
}
```

### Notification

When a stage fails persistently (after retries exhausted):
- Log error with full context
- Optionally notify via stderr exit code (to be picked up by cron/GitHub Actions)
- Future: notify via Telegram (when publisher agent is implemented)

### Existing assets

- `sub-agent-test-log.md` — contains timing data from a manual test run

## Acceptance criteria

- [ ] Retry decorator/utility implemented with configurable backoff
- [ ] Each pipeline stage produces structured timing and count data
- [ ] Run log written to `knowledge/runs/{YYYY-MM-DD}.json`
- [ ] Exit code reflects overall pipeline status (0 = all success, non-zero = any failure)
- [ ] Retry attempts are logged with `logging.warning()`
- [ ] After max retries, entry marked as error (not silently dropped)
- [ ] Progress tracking works even if pipeline is interrupted mid-run (partial output)

## Blocked by

- #1 (orchestration) — retry and notification decisions must be finalized first
