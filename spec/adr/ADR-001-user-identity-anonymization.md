# ADR-001 — User identity anonymization in logs and traces

| Field      | Value        |
|------------|--------------|
| Status     | Accepted     |
| Date       | 2026-10-19   |
| Author     | Federico Maggi |
| Related    | RFC-001      |
| Supersedes | —            |

## Context

The new access and audit logs (RFC-001) and the user-enriched trace spans would otherwise carry
full usernames. These records leave the service to shared, long-lived observability
infrastructure (Loki, Tempo) where they are readable by anyone with dashboard access, and
usernames are PII. The policy must be fixed before dashboards and alerts grow dependencies on
either raw or hashed identity values.

## Decision

### 1. Anonymize at field-construction time, through a single helper

A single `anonymize_user` function (`medallion/log.py`) is the only permitted path by which a
username reaches a log record or a span attribute; raw usernames never enter a record.

**Rationale:** centralizing the transform makes leakage a one-function audit and lets reviewers
check call sites mechanically.

**Rejected alternative:** filtering/redacting at handler level (a Formatter that scrubs
patterns) — regex-based scrubbing of free-form output is incomplete by construction and breaks
silently as fields evolve.

### 2. Deterministic lossy mask

Empty → empty; strings of ≤2 characters → `****`; otherwise the first 2 characters followed by
`****`. Email-shaped values are split on the first `@` and each side is masked independently.
Binding test vectors live in the repo's test suite.

**Rationale:** a constant-width mask leaks nothing about length beyond the 2-char prefix;
independent masking preserves the recognizable shape (`jo****@co****`) that makes triage
practical; being lossy means no key to manage and no risk of later reversal.

**Rejected alternative:** keyed hashing (stable pseudonyms enabling correlation) — rejected for
now: adds key management and an implicit reversibility story that the observability use case
does not need. Revisit only if investigations demand cross-system correlation.

## Consequences

Masking is irreversible by design: investigations that need the exact identity must use a
non-log source of truth. New username-bearing log or span fields must go through the helper —
that is a standing code-review check. The mask format is a visible contract once dashboards
filter on it; changing it later requires an RFC amendment.
