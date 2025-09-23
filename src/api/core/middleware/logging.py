import time

import structlog
from src.utils.logger import get_client_ip, get_logger
from fastapi import Request

logger = get_logger(__name__)


async def logging_middleware(request: Request, call_next):
    start_time = time.time()

    if request.url.path == "/health":
        return await call_next(request)

    structlog.contextvars.clear_contextvars()
    ip_address = get_client_ip(request)
    structlog.contextvars.bind_contextvars(
        ip_address=ip_address,
        method=request.method,
        path=request.url.path,
    )

    response = await call_next(request)

    process_time = time.time() - start_time
    status_code = response.status_code

    logger.info(
        "request",
        ip_address=ip_address,
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        duration=int(process_time * 1000),
    )

    return response
