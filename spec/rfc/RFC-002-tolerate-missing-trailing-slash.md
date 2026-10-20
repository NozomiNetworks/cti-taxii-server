# RFC-002 — Tolerate missing trailing slash on TAXII endpoints

| Field         | Value                                            |
|---------------|--------------------------------------------------|
| Status        | Implemented                                    |
| Author        | Federico Maggi                                 |
| Created       | 2026-10-19                                     |
| Related tasks | TIA-NNN (to be filed)                          |
| Scheduled     | Deferral lifted at acceptance — implemented together with RFC-001 |

## 1. Context

Trace analysis (Tempo export, 2026-10-19) shows that virtually every API call reaches the
server as **two HTTP requests**:

1. A request to the URL **without** the trailing slash (e.g.
   `GET /<api_root>/collections/<collection_id>/objects`). No route matches — all TAXII routes
   are declared with a trailing slash (`medallion/views/objects.py`, `collections.py`,
   `manifest.py`, `discovery.py`, `users.py`) — so with Flask's default `strict_slashes=True`
   the server answers **308 Permanent Redirect** in under 1 ms, and the OTel span cannot be
   renamed to a route template (it keeps the concrete path as its name).
2. The client follows the redirect; the real request matches the rule and produces the
   meaningful multi-second span named with the route template.

Consequences: every API call costs two round trips; redirect spans inflate request counts and
skew latency percentiles in dashboards (span metrics); TraceQL/dashboard queries get messy
because span names alternate between template and concrete path for the same logical endpoint.

## 2. Goals

Accept both URL variants directly (single request, one span, uniform route-template naming)
without changing the canonical (slash) URLs. **Implementation is deliberately deferred** — this
RFC records the finding and the decided fix so it is not lost.

## 3. Design

Set `strict_slashes = False` once on the application URL map
(`APPLICATION_INSTANCE.url_map.strict_slashes = False` in `medallion/common.py`) rather than
per-route. Rules ending in `/` then match both variants and stop redirecting; the slash
variants remain the canonical, documented TAXII 2.1 endpoint URLs (accepting both is a
superset, spec-compliant). A side benefit: some HTTP clients mishandle 308 on POST bodies —
that class of problem disappears.

Related to RFC-001 (access logs): once RFC-001 ships, the 308 round trips become visible as
access-log lines; this fix removes them at the source.

## 4. Open Questions

| # | Question | Impact | Status |
|-----|----------|--------|--------|
| OQ-1 | Same export also showed identical span IDs ingested twice (OTLP retry vs Tempo/export artifact). | Dashboards may double-count affected spans | Open |

OQ-1 detail: verification task, not part of the redirect fix — check whether one affected trace
waterfall in the Tempo UI really shows the span twice before touching anything.

## 5. Out of Scope

- Changing client callers (web-app / synchronizers) to request canonical slash URLs.
- Any change to the TAXII endpoint definitions themselves.
