# Reviews

Code review records live in this folder.

## Naming

- `<TICKET>-<topic>.md` — per-task or per-PR reviews (e.g. `ENG-1234-session-cache-review.md`).
- `SEC-NNN-<topic>.md` — standing security or architecture review campaigns (e.g.
  `SEC-001-dependency-hygiene-review.md`).

## Format

- A header table: `Reviewer`, `Date`, `Ticket`, `PR`/`Branch`, `Scope`, `Spec` (the RFCs/ADRs
  the change must be coherent with), and `Verdict`.
- Findings numbered and severity-tagged: `### F-1 — <title> (CRITICAL | HIGH | MEDIUM | LOW)`,
  each citing a repo-relative path and quoting the offending code.
- A `## Disposition` table: `| Finding | Decision | Where |`, with decisions like **Fixed**,
  **Recorded**, **Accepted**, **Deferred**.

## Reply protocol

Reviewees reply inline under each finding, as a blockquote:

- `> fix` — will fix.
- `> won't fix: <reason>` — accepted as-is, with the reason recorded.
- `> question` — needs clarification before deciding.

## Completion

When all findings are resolved, set the header-table `Verdict` (or a top status line) to
complete, and fold any resulting decisions into an ADR — or an RFC amendment banner — in the
same change. Update `spec/README.md`'s index in that same change if new documents were created.
