import importlib
import logging
import os
import re
import time
import warnings

from flask import (
    Flask, Response, current_app, g, got_request_exception, json, request
)
from flask_httpauth import HTTPBasicAuth
# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter
)
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import rollbar
import rollbar.contrib.flask
from werkzeug.security import check_password_hash

from .backends import base as mbe_base
from .common import APPLICATION_INSTANCE, MEDIA_TYPE_TAXII_V21
from .exceptions import BackendError, InitializationError, ProcessingError
from .log import anonymize_user
from .version import __version__  # noqa

# Module-level logger
log = logging.getLogger(__name__)

access_log = logging.getLogger("medallion.access")
# Access and audit lines are the product; emit them regardless of the
# (default WARN) root level.
access_log.setLevel(logging.INFO)

# /users/<user_id>/ routes carry the username in the path; it must never be
# logged raw (ADR-001). "reset_password" is a literal endpoint, not a user id.
_USER_ID_PATH = re.compile(r"^(/users/)([^/?]+)([/?].*)?$")


def _anonymized_request_path(path: str) -> str:
    match = _USER_ID_PATH.match(path)
    if match and match.group(2) != "reset_password":
        return f"{match.group(1)}{anonymize_user(match.group(2))}{match.group(3) or ''}"
    return path


def _scrub_span_target(span, status, response_headers):
    """Anonymize username-bearing span attributes before export (ADR-001).

    The WSGI instrumentation records the raw request URI verbatim
    (``http.target``, or ``url.path`` under new semconv); on
    ``/users/<user_id>/`` routes that value is a username. Runs as a
    response hook because the instrumentation re-applies its collected
    attributes after the request hook.
    """
    if not (span and span.is_recording()):
        return
    for attribute in ("http.target", "url.path"):
        raw = span.attributes.get(attribute)
        if raw:
            scrubbed = _anonymized_request_path(raw)
            if scrubbed != raw:
                span.set_attribute(attribute, scrubbed)


auth = HTTPBasicAuth()


def register_access_log_hooks(app):
    """Register the access-log hooks on an application (RFC-001 §3.2)."""
    @app.before_request
    def _start_request_timer():
        g.start_time = time.perf_counter()

    @app.after_request
    def _log_access(response):
        """Emit one access-log line when the request completes."""
        if request.path.rstrip("/") == "/ping":
            return response

        start_time = getattr(g, "start_time", None)
        duration_ms = (time.perf_counter() - start_time) * 1000 if start_time is not None else None

        user = auth.current_user()
        anon_user = anonymize_user(user) if user else None
        span = trace.get_current_span()
        if anon_user and span.is_recording():
            span.set_attribute("user.name", anon_user)

        path = _anonymized_request_path(request.path)
        access_log.info(
            "%s %s", request.method, path,
            extra={
                "event": "access",
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "remote_ip": request.remote_addr,
                "user": anon_user,
            },
        )
        return response

    return app


register_access_log_hooks(APPLICATION_INSTANCE)


def set_config(flask_application_instance, prop_name, config):
    log.debug("Registering medallion {} configuration into {}".format(prop_name, flask_application_instance))

    if not flask_application_instance.debug:
        # Shut up the werkzeug logger; medallion emits its own access log.
        logging.getLogger('werkzeug').setLevel(logging.CRITICAL)

    if prop_name == "taxii":
        if prop_name in config:
            flask_application_instance.taxii_config = config[prop_name]
        else:
            flask_application_instance.taxii_config = {'max_page_size': 100}
        if "interop_requirements" not in flask_application_instance.taxii_config:
            flask_application_instance.taxii_config["interop_requirements"] = False
    elif prop_name == "users":
        if prop_name in config:
            flask_application_instance.users_config = config[prop_name]
    elif prop_name == "auth" and prop_name in config:
        with flask_application_instance.app_context():
            log.debug(
                "Registering medallion users configuration into {}".format(current_app)
            )
            flask_application_instance.auth_backend = connect_to_backend(config[prop_name])
    elif prop_name == "backend":
        if prop_name in config:
            flask_application_instance.backend_config = config[prop_name]
        else:
            raise InitializationError("You did not give backend information in your config.", 408)


def connect_to_backend(config_info, clear_db=False):
    log.debug("Initializing backend configuration using: {}".format(config_info))

    try:
        backend_cls_name = config_info["module_class"]
    except KeyError:
        raise ValueError("No module_class parameter provided for the TAXII server.")

    try:
        backend_mod_name = config_info["module"]
    except KeyError:
        # Handle configurations which only specify a backend class name
        try:
            backend_cls = mbe_base.BackendRegistry.get(backend_cls_name)
        except KeyError as exc:
            msg = "Unknown backend {!r}".format(backend_cls_name)
            log.error(msg)
            raise ValueError(msg) from exc
    else:
        # Handle configurations which specify a module to load
        warnings.warn(
            "Backend module paths in configuration will be removed in future. "
            "Simply use the backend class name in 'module_class' or add a "
            "medallion.backends entrypoint for more exotic implementations.",
            DeprecationWarning
        )
        try:
            backend_mod = importlib.import_module(backend_mod_name)
            backend_cls = getattr(backend_mod, backend_cls_name)
        except (ImportError, AttributeError) as exc:
            log.error(
                "Failed to load backend %r from %r",
                backend_cls_name, backend_mod_name,
            )
            raise exc
        else:
            log.debug(
                "Instantiating medallion backend with %r from %r",
                backend_cls_name, backend_mod_name,
            )

    # Finally, instantiate the backend class with the configuration passed in
    try:
        config_info["clear_db"] = clear_db
        return backend_cls(**config_info)
    except BaseException as exc:
        log.error("Failed to instantiate %r: %s", backend_cls_name, exc)
        raise exc


def register_blueprints(flask_application_instance):
    from medallion.views import (
        collections, discovery, healthcheck, manifest, objects, users
    )

    with flask_application_instance.app_context():
        log.debug("Registering medallion blueprints into {}".format(current_app))
        current_app.register_blueprint(collections.collections_bp)
        current_app.register_blueprint(discovery.discovery_bp)
        current_app.register_blueprint(manifest.manifest_bp)
        current_app.register_blueprint(objects.objects_bp)
        current_app.register_blueprint(healthcheck.healthecheck_bp)
        current_app.register_blueprint(users.users_bp)


@auth.verify_password
def verify_basic_auth(username, password):
    if hasattr(current_app, "auth_backend"):
        password_hash = current_app.auth_backend.get_password_hash(username)
        return (
            False if password_hash is None else check_password_hash(password_hash, password)
        )

    if hasattr(current_app, "users_config"):
        return current_app.users_config.get(username) == password

    logging.critical("Authentication backend is not configured properly.")
    return False


@APPLICATION_INSTANCE.errorhandler(500)
def handle_error(error):
    e = {
        "title": "InternalError",
        "http_status": "500",
        "description": str(error),
    }
    return Response(
        response=json.dumps(e),
        status=500,
        mimetype=MEDIA_TYPE_TAXII_V21,
    )


@APPLICATION_INSTANCE.errorhandler(ProcessingError)
def handle_processing_error(error):
    e = {
        "title": str(error.__class__.__name__),
        "http_status": str(error.status),
        "description": str(error),
    }
    return Response(
        response=json.dumps(e),
        status=error.status,
        headers=getattr(error, "headers", None),
        mimetype=MEDIA_TYPE_TAXII_V21,
    )


@APPLICATION_INSTANCE.errorhandler(BackendError)
def handle_backend_error(error):
    e = {
        "title": str(error.__class__.__name__),
        "http_status": str(error.status),
        "description": str(error),
    }
    return Response(
        response=json.dumps(e),
        status=error.status,
        mimetype=MEDIA_TYPE_TAXII_V21,
    )


def init_observability(app: Flask) -> bool:
    """Initialize tracing and error reporting exactly once.

    Args:
        app (Flask): The Flask application instance.
    Returns:
        bool: Whether Rollbar error reporting is active.
    """
    with app.app_context():
        init_otel(app)
        return init_rollbar(app)


def init_otel(app: Flask):
    # OpenTelemetry initialization
    otel_endpoint = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')
    if otel_endpoint:
        # Configure the resource
        resource = Resource.create({
            "service.name": os.environ.get('OTEL_SERVICE_NAME', 'ti-taxii-server'),
            "service.version": os.environ.get("OTEL_SERVICE_VERSION", "default"),
        })

        # Create tracer provider
        otel_endpoint_traces = f"{otel_endpoint}/v1/traces"
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)

        # Create OTLP exporter
        otlp_exporter = OTLPSpanExporter(endpoint=otel_endpoint_traces)

        # Create span processor
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

        # Instrument Flask
        FlaskInstrumentor().instrument_app(
            app,
            tracer_provider=tracer_provider,
            excluded_urls="/ping",
            response_hook=_scrub_span_target,
        )


def init_rollbar(app: Flask) -> bool:
    """Initialize Rollbar error reporting when configured.

    Args:
        app (Flask): The Flask application instance.
    Returns:
        bool: Whether Rollbar is active.
    """
    rollbar_token = os.environ.get('ROLLBAR_TOKEN')
    if rollbar_token:
        rollbar.init(
            rollbar_token,
            environment=os.environ.get('ENVIRONMENT', 'development'),
            root=os.path.dirname(os.path.realpath(__file__)),
            allow_logging_basic_config=False
        )

        got_request_exception.connect(rollbar.contrib.flask.report_exception, app)
        return True
    return False
