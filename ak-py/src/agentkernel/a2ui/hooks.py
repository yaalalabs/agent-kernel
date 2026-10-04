"""
A2UI labelling: the one place in the framework that knows the format exists.

Everything else in this change carries a payload and its format label without interpreting either.
This capability supplies the label, because that part is the same for every application: A2UI's
media type is one agreed string, unlike a component catalog, which has to match the components a
given frontend implements and so stays with the application.

The detection rule is the config block itself. Naming an agent under ``a2ui.agents`` declares that
it emits A2UI, and the hook takes that at its word: a reply from that agent whose body parses as
JSON is labelled, and prose, which does not parse, is left alone. Nothing reads A2UI's message
names or its ``version``, so the capability needs no revision when the protocol moves.

An ``AgentReplyAny`` is skipped rather than labelled. A reply that is already structured means the
application set ``output_type``, whose schema — its union members, its discriminator — Agent Kernel
has never seen; a hook labelling every structured reply would stamp prose as A2UI on every turn.
Skipping is what keeps the config block and the ``output_type`` route from colliding: one or the
other owns the labelling, never both.
"""

import json
import logging
from typing import Optional

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.hooks import PostHook
from ..core.model import AgentReply, AgentReplyAny, AgentReplyText, AgentRequest


class A2UIPostHook(PostHook):
    """Label a parsed reply from an agent the configuration declares to be an A2UI agent."""

    MEDIA_TYPE = "application/a2ui+json"

    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        """Return the reply labelled as A2UI when it parses, and untouched when it does not.

        :param session: The session instance.
        :param requests: The requests provided to the agent, after pre-hooks.
        :param agent: The agent that produced the reply.
        :param agent_reply: The reply to label.
        :return: An AgentReplyAny carrying the media type, or the original reply unchanged.
        """
        if not self._applies_to(agent):
            return agent_reply
        if not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        try:
            payload = json.loads(agent_reply.response)
        except (ValueError, TypeError):
            return agent_reply
        if not isinstance(payload, (dict, list)):
            return agent_reply
        return AgentReplyAny(content=payload, prompt=agent_reply.prompt, media_type=self.MEDIA_TYPE)

    @staticmethod
    def _applies_to(agent: Agent) -> bool:
        """Return whether the configuration scopes this capability to `agent`.

        Read per call rather than resolved once, so one hook instance stays correct for every
        concurrent request; the hook holds no state of its own.

        :param agent: The agent that produced the reply.
        :return: True when `a2ui.agents` is unset or names this agent.
        """
        config = getattr(AKConfig.get(), "a2ui", None)
        agents: Optional[list[str]] = getattr(config, "agents", None) if config else None
        return agents is None or agent.name in agents

    def name(self) -> str:
        """Return the hook name."""
        return "A2UIPostHook"


class NoOpA2UIPostHook(PostHook):
    """Returned when the capability is disabled, so the hook chain keeps a uniform shape."""

    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        """Return the reply untouched.

        :param session: The session instance.
        :param requests: The requests provided to the agent.
        :param agent: The agent that produced the reply.
        :param agent_reply: The reply to pass through.
        :return: The reply, unchanged.
        """
        return agent_reply

    def name(self) -> str:
        """Return the hook name."""
        return "NoOpA2UIPostHook"


class A2UIPostHookFactory:
    """Factory returning the A2UI post-hook, or a no-op when the capability is disabled."""

    _log = logging.getLogger("ak.a2ui.hooks")

    @classmethod
    def get(cls) -> PostHook:
        """Return ``A2UIPostHook`` when ``a2ui.enabled`` is true, else the no-op hook.

        Any initialization failure also falls back to the no-op: the hook chain must never break
        the runtime. A streaming deployment is warned about rather than served, because the hook is
        an ``on_run`` and ``Runtime.stream`` never calls one — the block would otherwise do nothing
        with no indication why.

        :return: The configured post-hook.
        """
        try:
            config = getattr(AKConfig.get(), "a2ui", None)
            if not (config and config.enabled):
                return NoOpA2UIPostHook()
            if getattr(AKConfig.get().execution, "mode", None) == "stream":
                cls._log.warning(
                    "a2ui.enabled is true but execution.mode is 'stream': the A2UI hook runs on "
                    "Runtime.run and is never called for a streamed run, so no reply will be "
                    "labelled. Label streamed payloads with an on_stream_event hook instead."
                )
            return A2UIPostHook()
        except Exception:  # noqa: BLE001 — the hook chain must never break the runtime
            cls._log.exception("Failed to initialize A2UIPostHook; falling back to NoOpA2UIPostHook.")
            return NoOpA2UIPostHook()
