"""
ThreadRecorder — records a chat exchange into the conversation-thread store
around a ChatService execution-core run.
"""

import json
import logging
from typing import Any

from ...core.model import AgentPausedReplyAny, AgentReplyAny, AgentRequest, BaseChatRequest
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

    def pre_run(self, req: BaseChatRequest, requests: list[AgentRequest]) -> tuple[list[AgentRequest], list[ThreadAttachment]]:
        """Thread work done before the agent runs: require an authenticated principal, store
        attachment bytes, create/load the thread, append the user message, and return the rebuilt
        request list in which stored attachments are replaced by in-band
        AgentRequestAttachmentRef entries for MultimodalPreHook to resolve.

        store_attachments runs first: its config-validation rejections (raised
        as ValueError) must fire before any thread state exists, so a rejected
        request leaves no phantom thread behind.

        :param req: The originating chat request
        :param requests: The built AgentRequest list (may carry attachments)
        :return: Tuple of (rebuilt request list, stored ThreadAttachment references)
        :raises PermissionError: If the request carries no authenticated principal, or the thread
            exists and belongs to another principal (checked before any write)
        :raises ValueError: If attachments are rejected by config
        """
        principal = req.principal
        if principal is None or principal.is_anonymous:
            raise PermissionError("thread support requires an authenticated principal")
        # Ownership before any write: a request naming another user's session_id must not leave its
        # attachment bytes under that session before get_or_create_thread refuses it (spec 8.10).
        self._manager.get_thread(req.session_id, user_id=principal.subject)
        requests, attachments = self._manager.store_attachments(session_id=req.session_id, requests=requests)
        self._manager.get_or_create_thread(
            session_id=req.session_id,
            user_id=principal.subject,
            group_id=req.group_id,
            name=req.thread_name,
            first_prompt=req.prompt,
        )
        content, media_type = self._as_user_message(req)
        self._manager.append_message(req.session_id, "user", content, attachments=attachments, media_type=media_type)
        return requests, attachments

    @staticmethod
    def _as_user_message(req: BaseChatRequest) -> tuple[Any, str | None]:
        """The turn as the request carried it: its text, or the decision it answered a pause with.

        A resume-only request has no prompt, so recording ``req.prompt`` alone wrote an empty message
        for every decision a human made. The ``ResumeSpec`` is nested whole under ``resume`` rather
        than flattened, so a thread-owned ``prompt`` key can never collide with one of its fields, and
        the pair is one literal because insertion order is key order in ``model_dump_json``.

        :param req: The originating chat request.
        :return: The message content, and its label when the turn carried a decision.
        """
        if req.resume is None:
            return req.prompt, None
        resume = {"resume": req.resume.model_dump(mode="json")}
        return ({"prompt": req.prompt, **resume} if req.prompt else resume), HITL_MEDIA_TYPE

    def post_run(self, req: BaseChatRequest, result: Any, media_type: str | None = None) -> None:
        """Thread work done after a successful agent run: append the assistant message.

        ``media_type`` is how the queue runner hands over a label it holds *beside* the result
        rather than on it: ``ResponseBuilder`` put both in the response body, and the runner has
        only that body. The direct handler holds the reply itself and passes nothing.

        :param req: The originating chat request
        :param result: The agent's reply, in whichever form the caller holds it
        :param media_type: The reply's label when the caller holds it separately from the result
        :return: None
        """
        content, label = self._as_thread_message(result, media_type)
        self._manager.append_message(req.session_id, "assistant", content, media_type=label)

    @staticmethod
    def _as_thread_message(result: Any, media_type: str | None = None) -> tuple[Any, str | None]:
        """Render a reply as the (content, media_type) pair the thread store holds.

        A paused run is checked first: ``AgentPausedReplyAny`` subclasses ``AgentReplyAny`` and carries
        no label of its own, so the branches below would store the question as a string of itself.

        The callers pass three different things, which is what makes a single ``str()`` wrong. The
        direct handlers pass an ``AgentReply``, whose ``__str__`` already yields JSON, and the
        streaming one passes the accumulated text; but the queue runner has only the response body
        it just built, so for a labelled reply it passes a dict with the label in a sibling key —
        and ``str()`` on a dict is a Python repr, not JSON. Left alone, the same agent would record
        one encoding in single-process mode and another through the queue, permanently.

        **A labelled reply is stored as the object**, so replayed history has the shape the live
        reply had. Everything else keeps the encoding it had, byte for byte: the label is the
        switch, exactly as on every other surface.

        The unlabelled dict branch deliberately mirrors ``AgentReplyAny.__str__``'s own call,
        including its ``default=str`` fallback, rather than using ``PayloadCodec.encode``. For
        JSON-safe content the two agree; they part on a value that reached ``content`` through one
        of the documented bypasses, where ``default=str`` renders a datetime as the reply's
        ``__str__`` does and the codec renders it as ISO 8601. Matching the reply exactly is the
        point — the alternative is two stores holding the same reply in two encodings, which is
        invisible until someone diffs them.

        :param result: An AgentReply, a plain string, or the response body's ``result`` value.
        :param media_type: The label when the caller holds it separately from the result.
        :return: The thread message content, and its label when the reply carried one.
        """
        if isinstance(result, AgentPausedReplyAny):
            return result.content, HITL_MEDIA_TYPE
        if isinstance(result, AgentReplyAny) and result.media_type:
            return result.content, result.media_type
        if media_type and isinstance(result, (dict, list)):
            return result, media_type
        if isinstance(result, str):
            return result, None
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str), None
        return str(result), None
