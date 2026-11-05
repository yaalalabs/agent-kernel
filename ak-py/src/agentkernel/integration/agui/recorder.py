"""Conversation-thread recording for AG-UI runs (#836)."""

import logging
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException

from ...core.model import AgentRequest, AgentRequestText, AgentResumeRequestAny, BaseChatRequest, ResumeSpec
from ..thread.manager import ConversationThreadManager
from ..thread.recorder import StreamedReply, ThreadRecorder

if TYPE_CHECKING:
    from ag_ui.core import RunAgentInput


class AGUIThreadRecorder:
    """Records AG-UI runs through ``ThreadRecorder``; enabled by the presence of a ``thread`` block."""

    _log = logging.getLogger("ak.integration.agui.recorder")

    def __init__(self, recorder: ThreadRecorder):
        """:param recorder: The recorder every write goes through."""
        self._recorder = recorder

    @classmethod
    def create(cls) -> Optional["AGUIThreadRecorder"]:
        """:return: A recorder, or None when no ``thread`` block is configured."""
        manager = ConversationThreadManager.get()
        return cls(ThreadRecorder(manager)) if manager is not None else None

    @staticmethod
    def chat_request(run_input: "RunAgentInput", user_id: Optional[str], agent_name: str, requests: list[AgentRequest]) -> BaseChatRequest:
        """
        The chat request ``ThreadRecorder`` expects, built from an AG-UI run.

        ``prompt`` is always passed, even empty, since an image-only turn is valid. Decisions are
        copied onto ``resume`` so the user message records them.

        :param run_input: The parsed RunAgentInput.
        :param user_id: The authorised caller.
        :param agent_name: The agent the route resolved.
        :param requests: The run's requests, as ``AGUIRunInput.to_requests`` built them.
        :return: The request to record under.
        """
        prompt = "\n".join(r.prompt for r in requests if isinstance(r, AgentRequestText))
        decision = next((r for r in requests if isinstance(r, AgentResumeRequestAny)), None)
        resume = ResumeSpec(run_id=decision.run_id, decisions=decision.decisions) if decision is not None else None
        return BaseChatRequest(session_id=run_input.thread_id, user_id=user_id, agent=agent_name, prompt=prompt, resume=resume)

    def pre_run(self, req: BaseChatRequest, requests: list[AgentRequest]) -> list[AgentRequest]:
        """
        Record the user turn before the run.

        :param req: From ``chat_request``.
        :param requests: The run's requests.
        :return: The requests with stored attachments replaced by references.
        :raises HTTPException: 400 when the attachments are refused; nothing is written.
        """
        try:
            rebuilt, _ = self._recorder.pre_run(req, requests)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return rebuilt

    def post_run(self, req: BaseChatRequest, reply: StreamedReply) -> None:
        """
        Record the assistant turn; never raises, since the client already has its answer.

        :param req: From ``chat_request``.
        :param reply: The finished run.
        """
        result = reply.result()
        if result is None:
            return
        try:
            self._recorder.post_run(req, result)
        except Exception:
            self._log.exception(f"Failed to record the assistant message for thread {req.session_id}")
