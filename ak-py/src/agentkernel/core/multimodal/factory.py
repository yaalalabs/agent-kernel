import logging

from ..config import AKConfig
from ...core.hooks import PreHook
from ...core.model import AgentRequest


class NoOpPreHook(PreHook):
    """No-op pre-hook when multimodal is disabled."""

    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest]:
        return requests

    def name(self) -> str:
        return "NoOpMultimodalPreHook"


class MultimodalPreHookFactory:
    """Factory to get the appropriate multimodal pre-hook based on config."""

    @staticmethod
    def get() -> PreHook:
        try:
            config = getattr(AKConfig.get(), "multimodal", None)
            if config and config.enabled:
                from .hooks import MultimodalPreHook
                return MultimodalPreHook()
            return NoOpPreHook()
        except Exception:
            logging.getLogger("ak.hooks.multimodal_pre").exception("Failed to initialize MultimodalPreHook; falling back to NoOpPreHook.")
            return NoOpPreHook()
