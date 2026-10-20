# Spec — cti-taxii-server

All design documents live under `spec/`. Read the relevant file before starting any task;
update or create one when a decision is made.

## Structure

| Path | Contents |
|---|---|
| `spec/README.md` | This file — the process rules and the index of every RFC and ADR. |
| `spec/rfc/` | Request for Comments — design proposals, pending or accepted (`RFC-NNN`). Each RFC covers context, rationale, and design for one feature area or change. |
| `spec/adr/` | Architecture Decision Records — decisions made and closed (`ADR-NNN`). One file per decision that would be hard to revisit; captures context, rationale, and trade-offs. |
| `spec/reviews/` | Code review records. Reference them when addressing review feedback. |

## Lifecycles

- **RFC:** `Draft` → `Review` → `Accepted` | `Rejected`, and `Implemented` once shipped.
  Update the Status field in the document header as it moves through the lifecycle.
  Once accepted, extract any closed decisions into an ADR and mark the RFC `Accepted`.
- **ADR:** born `Accepted`. An ADR records a decision already made, not a debate.
- **Amendments:** never rewrite an accepted document silently. Record the change in a new RFC
  or ADR and prepend an amendment banner to the older document; the index notes the amendment.

## Authoring conventions

**Header tables.** Use these field labels (extra rows are fine; do not rename these):

| Doc | Required fields | Optional fields |
|-----|-----------------|-----------------|
| RFC | `Status`, `Author`, `Created`, `Related tasks` | `Related`, `Resolves` |
| ADR | `Status`, `Date`, `Author` | `Related`, `Supersedes` |

- Do **not** use `Decision` as a header-table label — it collides with the `## Decision` section
  every ADR has. The person is the `Author`; the choice is the `## Decision` body.
- Put cross-references (RFC/ADR/ticket IDs, external specs) in a `Related` row, not scattered
  across other fields.

**RFC proportionality.** An RFC tracks rationale and decisions; it is not an implementation
guide. Match depth to complexity: a header table plus a few paragraphs of context and rationale
is a complete RFC for a small change. Full design and contract sections are for large changes.

**Code & file references.** Always cite paths repo-relative from the repository root, with an
optional `:line` — e.g. `src/auth/session.go:33`. Never use a partial path or a bare filename;
they are ambiguous and unclickable. Line numbers drift — prefer a symbol name when the exact
line is not essential.

**Contract tables must match the implementation.** When a spec table states an observable
contract (HTTP status, response body, headers, wire format), it is the source of truth: keep
the code and the table in lock-step, and if they diverge in review, fix whichever is wrong
rather than leaving them inconsistent.

**Cross-linking & this index.** Reference other docs by ID (`RFC-004`, `ADR-007`) and work by
ticket ID. Whenever an RFC or ADR is created or its status changes, update the
[Index](#index) below **in the same change** — do not leave it stale.

## Reviews

Review records live in `spec/reviews/`, named `TIA-<ticket>-<topic>.md` for per-task reviews or
`SEC-NNN-<topic>.md` for standing security review campaigns. Findings are numbered and
severity-tagged (`CRITICAL` / `HIGH` / `MEDIUM` / `LOW`), each citing a repo-relative path.
Reviewees reply inline under each finding with `> fix`, `> won't fix: <reason>`, or
`> question`. When all findings are resolved, mark the review complete at the top and fold any
resulting decisions into an ADR (or an RFC amendment banner).

## Index

RFCs:

| ID | Title | Status |
|----|-------|--------|
| RFC-001 | Structured logging, access/audit logs, and quiet init | Accepted |
| RFC-002 | Tolerate missing trailing slash on TAXII endpoints | Accepted |

ADRs:

| ID | Title | Status |
|----|-------|--------|
| ADR-001 | User identity anonymization in logs and traces | Accepted |
