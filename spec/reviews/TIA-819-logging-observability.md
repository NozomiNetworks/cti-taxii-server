# Review — TIA-819 logging and observability

Status: **Complete** — all findings resolved or explicitly parked below; decisions folded
into RFC-001 (amendment) and the implementation.

| Field   | Value                                                            |
|---------|------------------------------------------------------------------|
| Date    | 2026-10-20                                                       |
| Process | Adversarial reviewer + critic loop: 2 rounds + final gate + authorized delta review |
| Scope   | TIA-819 implementation of RFC-001, RFC-002, ADR-001 (PRs #37/#38, plus secres #28/#29 deployment pins) |

## Findings (final state)

All blocking findings were fixed and verified before commit; each round's fixes were
re-reviewed (round-2 and delta reviews verified the fixes against installed library sources).

1. RESOLVED (HIGH) — raw username logged in `medallion/views/objects.py` → routed through
   `anonymize_user`.
2. RESOLVED (MEDIUM) — `medallion.access` / `medallion.audit` silent under the default WARN
   root level → explicit `INFO` on both loggers.
3. RESOLVED (MEDIUM) — username leaked via `/users/<user_id>/` in the access-log `path` field
   and in exported spans (`http.target` recorded from the raw URI by the WSGI instrumentation)
   → path masking (`_anonymized_request_path`) + response-hook span scrub (`_scrub_span_target`),
   verified end-to-end against the real instrumentation.
4. RESOLVED (MEDIUM) — access-log test poisoned the shared `APPLICATION_INSTANCE` singleton →
   dedicated test app via `register_access_log_hooks`.
5. RESOLVED (LOW, batch) — root-handler accumulation, `/ping/` access line, audit emitted
   before response construction, `anonymize_user(None)` raising, `.local/` gitignore, missing
   posture-table and audit-field tests.
6. RESOLVED (PR review, amendment) — JSON logging made the default; RFC-001 §4 amended with
   banner, `LOG_FORMAT=text` opts out.

## Parked follow-ups (non-blocking, candidates for future tickets)

- Rename `medallion/log.py` — the module name is shadowed by the package-level `log` logger
  attribute; rename requires a small ADR-001 amendment (it names the module).
- Harden evasion-shaped request paths (`/users%2Fname`, case/prefix variants) in the access-log
  path masking and span scrub.
- Add `http.url` / `url.full` to the span scrub tuple (defense-in-depth for WSGI environments
  that expose neither `RAW_URI` nor `REQUEST_URI`).
- The end-to-end span-scrub test asserts `http.target` (default semconv); under a
  new-semconv opt-in the `url.path` assertion would be needed instead.

## Open questions carried in the specs

- RFC-001 OQ-1: pymongo `serverselectiontryonce` `UserWarning` at startup — deployment Mongo
  URI decision (drop the option vs filter the warning).
- RFC-002 OQ-1: duplicate span IDs observed ingested twice — verify one affected trace
  waterfall in Tempo.
