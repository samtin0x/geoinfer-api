import logging
import sys
import structlog
from fastapi import Request
from structlog.stdlib import ProcessorFormatter

# Remove AppSettings import from top to avoid circular import


def get_client_ip(request: Request) -> str:
    if "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"]
    elif request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"  # localhost for development


def add_request_info(
    logger: structlog.BoundLogger, method_name: str, event_dict: dict
) -> dict:
    context_vars = structlog.contextvars.get_contextvars()
    ip_address = context_vars.get("ip_address")
    if ip_address:
        event_dict["ip_address"] = ip_address
    return event_dict


def setup_logging(is_production: bool = False):
    """Setup structlog configuration with different formats for dev/prod."""
    # Use DEBUG level in development, INFO in production
    log_level = logging.INFO  # if is_production else logging.DEBUG

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    shared_processors: list = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        add_request_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.handlers = []

    # Choose formatter based on environment
    if is_production:
        # JSON format for production (structured logging)
        formatter = ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(sort_keys=False),
        )
    else:
        # Human-readable format for development
        formatter = ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True, pad_event=8),
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    logging.getLogger("uvicorn").handlers = []
    logging.getLogger("uvicorn.access").handlers = []

    # Disable verbose Stripe logging (only show warnings/errors)
    logging.getLogger("stripe").setLevel(logging.WARNING)

    logger = structlog.get_logger()
    return logger


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance with optional name."""
    return structlog.get_logger(name)
