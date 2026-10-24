"""Keep exception payloads and external-service errors out of private demo logs."""

import datetime as dt
import logging

from structlog.stdlib import ProcessorFormatter

PRIVATE_ERROR = "Demo operation failed; inspect status and fixed failure codes"


class PrivateErrors(logging.Filter):
    def filter(self, record):
        private = record.name.startswith(("out_of_frame", "aegra_api"))
        transport = record.name.startswith(
            ("httpx", "httpcore", "urllib3", "anthropic", "tavily", "sqlalchemy")
        )
        # Normal agent diagnostics can include model answers and grounding errors.
        if private and record.levelno < logging.WARNING:
            return False
        if (private and record.levelno >= logging.WARNING) or transport or record.exc_info:
            record.msg = {"event": PRIVATE_ERROR} if isinstance(record.msg, dict) else PRIVATE_ERROR
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            record._demo_private = True
        return True


def private_event(logger, method, event):
    """Discard extra fields after Aegra adds stdlib extras and bound context."""
    record = event["_record"]
    if not getattr(record, "_demo_private", False):
        return event
    return {
        "_record": record,
        "_from_structlog": event["_from_structlog"],
        "event": PRIVATE_ERROR,
        "level": record.levelname.lower(),
        "logger": record.name,
        "timestamp": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
    }


def install():
    for name in ("httpx", "httpcore", "urllib3", "anthropic", "tavily", "sqlalchemy"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        handler.addFilter(PrivateErrors())
        formatter = handler.formatter
        if isinstance(formatter, ProcessorFormatter) and private_event not in formatter.processors:
            formatter.processors = (private_event, *formatter.processors)
