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
        if cls.missing_env():
            return None
        api_base_path, api_version, agent_endpoint = (os.getenv(name) for name in cls.ENV)
        base_path = f"/{api_base_path}/{api_version}"
        return cls(base_path, f"{base_path}/{agent_endpoint}")

    @classmethod
    def missing_env(cls) -> list[str]:
        """The names in ``ENV`` that are unset or empty, for a cold-start error."""
        return [name for name in cls.ENV if not os.getenv(name)]

    @property
    def base_path(self) -> str:
        return self._base_path

    @property
    def chat_path(self) -> str:
        return self._chat_path
