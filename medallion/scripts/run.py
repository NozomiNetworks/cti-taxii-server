import argparse
import inspect
import logging
import os
import textwrap

from flask import cli as flask_cli
import rollbar

from medallion import (
    __version__, connect_to_backend, init_observability, register_blueprints,
    set_config
)
from medallion.common import (
    APPLICATION_INSTANCE, get_application_instance_config_values
)
import medallion.config
from medallion.log import configure_logging

log = logging.getLogger("medallion")


def _check_auth_source(rollbar_ready: bool) -> None:
    """Report the configured authentication source at startup (RFC-001 §3.5)."""
    if hasattr(APPLICATION_INSTANCE, "auth_backend"):
        return

    if hasattr(APPLICATION_INSTANCE, "users_config"):
        log.warning(
            "Static user credentials are configured in plain text. "
            "Prefer the mongodb auth backend."
        )
        return

    log.error("No authentication source configured; all requests will fail authentication.")
    if rollbar_ready:
        rollbar.report_message(
            "No authentication source configured; all requests will fail authentication.",
            "error",
        )


class NewlinesHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom help formatter to insert newlines between argument help texts.
    """

    def _split_lines(self, text, width):
        text = self._whitespace_matcher.sub(" ", text).strip()
        txt = textwrap.wrap(text, width)
        txt[-1] += "\n"
        return txt


def _get_argparser():
    """Create and return an ArgumentParser for this application."""
    desc = "medallion v{0}".format(__version__)
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=NewlinesHelpFormatter,
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        type=str,
        help="The host to listen on.",
    )

    parser.add_argument(
        "--port",
        default=5000,
        type=int,
        help="The port of the web server.",
    )

    parser.add_argument(
        "--debug-mode",
        default=False,
        action="store_true",
        help="If set, start application in debug mode.",
    )

    parser.add_argument(
        "--log-level",
        default="WARN",
        type=str,
        help="The logging output level for medallion.",
        choices=["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"],
    )

    config_path_group = parser.add_mutually_exclusive_group()
    config_path_group.add_argument(
        "CONFIG_PATH",
        metavar="CONFIG_PATH",
        nargs="?",
        type=str,
        help=inspect.cleandoc("""
            Deprecated argument for specifying a single JSON configuration
            file. Do not specify this and `--conf-file`.
        """),
    )
    config_path_group.add_argument(
        "-c", "--conf-file",
        default=os.environ.get(
            "MEDALLION_CONFFILE", medallion.config.DEFAULT_CONFFILE
        ),
        help=inspect.cleandoc(f"""
            Path to a single configuration file. Defaults to the value of
            the MEDALLION_CONFFILE environment variable or {medallion.config.DEFAULT_CONFFILE}.
        """),
    )
    config_dir_group = parser.add_mutually_exclusive_group()
    config_dir_group.add_argument(
        "--conf-dir",
        default=os.environ.get(
            "MEDALLION_CONFDIR", medallion.config.DEFAULT_CONFDIR
        ),
        help=inspect.cleandoc(f"""
            Path to a directory containing JSON configuration files with names
            ending in .json or .conf. Defaults to the value of the
            MEDALLION_CONFDIR environment variable or {medallion.config.DEFAULT_CONFDIR}.
        """),
    )
    config_dir_group.add_argument(
        "--no-conf-dir",
        action="store_true",
        help=inspect.cleandoc("""
            Disable the use of any configuration directory as described for
            --conf-dir. This may be used to ensure that the default or some
            value from the environment is not used.
        """),
    )
    parser.add_argument(
        "--conf-check", action="store_true",
        help="Evaluate medallion configuration without running the server.",
    )

    return parser


def main():
    medallion_parser = _get_argparser()
    medallion_args = medallion_parser.parse_args()
    # Configuration checking sets up debug logging and does not run the app
    if medallion_args.conf_check:
        medallion_args.log_level = logging.DEBUG
    # Logging is configured once here, on the root logger, so third-party
    # loggers honor --log-level too (RFC-001 §3.1)
    configure_logging(medallion_args.log_level)

    configuration = medallion.config.load_config(
        medallion_args.CONFIG_PATH or medallion_args.conf_file,
        medallion_args.conf_dir if not medallion_args.no_conf_dir else None,
    )

    set_config(APPLICATION_INSTANCE, "users", configuration)
    set_config(APPLICATION_INSTANCE, "taxii", configuration)
    set_config(APPLICATION_INSTANCE, "backend", configuration)
    set_config(APPLICATION_INSTANCE, "auth", configuration)

    APPLICATION_INSTANCE.medallion_backend = connect_to_backend(
        get_application_instance_config_values(APPLICATION_INSTANCE, "backend"))
    rollbar_ready = init_observability(APPLICATION_INSTANCE)
    _check_auth_source(rollbar_ready)
    if (not APPLICATION_INSTANCE.blueprints):
        register_blueprints(APPLICATION_INSTANCE)

    if not medallion_args.conf_check:
        # Container runtimes timestamp stdout themselves; flask's banner is noise (RFC-001 §3.4)
        flask_cli.show_server_banner = lambda *args, **kwargs: None
        APPLICATION_INSTANCE.run(
            host=medallion_args.host,
            port=medallion_args.port,
            debug=medallion_args.debug_mode,
        )


if __name__ == "__main__":
    main()
