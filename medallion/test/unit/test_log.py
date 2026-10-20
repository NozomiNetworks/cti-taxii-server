import json
import logging
from unittest import mock

from flask import Flask
import pytest

from medallion import _anonymized_request_path, register_access_log_hooks
from medallion.log import (
    JsonFormatter, TextFormatter, anonymize_user, configure_logging
)

APPLICATION_INSTANCE_LOG_ACCESS = logging.getLogger("medallion.access")


def _medallion_root_handlers() -> list:
    return [
        handler for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, (JsonFormatter, TextFormatter))
    ]


def test_configure_logging_defaults_to_json(monkeypatch):
    # The service only runs containerized; JSON is the default (RFC-001 §4,
    # amended), LOG_FORMAT=text selects the human format.
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    configure_logging(logging.INFO)

    handlers = _medallion_root_handlers()
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, JsonFormatter)


def test_configure_logging_text_opt_in(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    configure_logging(logging.INFO)

    handlers = _medallion_root_handlers()
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, TextFormatter)


def test_anonymize_user_rejects_none():
    # ADR-001 makes this the single mandatory path; None must not raise.
    assert anonymize_user(None) == ""


def test_access_and_audit_loggers_emit_at_default_root_level():
    # The root logger defaults to WARN (run.py --log-level); access and audit
    # lines are the product and must not be gated by it (RFC-001 Goals 2-3).
    from medallion.views.users import audit_log

    assert APPLICATION_INSTANCE_LOG_ACCESS.level == logging.INFO
    assert audit_log.level == logging.INFO


def test_anonymized_request_path_masks_user_id():
    assert _anonymized_request_path("/users/john.smith/") == "/users/jo****/"
    assert _anonymized_request_path("/users/john.smith") == "/users/jo****"
    assert _anonymized_request_path("/users/john?x=1") == "/users/jo****?x=1"
    assert _anonymized_request_path("/users/reset_password/") == "/users/reset_password/"
    assert _anonymized_request_path("/taxii1/collections/x/objects/") == "/taxii1/collections/x/objects/"


class _FakeSpan:
    """Minimal recording-span stand-in for hook tests."""

    def __init__(self, attributes):
        self.attributes = attributes
        self.set = {}

    def is_recording(self):
        return True

    def set_attribute(self, key, value):
        self.set[key] = value


def test_otel_exported_span_target_is_scrubbed():
    # End-to-end against the real instrumentation: the WSGI collector records
    # http.target from the raw request URI; the response hook must mask the
    # username before export (ADR-001).
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        SimpleSpanProcessor, SpanExporter, SpanExportResult
    )
    from opentelemetry.trace import SpanKind

    from medallion import _scrub_span_target

    class ListExporter(SpanExporter):
        spans = []

        def export(self, spans):
            ListExporter.spans.extend(spans)
            return SpanExportResult.SUCCESS

    exporter = ListExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = Flask("otel-scrub-test")
    app.url_map.strict_slashes = False
    FlaskInstrumentor().instrument_app(
        app, tracer_provider=provider,
        response_hook=_scrub_span_target,
    )
    app._is_instrumented_by_opentelemetry = True

    @app.route("/users/<user_id>/", methods=["PUT"])
    def put_user(user_id):
        return "ok"

    app.test_client().put("/users/john.smith/")

    server_spans = [s for s in exporter.spans if s.kind == SpanKind.SERVER]
    assert server_spans, "no server span was exported"
    assert server_spans[-1].attributes["http.target"] == "/users/jo****/"


def test_scrub_span_target_masks_user_id_paths():
    from medallion import _scrub_span_target

    span = _FakeSpan({
        "http.target": "/users/john.smith/?limit=5",
        "url.path": "/users/john.smith/",
    })
    _scrub_span_target(span, "200 OK", [])

    assert span.set["http.target"] == "/users/jo****/?limit=5"
    assert span.set["url.path"] == "/users/jo****/"


def test_scrub_span_target_leaves_other_paths():
    from medallion import _scrub_span_target

    attributes = {"http.target": "/taxii1/collections/x/objects/", "url.path": "/taxii1/collections/x/objects/"}
    span = _FakeSpan(attributes)
    _scrub_span_target(span, "200 OK", [])

    assert span.set == {}
    assert span.attributes == attributes


def test_scrub_span_target_ignores_non_recording_span():
    from medallion import _scrub_span_target

    class _NonRecording:
        def is_recording(self):
            return False

        attributes = {"http.target": "/users/john.smith/"}

    span = _NonRecording()
    _scrub_span_target(span, "200 OK", [])

    assert span.attributes["http.target"] == "/users/john.smith/"


@pytest.mark.parametrize("value,expected", (
    ("john.smith@metabase.com", "jo****@me****"),
    ("ab@example.com", "****@ex****"),
    ("a@b.c", "****@b.****"),
    ("user@", "us****@"),
    ("@domain.com", "@do****"),
    ("admin", "ad****"),
    ("ab", "****"),
    ("a", "****"),
    ("", ""),
    ("josé@example.com", "jo****@ex****"),
    ("用户名", "用户****"),
))
def test_anonymize_user_binding_vectors(value, expected):
    # Binding vectors from ADR-001: any change here is a spec change.
    assert anonymize_user(value) == expected


def _make_record(extra):
    record = logging.LogRecord(
        name="medallion.test", level=logging.INFO, pathname=__file__,
        lineno=1, msg="message text", args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_record_fields():
    record = _make_record({"event": "access", "status": 200, "user": "no****"})
    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "medallion.test"
    assert payload["message"] == "message text"
    assert payload["event"] == "access"
    assert payload["status"] == 200
    assert payload["user"] == "no****"
    # ts is ISO 8601 UTC with microsecond precision
    assert payload["ts"].endswith("Z")
    assert len(payload["ts"]) == 27
    assert "exc_info" not in payload


def test_json_formatter_single_line():
    record = _make_record({"event": "access"})
    rendered = JsonFormatter().format(record)

    assert "\n" not in rendered


def test_json_formatter_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = _make_record({})
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exc_info"]


def test_text_formatter_appends_extras():
    record = _make_record({"event": "audit", "outcome": 201})
    rendered = TextFormatter("[%(name)s] [%(levelname)-8s] [%(asctime)s] %(message)s").format(record)

    assert "message text" in rendered
    assert "event=audit" in rendered
    assert "outcome=201" in rendered


def test_text_formatter_without_extras():
    record = _make_record({})
    rendered = TextFormatter("[%(name)s] [%(levelname)-8s] [%(asctime)s] %(message)s").format(record)

    assert rendered.endswith("message text")


def test_access_log_emitted_at_request_end(caplog):
    # A dedicated app keeps the shared APPLICATION_INSTANCE singleton untouched
    # (a real request on it would lock out later register_blueprint calls).
    app = Flask("access-log-test")
    register_access_log_hooks(app)

    @app.route("/hello")
    def hello():
        return "ok"

    client = app.test_client()

    with caplog.at_level(logging.INFO, logger="medallion.access"):
        response = client.get("/hello")

    records = [r for r in caplog.records if r.name == "medallion.access"]
    assert len(records) == 1
    payload = json.loads(JsonFormatter().format(records[0]))

    assert response.status_code == 200
    assert payload["event"] == "access"
    assert payload["method"] == "GET"
    assert payload["path"] == "/hello"
    assert payload["status"] == 200
    assert isinstance(payload["duration_ms"], float)
    assert payload["user"] is None


def test_access_log_skips_ping_variants(caplog):
    app = Flask("access-log-test")
    # Mirror the production URL map (RFC-002) so /ping/ resolves directly
    app.url_map.strict_slashes = False
    register_access_log_hooks(app)

    @app.route("/ping")
    def ping():
        return "pong"

    client = app.test_client()

    with caplog.at_level(logging.INFO, logger="medallion.access"):
        assert client.get("/ping").status_code == 200
        assert client.get("/ping/").status_code == 200

    assert [r for r in caplog.records if r.name == "medallion.access"] == []


def test_audit_record_fields(caplog):
    from medallion.views.users import _audit

    with mock.patch("medallion.views.users.auth") as mock_auth:
        mock_auth.current_user.return_value = "admin_user"

        with caplog.at_level(logging.INFO, logger="medallion.audit"):
            _audit("create_user", "target_user", 201)

    records = [r for r in caplog.records if r.name == "medallion.audit"]
    assert len(records) == 1
    payload = json.loads(JsonFormatter().format(records[0]))

    assert payload["event"] == "audit"
    assert payload["action"] == "create_user"
    assert payload["actor"] == "ad****"
    assert payload["target"] == anonymize_user("target_user")
    assert "target_user" not in json.dumps(payload)
    assert "admin_user" not in json.dumps(payload)
    assert payload["outcome"] == 201


@pytest.mark.parametrize("rollbar_ready,expect_report", ((True, 1), (False, 0)))
def test_check_auth_source_no_auth_source(rollbar_ready, expect_report, caplog):
    from medallion.scripts import run as run_module

    app = Flask("posture-test")
    with mock.patch.object(run_module, "APPLICATION_INSTANCE", app), mock.patch(
        "medallion.scripts.run.rollbar"
    ) as mock_rollbar, caplog.at_level(logging.ERROR):
        run_module._check_auth_source(rollbar_ready)

    assert mock_rollbar.report_message.call_count == expect_report
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_check_auth_source_static_users(caplog):
    from medallion.scripts import run as run_module

    app = Flask("posture-test")
    app.users_config = {"admin": "Password0"}
    with mock.patch.object(run_module, "APPLICATION_INSTANCE", app), caplog.at_level(logging.WARNING):
        run_module._check_auth_source(rollbar_ready=False)

    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_check_auth_source_auth_backend_silent(caplog):
    from medallion.scripts import run as run_module

    app = Flask("posture-test")
    app.auth_backend = object()
    with mock.patch.object(run_module, "APPLICATION_INSTANCE", app), caplog.at_level(logging.DEBUG):
        run_module._check_auth_source(rollbar_ready=True)

    assert caplog.records == []
