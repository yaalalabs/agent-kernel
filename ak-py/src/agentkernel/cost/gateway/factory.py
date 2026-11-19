"""LLMGatewayFactory: builds the LLMGateway named by ``cost.gateway.type``."""

import logging
from typing import TYPE_CHECKING

from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ...secret import SecretManager
from .base import LLMGateway

if TYPE_CHECKING:
    from ...core.config import _CostGatewayConfig


class LLMGatewayFactory:
    """Creates the configured gateway. It holds no instance: ``CostManager`` owns the one it builds."""

    _log = logging.getLogger("ak.cost.gateway.factory")

    @staticmethod
    def create(config: "_CostGatewayConfig") -> LLMGateway:
        """Build the gateway the ``cost.gateway`` block names.

        :param config: The ``cost.gateway`` block.
        :return: The gateway.
        :raises AKConfigError: If the type is neither a built-in nor a resolvable dotted path to an LLMGateway subclass.
        """
        LLMGatewayFactory._log.info(f"Building '{config.type}' LLM gateway")
        key = config.type.lower()
        if key == "litellm":
            with require_extra("cost", "cost.gateway.type: litellm"):
                from .litellm import LiteLLMGateway

            return LiteLLMGateway(config, SecretManager.current())
        if "." not in key:
            raise AKConfigError(
                f"unknown cost.gateway.type '{config.type}'; expected one of litellm, agentgateway, langfuse or a dotted path to an LLMGateway subclass"
            )
        # A bring-your-own gateway reads its own settings from config.model_extra.
        return resolve_dotted(config.type, base=LLMGateway)(config, SecretManager.current())
