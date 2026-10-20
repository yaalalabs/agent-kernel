"""
ThreadRecorder — records a chat exchange into the conversation-thread store
around a ChatService execution-core run.
"""

import json
import logging
from typing import Any, List, Optional

from ...core.model import AgentPausedReplyAny, AgentRequest, BaseChatRequest
from .manager import ConversationThreadManager
from .model import HITL_MEDIA_TYPE, ThreadAttachment


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
        content, media_type = self._as_user_message(req)
        self._manager.append_message(req.session_id, "user", content, attachments=attachments, media_type=media_type)
        return requests, attachments

    @staticmethod
    def _as_user_message(req: BaseChatRequest) -> tuple[Any, Optional[str]]:
        """The turn as the request carried it: its text, or the decision it answered a pause with.

        A resume-only request has no prompt — ``BaseChatRequest.prompt`` is ``str = ""`` precisely so a
        decision can stand alone — so recording ``req.prompt`` wrote an empty message for every decision
        a human made.

        The validated ``ResumeSpec`` is nested whole under ``resume`` rather than flattened, so the
        stored object remains exactly a ``ResumeSpec``: flattening would put a thread-owned ``prompt``
        key inside Agent Kernel's own namespace, where a later ``ResumeSpec`` field could collide with
        it and a reader could not tell the two apart. The pair is built as one literal because key
        insertion order is key order in ``model_dump_json``, and ``prompt`` precedes ``resume`` on
        ``BaseChatRequest`` itself.

        Nothing here reads ``ResumeDecision.status``: approved, denied and cancelled reach the store
        inside the payload and nowhere else, so what is stored never depends on what a decision meant.

        :param req: The originating chat request.
        :return: The message content, and its label when the turn carried a decision.
        """
        if req.resume is None:
            return req.prompt, None
        resume = {"resume": req.resume.model_dump(mode="json")}
        return ({"prompt": req.prompt, **resume} if req.prompt else resume), HITL_MEDIA_TYPE

    def post_run(self, req: BaseChatRequest, result: Any) -> None:
        """Thread work done after a successful agent run: append the assistant message.

        :param req: The originating chat request
        :param result: The agent's reply, in whichever form the caller holds it
        :return: None
        """
        content, media_type = self._as_thread_message(result)
        self._manager.append_message(req.session_id, "assistant", content, media_type=media_type)

    @staticmethod
    def _as_thread_message(result: Any) -> tuple[Any, Optional[str]]:
        """Render a reply as the (content, media_type) pair the thread store holds.

        **A paused run is stored as the object its reply derived**, so history carries the question
        rather than a string of it. That branch is checked first because ``AgentPausedReplyAny`` is an
        ``AgentReplyAny`` subclass: left to the branches below it would fall through to ``str(result)``
        and be stored as text, which is what made a pause unbranchable in history.

        The callers pass three different things, which is what makes a single ``str()`` wrong. The
        direct handlers pass an ``AgentReply``, whose ``__str__`` already yields JSON, and the
        streaming one passes the accumulated text; but the queue runner has only the response body
        it just built, so for a labelled reply it passes a dict — and ``str()`` on a dict is a
        Python repr, not JSON. Left alone, the same agent would record one encoding in
        single-process mode and another through the queue, permanently.

        The dict branch deliberately mirrors ``AgentReplyAny.__str__``'s own call, including its
        ``default=str`` fallback, rather than using ``PayloadCodec.encode``. For JSON-safe content
        the two agree; they part on a value that reached ``content`` through one of the documented
        bypasses, where ``default=str`` renders a datetime as the reply's ``__str__`` does and the
        codec renders it as ISO 8601. Matching the reply exactly is the point — the alternative is
        two stores holding the same reply in two encodings, which is invisible until someone diffs
        them.

        :param result: An AgentReply, a plain string, or the response body's ``result`` value.
        :return: The thread message content, and its label when the reply carried one.
        """
        if isinstance(result, AgentPausedReplyAny):
            return result.content, HITL_MEDIA_TYPE
        if isinstance(result, str):
            return result, None
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str), None
        return str(result), None
