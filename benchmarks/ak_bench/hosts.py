from typing import ClassVar

from ak_bench.errors import BenchConfigError
from ak_bench.platforms.base import Host


class HostRegistry:
    """Built-in hosts by name. ecs / lambda are added by the AWS issues."""

    _BUILTINS: ClassVar[dict[str, Host]] = {}

    @classmethod
    def get(cls, name: str) -> Host:
        """The host, with its fetcher lists validated."""
        host = cls._BUILTINS.get(name)
        if host is None:
            raise BenchConfigError(f"unknown host '{name}'; built-ins: {', '.join(cls.names()) or '(none)'}")
        host.fetchers.validate(name)
        return host

    @classmethod
    def names(cls) -> list[str]:
        return list(cls._BUILTINS)
