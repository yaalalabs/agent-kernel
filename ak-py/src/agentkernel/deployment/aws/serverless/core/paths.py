import os


class LambdaPaths:
    """The API prefix and chat path the ak-serverless module gives the request-handler Lambda (#894)."""

    ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")

    def __init__(self, base_path: str, chat_path: str):
        """
        :param base_path: The API prefix, e.g. ``/api/v1``
        :param chat_path: The configured chat path, e.g. ``/api/v1/chat``
        """
        self._base_path = base_path
        self._chat_path = chat_path

    @classmethod
    def from_env(cls) -> "LambdaPaths | None":
        """Build from the environment; ``None`` when any of ``ENV`` is unset or empty."""
        values = cls._read_env()
        if not all(values.values()):
            return None
        base_path = f"/{values['API_BASE_PATH']}/{values['API_VERSION']}"
        return cls(base_path, f"{base_path}/{values['AGENT_ENDPOINT']}")

    @classmethod
    def missing_env(cls) -> list[str]:
        """The names in ``ENV`` that are unset or empty, for a cold-start error."""
        values = cls._read_env()
        return [name for name in cls.ENV if not values[name]]

    @staticmethod
    def _read_env() -> dict[str, str | None]:
        """Each name in ``ENV`` and its value. Literal names, never computed ones: tests/test_secret_consumers.py
        rejects an environment read whose key it cannot see."""
        return {"API_BASE_PATH": os.getenv("API_BASE_PATH"), "API_VERSION": os.getenv("API_VERSION"), "AGENT_ENDPOINT": os.getenv("AGENT_ENDPOINT")}

    @property
    def base_path(self) -> str:
        return self._base_path

    @property
    def chat_path(self) -> str:
        return self._chat_path
