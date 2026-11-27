from typing import ClassVar

from ak_bench.errors import BenchConfigError
from ak_bench.load.driver.base import ClientDriver
from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver


class DriverFactory:
    """Built-in client drivers by (mode, message type)."""

    BUILTINS: ClassVar[tuple[tuple[str, str], ...]] = (("async", "complete"),)

    @staticmethod
    def driver_class(mode: str, message_type: str) -> type[ClientDriver]:
        if (mode, message_type) == ("async", "complete"):
            return WebSocketCompleteDriver
        builtins = ", ".join(f"{m} + {t}" for m, t in DriverFactory.BUILTINS)
        raise BenchConfigError(f"no client driver for {mode} + {message_type}; built-ins: {builtins}")
