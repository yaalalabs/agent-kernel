"""Shared connection-driver base class inherited by all database drivers."""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Tuple, Type, Union

ExceptionScope = Union[Type[BaseException], Tuple[Type[BaseException], ...]]


class BaseDriver(ABC):
    """
    Base class for the shared database connection drivers.

    Owns the pieces common to every driver: the connect lock, the logger, and
    the connection-retry helper. Concrete drivers implement :meth:`_connect`
    and keep their backend-specific client surface and lazy-access properties.
    """

    def __init__(self, logger_name: str):
        """
        Initialize the shared driver state.

        :param logger_name: Name of the driver's logger,
            e.g. ``"ak.core.util.driver.dynamodb"``.
        """
        self._lock = threading.Lock()
        self._log = logging.getLogger(logger_name)

    @abstractmethod
    def _connect(self) -> None:
        """Establish the backend connection and store the resulting client(s), with retries."""

    def _connect_with_retries(
        self,
        connect: Callable[[], Any],
        retry_on: ExceptionScope,
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
        :param retries: Maximum number of connection attempts.
        :param delay: Seconds to sleep between attempts.
        :return: The value returned by ``connect()``.
        """
        last_err: Optional[BaseException] = None
        for attempt in range(retries):
            try:
                return connect()
            except retry_on as e:
                last_err = e
                self._log.warning("Connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(delay)
        if last_err is None:
            raise ValueError("retries must be >= 1")
        raise last_err
