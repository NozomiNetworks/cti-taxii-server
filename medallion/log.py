"""Logging setup: user anonymization (ADR-001) and record formatters (RFC-001)."""
from datetime import datetime, timezone
import json
import logging
import os

# Standard LogRecord attributes; anything else on the record is caller-provided
# extra context and is rendered as a first-class field.
_RECORD_ATTRS = frozenset((
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "taskName", "thread", "threadName",
))


def _mask(value: str) -> str:
    if value == "":
        return ""
    if len(value) <= 2:
        return "****"
    return value[:2] + "****"


def anonymize_user(value: str) -> str:
    """Anonymize a username or email for logging and tracing.

    The mask is deterministic and lossy: at most the first two characters
    survive, the rest is replaced by a fixed-width run of asterisks so no
    length information leaks. Email-shaped values (containing "@") keep their
    recognizable shape by masking local part and domain independently. This
    function is the only permitted path by which a username may reach a log
    record or a span attribute (ADR-001).

    Args:
        value (str): The username or email to anonymize.
    Returns:
        str: The anonymized value; empty when the input is empty or None.
    """
    if not value:
        return ""
    if "@" in value:
        local, domain = value.split("@", 1)
        return f"{_mask(local)}@{_mask(domain)}"
    return _mask(value)


class JsonFormatter(logging.Formatter):
    """Render a record as a single-line JSON object (RFC-001 §4).

    Caller-provided extras become top-level fields so that log queries can
    filter on them directly.
    """

    def format(self, record):
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable format; caller-provided extras are appended as key=value."""

    def format(self, record):
        message = super().format(record)
        extras = [
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in _RECORD_ATTRS and not key.startswith("_")
        ]
        if extras:
            message = f"{message} [{', '.join(extras)}]"
        return message


def configure_logging(level):
    """Configure the root logger once: one console handler, JSON or text per LOG_FORMAT.

    Re-invocations replace the medallion handler instead of accumulating
    duplicates (RFC-001 §3.4).

    Args:
        level (str | int): The level for the root logger.
    """
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "") == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("[%(name)s] [%(levelname)-8s] [%(asctime)s] %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing.formatter, (JsonFormatter, TextFormatter)):
            root.removeHandler(existing)
    root.setLevel(level)
    root.addHandler(handler)
