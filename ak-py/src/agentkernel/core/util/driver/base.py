"""Shared connection-retry helper used by all database drivers."""

import logging
import time
from typing import Any, Callable, Tuple, Type, Union

ExceptionScope = Union[Type[BaseException], Tuple[Type[BaseException], ...]]


def connect_with_retries(
    connect: Callable[[], Any],
    retry_on: ExceptionScope,
    log: logging.Logger,
    retries: int = 3,
    delay: float = 2.0,
) -> Any:
    """
    Call ``connect()`` up to ``retries`` times, sleeping ``delay`` seconds between
    attempts, and return its result.

    Only exceptions matching ``retry_on`` (an exception type or tuple of types) are
    retried; anything outside that scope propagates immediately. The last error is
    re-raised once all attempts are exhausted.

    :param connect: Zero-argument callable that establishes and returns the connection.
    :param retry_on: Exception type(s) that trigger a retry.
    :param log: Logger used to report failed attempts.
    :param retries: Maximum number of connection attempts.
    :param delay: Seconds to sleep between attempts.
    :return: The value returned by ``connect()``.
    """
    last_err: BaseException = None
    for attempt in range(retries):
        try:
            return connect()
        except retry_on as e:
            last_err = e
            log.warning("Connection attempt %s failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_err
