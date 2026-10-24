"""Private demo logs must not contain conversation or provider payloads."""

import io
import logging

import pytest
import structlog
from aegra_api.settings import settings
from aegra_api.utils.setup_logging import get_logging_config

from out_of_frame.demo.logging import PrivateErrors, install

MARKER = "PRIVATE_ADDRESS_OR_SOURCE_TEXT"


def test_error_logs_drop_source_text_and_exception_payloads():
    record = logging.LogRecord(
        "out_of_frame.geocoding",
        logging.WARNING,
        __file__,
        1,
        "request failed: %s",
        (MARKER,),
        (ValueError, ValueError(MARKER), None),
    )
    assert PrivateErrors().filter(record)
    assert MARKER not in record.getMessage()
    assert record.exc_info is None


def test_transport_logs_do_not_reveal_an_address():
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1, "GET https://nominatim/search?q=%s", (MARKER,), None
    )
    assert PrivateErrors().filter(record)
    assert MARKER not in record.getMessage()


@pytest.mark.parametrize("mode", ["LOCAL", "PRODUCTION"])
def test_installed_filter_protects_formatted_logs(monkeypatch, mode):
    monkeypatch.setattr(settings.app, "ENV_MODE", mode)
    formatter_options = get_logging_config()["formatters"]["default"].copy()
    formatter_options.pop("()")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(**formatter_options))
    monkeypatch.setattr(logging.getLogger(), "handlers", [handler])
    for name in ("httpx", "httpcore", "urllib3", "anthropic", "tavily", "sqlalchemy"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "level", logger.level)
    install()

    logger = logging.getLogger("out_of_frame.triage")
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    logger.info("model answer: %s", MARKER)
    logger.debug("request: %s", MARKER)
    assert not output.getvalue()
    logger.warning("source failed", extra={"address": MARKER, "source": {"text": MARKER}})
    # Aegra merges context after the logging filter, before rendering stdlib records.
    with structlog.contextvars.bound_contextvars(address=MARKER, source={"text": MARKER}):
        logger.warning("context-bound source failed")
    try:
        raise ValueError(MARKER)
    except ValueError:
        logger.exception("source failed: %s", MARKER, stack_info=True)

    logging.getLogger("httpx").warning("request failed: %s", MARKER)
    structured = structlog.wrap_logger(
        logging.getLogger("aegra_api.worker"),
        processors=[
            *formatter_options["foreign_pre_chain"],
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    with structlog.contextvars.bound_contextvars(address=MARKER):
        structured.error("run failed", error=MARKER, input=MARKER, exc_info=True)
    rendered = output.getvalue()
    assert MARKER not in rendered
    assert "Traceback" not in rendered
    assert rendered.count("Demo operation failed") == 5
