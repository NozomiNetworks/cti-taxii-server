import importlib
import logging
import os
import random

import rollbar
import rollbar.contrib.flask
from flask import Flask, Response, current_app, json, got_request_exception, g
from flask_httpauth import HTTPBasicAuth
# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .exceptions import BackendError, ProcessingError
from .version import __version__  # noqa
from .views import MEDIA_TYPE_TAXII_V21

# Console Handler for medallion messages
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("[%(name)s] [%(levelname)-8s] [%(asctime)s] %(message)s"))

# Module-level logger
log = logging.getLogger(__name__)
log.addHandler(ch)

auth = HTTPBasicAuth()


def set_config(flask_application_instance, prop_name, config):
    with flask_application_instance.app_context():
        log.debug("Registering medallion {} configuration into {}".format(prop_name, current_app))
        if prop_name == "taxii":
            try:
                flask_application_instance.taxii_config = config[prop_name]
            except KeyError:
                flask_application_instance.taxii_config = {'max_page_size': 100}
        elif prop_name == "users":
            try:
                flask_application_instance.users_backend = config[prop_name]
            except KeyError:
                log.warning("You did not give user information in your config.")
                log.warning("We are giving you the default user information of:")
                log.warning("User = user")
                log.warning("Pass = pass")
                flask_application_instance.users_backend = {"user": "pass"}
        elif prop_name == "backend":
            try:
                flask_application_instance.medallion_backend = connect_to_backend(config[prop_name])
            except KeyError:
                log.warning("You did not give backend information in your config.")
                log.warning("We are giving medallion the default settings,")
                log.warning("which includes a data file of 'default_data.json'.")
                log.warning("Please ensure this file is in your CWD.")
                back = {'module': 'medallion.backends.memory_backend', 'module_class': 'MemoryBackend', 'filename': None}
                flask_application_instance.medallion_backend = connect_to_backend(back)


def connect_to_backend(config_info):
    log.debug("Initializing backend configuration using: {}".format(config_info))

    if "module" not in config_info:
        raise ValueError("No module parameter provided for the TAXII server.")
    if "module_class" not in config_info:
        raise ValueError("No module_class parameter provided for the TAXII server.")

    try:
        module = importlib.import_module(config_info["module"])
        module_class = getattr(module, config_info["module_class"])
        log.debug("Instantiating medallion backend with {}".format(module_class))
        return module_class(**config_info)
    except Exception as e:
        log.error("Unknown backend for TAXII server. {} ".format(str(e)))
        raise


def register_blueprints(flask_application_instance):
    from medallion.views import collections
    from medallion.views import discovery
    from medallion.views import manifest
    from medallion.views import objects

    with flask_application_instance.app_context():
        log.debug("Registering medallion blueprints into {}".format(current_app))
        current_app.register_blueprint(collections.collections_bp)
        current_app.register_blueprint(discovery.discovery_bp)
        current_app.register_blueprint(manifest.manifest_bp)
        current_app.register_blueprint(objects.objects_bp)


@auth.get_password
def get_pwd(username):
    if username in current_app.users_backend:
        return current_app.users_backend.get(username)
    return None


def handle_error(error):
    e = {
        "title": "InternalError",
        "http_status": "500",
        "description": str(error.args[0]),
    }
    return Response(
        response=json.dumps(e),
        status=500,
        mimetype=MEDIA_TYPE_TAXII_V21,
    )


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
        FlaskInstrumentor().instrument_app(app, tracer_provider=tracer_provider, excluded_urls="/ping")


def init_rollbar(app: Flask):
    rollbar_token = os.environ.get('ROLLBAR_TOKEN')
    if rollbar_token:
        rollbar.init(
            rollbar_token,
            environment=os.environ.get('ENVIRONMENT', 'development'),
            root=os.path.dirname(os.path.realpath(__file__)),
            allow_logging_basic_config=False
        )

        got_request_exception.connect(rollbar.contrib.flask.report_exception, app)


def set_trace_id():
    g.trace_id = "{:08x}".format(random.randrange(0, 0x100000000))


def log_after_request(response):
    current_app.logger.info(response.status)
    return response


def set_taxii_config(flask_application_instance, config_info):
    with flask_application_instance.app_context():
        log.debug("Registering medallion taxii configuration into {}".format(current_app))
        flask_application_instance.taxii_config = config_info


def set_backend_config(flask_application_instance, config_info):
    with flask_application_instance.app_context():
        log.debug("Registering medallion_backend into {}".format(current_app))
        current_app.medallion_backend = connect_to_backend(config_info)


def register_error_handlers(app):
    app.register_error_handler(500, handle_error)
    app.register_error_handler(ProcessingError, handle_processing_error)
    app.register_error_handler(BackendError, handle_backend_error)


def create_app():
    app = Flask(__name__)

    app.logger = logging.getLogger('medallion-app')
    app.logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    app.logger.addHandler(handler)

    if not app.debug:
        # Shut up the werkzeug logger unless debugging.
        logging.getLogger('werkzeug').setLevel(logging.CRITICAL)

    _ = app.before_request(set_trace_id)
    _ = app.after_request(log_after_request)

    with app.app_context():
        init_otel(app)
        init_rollbar(app)

    register_error_handlers(app)

    return app
