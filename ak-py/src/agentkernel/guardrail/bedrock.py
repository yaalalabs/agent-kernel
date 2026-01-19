from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.model import AgentReply, AgentReplyText, AgentRequest
from .guardrail import BaseGuardrailUtil, InputGuardrail, OutputGuardrail

log = logging.getLogger(__name__)


class BaseBedrockGuardrail(ABC):
    """
    Base class for AWS Bedrock guardrails with shared initialization logic.
    """

    def __init__(self):
        self._bedrock_client = None
        self._guardrail_id: str | None = None
        self._guardrail_version: str | None = None
        self._initialize_guardrails()

    @abstractmethod
    def _get_guardrail_config(self) -> tuple[str | None, str | None]:
        """
        Get the guardrail ID and version for this guardrail type.

        :return: Tuple of (guardrail_id, guardrail_version)
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
        Initialize the AWS Bedrock guardrails client.
        """
        try:
            guardrail_id, guardrail_version = self._get_guardrail_config()

            if not guardrail_id:
                log.warning("No Bedrock guardrail ID specified. Guardrails will be disabled.")
                return

            self._guardrail_id = guardrail_id
            self._guardrail_version = guardrail_version or "DRAFT"

            # Lazy import
            import boto3

            self._bedrock_client = boto3.client("bedrock-runtime")
            log.info(
                f"AWS Bedrock {self._get_guardrail_type()} Guardrails initialized with ID: {self._guardrail_id}, "
                f"Version: {self._guardrail_version}"
            )
        except ImportError as e:
            log.warning(f"boto3 package not installed: {e}. Bedrock guardrails will be disabled.")
        except Exception as e:
            log.error(f"Failed to initialize AWS Bedrock guardrails: {e}")

    async def _apply_guardrail(self, text_content: list[dict[str, dict]], source: str = "INPUT") -> tuple[bool, str | None]:
        """
        Apply Bedrock guardrail to the provided content.

        :param text_content: List of content blocks to evaluate
        :param source: Source of the content ("INPUT" or "OUTPUT")
        :return: Tuple of (passed, intervention_message)
        """
        if not self._bedrock_client or not self._guardrail_id:
            return True, None

        try:
            # Run boto3 call in executor to avoid blocking event loop
            response = await asyncio.to_thread(
                self._bedrock_client.apply_guardrail,
                guardrailIdentifier=self._guardrail_id,
                guardrailVersion=self._guardrail_version,
                source=source,
                content=text_content,
            )

            action = response.get("action")

            if action == "GUARDRAIL_INTERVENED":
                # Extract intervention details
                assessments = response.get("assessments", [])
                outputs = response.get("outputs", [])

                log.warning(f"Bedrock guardrail intervened. Action: {action}, Assessments: {assessments}")

                # Return False to indicate guardrail was triggered
                output_message = self._build_intervention_message(assessments, outputs)
                log.warning(f"Bedrock intervention message: {output_message}")
                return False, output_message

            # No intervention needed
            log.debug(f"Content passed Bedrock guardrail validation. Action: {action}")
            return True, None

        except Exception as e:
            log.error(f"Error during Bedrock guardrail validation: {e}")
            # On error, allow content to proceed rather than blocking
            return True, None

    @staticmethod
    def _build_intervention_message(assessments: list, outputs: list) -> str:
        """
        Build a user-friendly intervention message from guardrail assessments.

        :param assessments: List of assessment results from Bedrock
        :param outputs: List of output blocks from Bedrock
        :return: User-friendly intervention message
        """
        # If Bedrock provides output text, use it
        if outputs:
            for output_block in outputs:
                if "text" in output_block:
                    log.debug(f"Bedrock responded with the reject message: {output_block}")
                    return output_block["text"]

        # Otherwise, construct a generic message based on assessments
        violation_types = set()
        for assessment in assessments:
            for policy_type, policy_data in assessment.items():
                if isinstance(policy_data, dict) and policy_data.get("filters"):
                    for filter_item in policy_data["filters"]:
                        if filter_item.get("action") == "BLOCKED":
                            violation_types.add(policy_type)

        if violation_types:
            return (
                f"I apologize, but I'm unable to process this request as it may violate content safety guidelines "
                f"({', '.join(violation_types)}). Please rephrase your question or try a different topic."
            )

        return (
            "I apologize, but I'm unable to process this request as it may violate content safety guidelines. "
            "Please rephrase your question or try a different topic."
        )


class BedrockInputGuardrail(BaseGuardrailUtil, BaseBedrockGuardrail, InputGuardrail):
    """
    AWS Bedrock Input Guardrail.
    Validates input requests before they are sent to the agent.
    """

    def _get_guardrail_config(self) -> tuple[str | None, str | None]:
        """Get the input guardrail ID and version."""
        config = AKConfig.get().guardrail.input
        guardrail_id = getattr(config, "id", None)
        guardrail_version = getattr(config, "version", None)
        return guardrail_id, guardrail_version

    def _get_guardrail_type(self) -> str:
        """Get the guardrail type name for logging."""
        return "Input"

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        """
        Validate input requests using AWS Bedrock guardrails.

        :param session: Session object containing interaction state
        :param agent: Agent object that will process the requests
        :param requests: List of AgentRequest objects to validate

        :return: Original requests if validation passes or guardrails not configured,
                or AgentReply with the error message if guardrail is triggered
        """
        if not self._bedrock_client or not self._guardrail_id:
            return requests

        try:
            # Extract text from requests
            input_text = self._extract_text_from_requests(requests)
            if not input_text:
                return requests

            # Prepare content for Bedrock guardrail
            content = [{"text": {"text": input_text}}]

            # Apply guardrail
            passed, intervention_message = await self._apply_guardrail(content, source="INPUT")

            if not passed:
                # Guardrail was triggered - return error response
                message = intervention_message or (
                    "I apologize, but I'm unable to process this request as it may violate content safety guidelines. "
                    "Please rephrase your question or try a different topic."
                )
                return AgentReplyText(text=message, prompt=input_text)

            # Validation passed
            log.debug("Input passed Bedrock guardrail validation")
            return requests

        except ImportError as e:
            log.error(f"boto3 not available but Bedrock guardrails are enabled: {e}")
            input_text = self._extract_text_from_requests(requests)
            return AgentReplyText(
                text="I apologize, but I'm unable to process your request at this time due to a configuration issue. "
                "Please contact support if this problem persists.",
                prompt=input_text,
            )
        except Exception as e:
            log.error(f"Error during Bedrock input guardrail validation: {e}")
            input_text = self._extract_text_from_requests(requests)
            return AgentReplyText(
                text="I apologize, but I'm unable to process your request at this time. "
                "Please try again or contact support if this issue continues.",
                prompt=input_text,
            )

    def name(self) -> str:
        return "BedrockInputGuardrail"


class BedrockOutputGuardrail(BaseGuardrailUtil, BaseBedrockGuardrail, OutputGuardrail):
    """
    AWS Bedrock Output Guardrail.
    Validates agent responses before they are returned to the user.
    """

    def _get_guardrail_config(self) -> tuple[str | None, str | None]:
        """Get the output guardrail ID and version."""
        config = AKConfig.get().guardrail.output
        guardrail_id = getattr(config, "id", None)
        guardrail_version = getattr(config, "version", None)
        return guardrail_id, guardrail_version

    def _get_guardrail_type(self) -> str:
        """Get the guardrail type name for logging."""
        return "Output"

    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        """
        Validate output responses using AWS Bedrock guardrails.

        :param session: Session object containing interaction state
        :param requests: List of agent requests being processed
        :param agent: Agent instance that generated the reply
        :param agent_reply: Agent reply to validate
        :return: Original reply if validation passes or guardrails are not configured,
                or modified reply with an error message if guardrail is triggered
        """
        if not self._bedrock_client or not self._guardrail_id:
            return agent_reply

        try:
            # Extract text from reply
            output_text = self._extract_text_from_reply(agent_reply)
            if not output_text:
                return agent_reply

            # Prepare content for Bedrock guardrail
            content = [{"text": {"text": output_text}}]

            # Apply guardrail
            passed, intervention_message = await self._apply_guardrail(content, source="OUTPUT")

            if not passed:
                # Guardrail was triggered - return safe response
                message = intervention_message or (
                    "I apologize, but I'm unable to provide this response as it may not meet content safety guidelines. "
                    "Please try rephrasing your question."
                )

                if isinstance(agent_reply, AgentReplyText):
                    agent_reply.text = message

                return agent_reply

            # Validation passed
            log.debug("Output passed Bedrock guardrail validation")
            return agent_reply

        except ImportError:
            log.warning("boto3 not available, skipping Bedrock output validation")
            return agent_reply
        except Exception as e:
            log.error(f"Error during Bedrock output guardrail validation: {e}")
            # On error, allow the reply to proceed rather than blocking
            return agent_reply

    def name(self) -> str:
        return "BedrockOutputGuardrail"
