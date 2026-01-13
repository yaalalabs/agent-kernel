from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from guardrails import GuardrailsOpenAI, GuardrailTripwireTriggered

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.model import AgentReply, AgentReplyText, AgentRequest
from .guardrail import BaseGuardrailUtil, InputGuardrail, OutputGuardrail

log = logging.getLogger(__name__)


class BaseOpenAIGuardrail(ABC):
    """
    Base class for OpenAI guardrails with shared initialization logic.
    """

    def __init__(self):
        self._guardrails_client: GuardrailsOpenAI | None = None
        self._initialize_guardrails()

    @abstractmethod
    def _get_config_path(self) -> str | None:
        """
        Get the configuration path for this guardrail type.
        """
        raise NotImplementedError

    @abstractmethod
    def _get_guardrail_type(self) -> str:
        """
        Get the guardrail type name (input/output) for logging.
        """
        raise NotImplementedError

    def _initialize_guardrails(self):
        """
        Initialize the OpenAI guardrails client.
        """
        try:
            config_path = self._get_config_path()
            if config_path:
                config_file = Path(config_path)
                if not config_file.exists():
                    log.warning(f"Guardrail config file not found: {config_path}. Guardrails will be disabled.")
                    return

                self._guardrails_client = GuardrailsOpenAI(config=config_file)
                log.info(f"OpenAI {self._get_guardrail_type()} Guardrails initialized with config: {config_path}")
            else:
                log.warning("No guardrail config path specified. Guardrails will be disabled.")
        except ImportError as e:
            log.warning(f"openai-guardrails package not installed: {e}. Guardrails will be disabled.")
        except Exception as e:
            log.error(f"Failed to initialize OpenAI guardrails: {e}")


class OpenAIInputGuardrail(BaseGuardrailUtil, BaseOpenAIGuardrail, InputGuardrail):
    """
    OpenAI Input Guardrail using the openai-guardrails library.
    Validates input requests before they are sent to the agent.
    """

    def _get_config_path(self) -> str | None:
        """Get the input guardrail configuration path."""
        return AKConfig.get().guardrail.input.config_path

    def _get_guardrail_type(self) -> str:
        """Get the guardrail type name for logging."""
        return "Input"

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        """
        Validate input requests using OpenAI guardrails.

        :param session: Session object containing interaction state
        :param agent: Agent object that will process the requests
        :param requests: List of AgentRequest objects to validate

        :return: Original requests if validation passes or guardrails not configured,
                or AgentReply with the error message if guardrail is triggered
        :rtype: list[AgentRequest] | AgentReply
        """
        if not self._guardrails_client:
            return requests

        try:
            # Extract text from requests
            input_text = self._extract_text_from_requests(requests)
            if not input_text:
                return requests

            # Validate input using guardrails
            try:
                # Check input against configured guardrails
                # Run the synchronous guardrails client in executor to avoid blocking event loop
                await asyncio.to_thread(
                    self._guardrails_client.chat.completions.create,
                    model=AKConfig.get().guardrail.input.model,
                    messages=[{"role": "user", "content": input_text}],
                    max_tokens=1,  # We only need to check, not generate
                )
                # If we get here, no guardrail was triggered
                log.debug("Input passed guardrail validation")
                return requests

            except GuardrailTripwireTriggered as e:
                # Guardrail was triggered - return error response
                log.warning(f"Input guardrail triggered: {e}")
                return AgentReplyText(
                    text="I apologize, but I'm unable to process this request as it may violate content safety guidelines. Please rephrase your question or try a different topic.",
                    prompt=input_text,
                )

        except ImportError as e:
            # Guardrails are enabled but package not installed
            log.error(f"openai-guardrails not available but guardrails are enabled: {e}")
            input_text = self._extract_text_from_requests(requests)
            return AgentReplyText(
                text="I apologize, but I'm unable to process your request at this time due to a configuration issue. Please contact support if this problem persists.",
                prompt=input_text,
            )
        except Exception as e:
            # Guardrails are enabled but validation failed
            log.error(f"Error during input guardrail validation: {e}")
            input_text = self._extract_text_from_requests(requests)
            return AgentReplyText(
                text="I apologize, but I'm unable to process your request at this time. Please try again or contact support if this issue continues.",
                prompt=input_text,
            )

    def name(self) -> str:
        return "OpenAIInputGuardrail"


class OpenAIOutputGuardrail(BaseGuardrailUtil, BaseOpenAIGuardrail, OutputGuardrail):
    """
    OpenAI Output Guardrail using the openai-guardrails library.
    Validates agent responses before they are returned to the user.
    """

    def _get_config_path(self) -> str | None:
        """
        Get the output guardrail configuration path.
        """
        return AKConfig.get().guardrail.output.config_path

    def _get_guardrail_type(self) -> str:
        """
        Get the guardrail type name for logging.
        """
        return "Output"

    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        """
        Validate output responses using OpenAI guardrails.

        :param session: Session object containing interaction state
        :param requests: List of agent requests being processed
        :param agent: Agent instance that generated the reply
        :param agent_reply: Agent reply to validate
        :return: Original reply if validation passes or guardrails are not configured,
                or modified reply with an error message if guardrail is triggered
        :rtype: AgentReply
        """
        if not self._guardrails_client:
            return agent_reply

        try:
            # Extract text from reply
            output_text = self._extract_text_from_reply(agent_reply)
            if not output_text:
                return agent_reply

            # Validate output using guardrails
            try:
                # Check output against configured guardrails
                # Run the synchronous guardrails client in executor to avoid blocking event loop
                await asyncio.to_thread(
                    self._guardrails_client.chat.completions.create,
                    model=AKConfig.get().guardrail.output.model,  # Model for guardrail checks
                    messages=[
                        {"role": "user", "content": agent_reply.prompt if hasattr(agent_reply, "prompt") else ""},
                        {"role": "assistant", "content": output_text},
                    ],
                    max_tokens=1,  # We only need to check, not generate
                )
                # If we get here, no guardrail was triggered
                log.debug("Output passed guardrail validation")
                return agent_reply

            except GuardrailTripwireTriggered as e:
                # Guardrail was triggered - return safe response
                log.warning(f"Output guardrail triggered: {e}")
                if isinstance(agent_reply, AgentReplyText):
                    agent_reply.text = "I apologize, but I'm unable to provide this response as it may not meet content safety guidelines. Please try rephrasing your question."
                return agent_reply

        except ImportError:
            log.warning("openai-guardrails not available, skipping validation")
            return agent_reply
        except Exception as e:
            log.error(f"Error during output guardrail validation: {e}")
            # On error, allow the reply to proceed rather than blocking
            return agent_reply

    def name(self) -> str:
        return "OpenAIOutputGuardrail"
