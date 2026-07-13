## What to decide

Define how the daily AI knowledge base pipeline is orchestrated. Currently the 3 agents (collector → analyzer → organizer) are manually invoked via OpenCode. Production requires unattended daily runs.

Decisions needed:

1. **Scheduling**: How is the UTC 0:00 daily trigger implemented?
   - Options: cron job on a server, GitHub Actions scheduled workflow, Windows Task Scheduler, OpenCode scheduler
2. **Data passing**: How does data flow between agents?
   - Options: file-based (current `knowledge/raw/` + `knowledge/articles/`), in-memory message queue, temp files
3. **Upstream failure**: What happens when collector fails? Does the pipeline halt?
   - Options: downstream skips (graceful degradation), pipeline retries, alert-only, dead-letter queue
4. **Retry strategy**: How many retries? Exponential backoff? Manual intervention required?
5. **Progress tracking**: How to know if today's run succeeded/failed?
   - Logs to a file? Status file? Notification channel?

## Output

An ADR (Architecture Decision Record) documenting all choices, plus a scheduler skeleton script that:
- Invokes collector, analyzer, organizer in sequence
- Implements the chosen error handling
- Logs start/end/success/failure per stage

## Acceptance criteria

- [ ] ADR document written to `docs/adr/` with all 5 decisions recorded
- [ ] Scheduler skeleton script runs all 3 agents in sequence
- [ ] Stage failure propagates per the chosen strategy (skip / halt / retry)
- [ ] Each run produces a timestamped execution log

## Blocked by

None - can start immediately
