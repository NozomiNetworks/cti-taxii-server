# RFC-001 — Structured logging, access/audit logs, and quiet init

| Field         | Value                          |
|---------------|--------------------------------|
| Status        | Implemented                    |
| Author        | Federico Maggi                 |
| Created       | 2026-10-19                     |
| Related tasks | TIA-NNN (to be filed)          |

## 1. Context

The server's observability today:

- **Logging** is plain stdlib `logging` with one human-readable formatter attached at import
  time (`medallion/__init__.py`, module-level handler). No structured output; `--log-level`
  (`medallion/scripts/run.py`) applies only to the `medallion` logger, not the root, so
  third-party loggers bypass it.
- **No access logs exist**: the werkzeug logger is silenced unless debug
  (`medallion/__init__.py`, `set_config`), and nothing else records requests.
- **OTel traces are live** (`init_otel`, `medallion/__init__.py`): when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set, one server span per request is exported over OTLP HTTP
  with `http.method`, `http.route`, `http.status_code`, and duration. Spans carry no user
  identity. There is no metrics SDK and no metrics export.
- **Startup noise**: `main()` calls `set_config` four times (users, taxii, backend, auth) and
  every call re-runs `init_otel`/`init_rollbar` and adds another StreamHandler — producing ×3
  "Rollbar already initialized", "Overriding of current TracerProvider is not allowed",
  "Attempting to instrument Flask app while already instrumented", plus the Flask server banner
  and the "You did not give user information" warning that fires on every boot even when the
  mongodb auth backend is configured.

Why now: the goal is better o11y — machine-parsable logs for Loki, and per-endpoint API access
and performance dashboards in Grafana — plus a startup that surfaces real signal instead of
repeated init warnings.

## 2. Goals

1. JSON structured logging, opt-in, **zero new dependencies**.
2. One-line access log emitted at the **end** of each request with status code, duration, and
   authenticated user.
3. Audit log for the users API.
4. Quiet startup: OTel/Rollbar initialize exactly once; Flask banner suppressed; handler
   accumulation removed.
5. Auth-posture logging: WARN when static users are configured; ERROR + Rollbar notification
   when no auth source exists at all.
6. Trace spans carry the authenticated user.
7. **No full usernames anywhere in logs or spans** — identities are anonymized at
   field-construction time (§3.6).

**Non-goals:** a Prometheus `/metrics` endpoint (Tempo span metrics cover the dashboards);
removing the static-users fallback auth mode; log shipping/retention/dashboards provisioning
(deployment side); changes to the Rollbar client configuration.

## 3. Design

### 3.1 JSON formatter

Custom `logging.Formatter` subclass in a new `medallion/log.py`. When env `LOG_FORMAT=json`,
every record renders as a single-line JSON object (field contract in §4); otherwise the current
human format is kept. `run.py` configures the **root logger** once (formatter + handler +
level), so `--log-level` governs third-party loggers too. No new dependency — stdlib `json`
only.

### 3.2 Access log (and span enrichment) — one hook

A single `after_request` hook (paired with `before_request` storing `time.perf_counter()` on
`flask.g`):

- emits one line via the `medallion.access` logger: `event=access`, `method`, `path`,
  `status`, `duration_ms`, `remote_ip`, `user` (from `auth.current_user()`; `null` when
  anonymous, anonymized per §3.6). `/ping` is skipped. Werkzeug stays silenced — this replaces
  it.
- sets the `user.name` attribute on the active OTel span (`trace.get_current_span()`) to the
  **anonymized** identity (§3.6), so Tempo carries identity too. Dashboards use Tempo span
  metrics (RED) for performance and the JSON access log in Loki for access/audit. No Prometheus
  endpoint.

### 3.3 Users API audit log

Dedicated `medallion.audit` logger. On `POST /users/` (medallion/views/users.py), log
`event=audit`, `action=create_user`, `actor` (calling admin), `target` (the new user's `_id`),
`outcome` (HTTP status). `actor` and `target` are usernames — anonymize both per §3.6.
**Never** log request-body fields (`password`, `password_hash`). Audit lines flow through the
same handlers/formatters — structured fields in JSON mode, `key=value` extras appended in human
mode.

### 3.4 Quiet init

- Extract `init_otel` + `init_rollbar` into a single `init_observability(app)` called **once**
  from `run.py:main()` after config load; `set_config` keeps only config concerns. Kills the
  ×3 warnings without changing behavior (first provider wins today, so traces are unaffected).
- Remove the per-`set_config` handler additions on `medallion-app`; logging is centralized in
  `run.py` (§3.1).
- Suppress the Flask server banner (`flask.cli.show_server_banner` no-op) — container runtimes
  already timestamp stdout.
- Remove the unused dependency `opentelemetry-instrumentation-sqlalchemy` (`setup.py`; never
  referenced in code — the backend is pymongo).

### 3.5 Auth posture logging (decided)

Evaluated in `run.py:main()` after config load and after `init_observability`:

| Auth state at startup | Behavior |
|---|---|
| mongodb auth backend configured | silent |
| no backend, static `users` map present | WARN: static plaintext credentials in config; prefer the mongodb auth backend |
| neither | ERROR ("no authentication source configured — all requests will fail auth") **plus** `rollbar.report_message(..., level="error")` so the deployment gets notified |

The old "You did not give user information" warning is removed; it fired in the healthy
mongodb-backend case, which is precisely the state that should be silent.

### 3.6 User identity anonymization

Usernames are PII: logs and spans must never carry a full username. Anonymization happens at
**field-construction time** — a helper (`anonymize_user` in `medallion/log.py`) is the only
path by which a username may reach a log record or a span attribute. Callers pass the raw
username to the helper and log/attach only what it returns; raw values never enter the record.

Algorithm (deterministic, lossy, rune-safe — Python `str` slicing is codepoint-based, which
satisfies this):

```
mask(value):                      # mask one identifier or one email part
    if value == "":  return ""    # empty stays empty (matters for malformed emails)
    if len(value) <= 2:  return "****"
    return value[:2] + "****"     # keep first 2 chars, fixed mask

anonymize_user(value):
    if value == "":  return ""    # empty stays empty
    if "@" in value:              # treat as email: mask local part and domain separately
        local, domain = value.split("@", 1)
        return mask(local) + "@" + mask(domain)
    return mask(value)
```

Properties: fixed mask string `****` (constant-width — length is not leaked beyond the 2-char
prefix); email local part and domain masked independently so the domain shape (`@`, subdomains)
stays recognizable while content is hidden; malformed emails (`user@`, `@domain.com`) keep their
empty side untouched; unicode-safe.

The implementing change must port the following vectors as pytest cases (regression test —
every one of these is a binding behavior):

| input | expected |
|---|---|
| `john.smith@metabase.com` | `jo****@me****` |
| `ab@example.com` | `****@ex****` |
| `a@b.c` | `****@b.****` |
| `user@` | `us****@` |
| `@domain.com` | `@do****` |
| `admin` | `ad****` |
| `ab` | `****` |
| `a` | `****` |
| `` (empty) | `` (empty) |
| `josé@example.com` | `jo****@ex****` |
| `用户名` | `用户****` |

Audit trail note: masking is lossy and irreversible by design. If investigations later need
stable pseudonymous correlation, revisit with a keyed-hash approach — do not add it now.

## 4. API / Contract

**JSON log record** (all records; `LOG_FORMAT=json`):

| Field | Type | Present | Notes |
|---|---|---|---|
| `ts` | string | always | ISO 8601 UTC, microsecond precision |
| `level` | string | always | logging level name (e.g. `WARNING`) |
| `logger` | string | always | logger name (e.g. `medallion.access`) |
| `message` | string | always | rendered message |
| `event` | string | access/audit | discriminator: `access` / `audit` |
| `method`, `path`, `remote_ip` | string | access | |
| `user` | string \| null | access | anonymized username (§3.6); `null` when anonymous |
| `status` | int | access | response status code |
| `duration_ms` | float | access | end-of-request wall time |
| `action`, `actor`, `target` | string | audit | audit event identity; `actor`/`target` anonymized (§3.6) |
| `outcome` | int | audit | resulting HTTP status |

Examples (one line each):

```json
{"ts": "2026-10-18T23:47:59.774Z", "level": "INFO", "logger": "medallion.access", "event": "access",
 "method": "GET", "path": "/taxii1/collections/", "status": 200, "duration_ms": 12.3, "remote_ip": "10.0.0.1", "user": "no****"}
```

```json
{"ts": "2026-10-18T23:48:01.100Z", "level": "INFO", "logger": "medallion.audit", "event": "audit",
 "action": "create_user", "actor": "no****", "target": "us****", "outcome": 201}
```

**Environment variables:** `LOG_FORMAT=json` enables JSON records; unset or any other value
keeps the human format.

## 5. Open Questions

| # | Question | Impact | Status |
|-----|----------|--------|--------|
| OQ-1 | Deployment config passes `serverselectiontryonce` in the Mongo URI → pymongo `UserWarning` at startup. | One warning line at startup | Open |

OQ-1 detail: fix in deployment config (drop the option) or filter the warning in code — decide
before implementation.

## 6. Out of Scope

- Prometheus `/metrics` endpoint — revisit only if Tempo metrics-generator proves insufficient.
- The static-users fallback auth behavior itself — only the startup logging posture changes.
- Log shipping, retention, and Grafana/Tempo/Loki provisioning — deployment configuration.
- OTel metrics SDK (no `MeterProvider`); this change covers traces + logs only.
