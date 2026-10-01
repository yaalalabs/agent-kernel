"""
ThreadRecorder — records a chat exchange into the conversation-thread store
around a ChatService execution-core run.
"""

import json
import logging
from typing import Any, List

from ...core.model import AgentRequest, BaseChatRequest
from .manager import ConversationThreadManager
from .model import ThreadAttachment


class ThreadRecorder:
    """
    Recording logic for Conversation Thread Support, kept separate from the
    routes so it stays reusable and independently testable. pre_run() wraps the
    work done before the agent runs; post_run() appends the assistant reply.
    """

    _log = logging.getLogger("ak.integration.thread.recorder")

    def __init__(self, manager: ConversationThreadManager):
        """
        Initializes a ThreadRecorder instance.

        :param manager: The shared ConversationThreadManager to record through.
        """
        self._manager = manager

    def pre_run(self, req: BaseChatRequest, requests: List[AgentRequest]) -> tuple[List[AgentRequest], List[ThreadAttachment]]:
        """Thread work done before the agent runs: enforce user_id, store attachment
        bytes, create/load the thread, append the user message, and return the rebuilt
        request list in which stored attachments are replaced by in-band
        AgentRequestAttachmentRef entries for MultimodalPreHook to resolve.

        store_attachments runs first: its config-validation rejections (raised
        as ValueError) must fire before any thread state exists, so a rejected
        request leaves no phantom thread behind.

        :param req: The originating chat request
        :param requests: The built AgentRequest list (may carry attachments)
        :return: Tuple of (rebuilt request list, stored ThreadAttachment references)
        :raises ValueError: If user_id is missing, or attachments are rejected by config
        """
        if not req.user_id:
            raise ValueError("No user_id is provided in the request — user_id is required when thread support is enabled")
        requests, attachments = self._manager.store_attachments(session_id=req.session_id, requests=requests)
        self._manager.get_or_create_thread(
            session_id=req.session_id,
            user_id=req.user_id,
            group_id=req.group_id,
            name=req.thread_name,
            first_prompt=req.prompt,
        )
        self._manager.append_message(req.session_id, "user", req.prompt, attachments=attachments)
        return requests, attachments

    def post_run(self, req: BaseChatRequest, result: Any) -> None:
        """Thread work done after a successful agent run: append the assistant message.

        :param req: The originating chat request
        :param result: The agent's reply, in whichever form the caller holds it
        :return: None
        """
        self._manager.append_message(req.session_id, "assistant", self._as_thread_content(result))

    @staticmethod
    def _as_thread_content(result: Any) -> str:
        """Render a reply as the string the thread store holds, without ever producing a repr.

        The callers pass three different things, which is what makes a single ``str()`` wrong. The
        direct handlers pass an ``AgentReply``, whose ``__str__`` already yields JSON, and the
        streaming one passes the accumulated text; but the queue runner has only the response body
        it just built, so for a labelled reply it passes a dict — and ``str()`` on a dict is a
        Python repr, not JSON. Left alone, the same agent would record one encoding in
        single-process mode and another through the queue, permanently.

        The dict branch deliberately mirrors ``AgentReplyAny.__str__``'s own call rather than using
        ``PayloadCodec.encode``: the aim is that both paths record byte-identical rows, and the
        codec's compact separators would differ from the reply's by whitespace alone — the kind of
        divergence that is invisible until someone diffs two stores.

        :param result: An AgentReply, a plain string, or the response body's ``result`` value.
        :return: The thread message content.
        """
        if isinstance(result, str):
            return result
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)
        return str(result)
