"""Conversation-thread recording for AG-UI runs (#836)."""

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException

from ...core.model import AgentRequest, AgentRequestText, AgentResumeRequestAny, BaseChatRequest, ResumeSpec
from ..thread.manager import ConversationThreadManager
from ..thread.recorder import StreamedReply, ThreadRecorder

if TYPE_CHECKING:
    from ag_ui.core import RunAgentInput


class AGUIThreadRecorder:
    """Records AG-UI runs through ``ThreadRecorder``; enabled by the presence of a ``thread`` block."""

    _log = logging.getLogger("ak.integration.agui.recorder")

    def __init__(self, recorder: ThreadRecorder, manager: ConversationThreadManager):
        """
        :param recorder: The recorder every write goes through.
        :param manager: The thread manager, for the ownership check.
        """
        self._recorder = recorder
        self._manager = manager

    @classmethod
    def create(cls) -> "AGUIThreadRecorder | None":
        """:return: A recorder, or None when no ``thread`` block is configured."""
        manager = ConversationThreadManager.get()
        return cls(ThreadRecorder(manager), manager) if manager is not None else None

    @staticmethod
    def chat_request(run_input: "RunAgentInput", user_id: str | None, agent_name: str, requests: list[AgentRequest]) -> BaseChatRequest:
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
        Record the user turn before the run, refusing a thread another user owns.

        Checked twice: up front, so the common case stores no attachment bytes, and again inside
        ``get_or_create_thread``, which also catches a thread a concurrent request created first.

        :param req: From ``chat_request``.
        :param requests: The run's requests.
        :return: The requests with stored attachments replaced by references.
        :raises HTTPException: 403 for another user's thread, 400 when the attachments are refused;
                               no message is written either way.
        """
        try:
            self._manager.get_thread(req.session_id, user_id=req.user_id)
            rebuilt, _ = self._recorder.pre_run(req, requests, enforce_owner=True)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Thread is not owned by the authorised user")
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
