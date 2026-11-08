"""
ThreadRecorder — records a chat exchange into the conversation-thread store
around a ChatService execution-core run.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ...core.model import AgentReplyAny, AgentRequest, BaseChatRequest
from ...pipeline.envelope import ATTR_THREAD
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

    def pre_run(self, req: BaseChatRequest, requests: list[AgentRequest]) -> tuple[list[AgentRequest], list[ThreadAttachment]]:
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

    @classmethod
    def record_queued_reply(cls, attributes: Mapping[str, Any], req: BaseChatRequest, status_code: int, response: Any) -> None:
        """Append the assistant message for a request the edge already recorded. Never raises.

        The other half of the split: ``pre_run`` ran at the edge, before the request was enqueued,
        so only the reply is left, and only the agent runner has it. The ``thread`` attribute is
        what says the edge recorded a user message for this request — without it a plain queue
        request would grow a thread nothing asked for.

        Shared by every runner that consumes such a queue (the pipeline ``AgentRunner`` and
        ``StreamAgentRunner``, the serverless agent runner). Each calls it **after** sending the
        reply to the output queue: recording first would duplicate the assistant message whenever
        the send then failed and the message was redelivered; this order trades that for losing a
        recording if the process dies in between, which is the safer direction (the caller still
        got its answer). For the same reason a recording failure is logged and never raised: the
        reply is already delivered, so a failing thread store must not re-run the agent.

        :param attributes: The input message's attributes, carrying the ``thread`` marker.
        :param req: The validated request body; supplies the session the thread is keyed by.
        :param status_code: The status the run produced; a failure records nothing.
        :param response: What the runner holds: the response body, whose ``result`` and
            ``media_type`` are read (the label travels beside the result, and dropping it is what
            left replayed history unlabelled, #763), or the reply itself, such as a stream's
            accumulated text.
        """
        if not attributes.get(ATTR_THREAD) or status_code >= 400:
            return
        if isinstance(response, dict):
            result, media_type = response.get("result"), response.get("media_type")
        else:
            result, media_type = response, None
        if result in (None, ""):
            return
        try:
            manager = ConversationThreadManager.get()
            if manager is None:
                cls._log.warning(
                    "Input message is marked for thread recording but this process has no 'thread' "
                    "config block: the user message was recorded at the edge and the reply is lost. "
                    "Give the agent-runner process the same thread configuration as the API process."
                )
                return
            cls(manager).post_run(req, result, media_type)
        except Exception:
            cls._log.exception(f"Failed to record the assistant message for session_id={req.session_id}")

    @staticmethod
    def _as_thread_message(result: Any, media_type: str | None = None) -> tuple[Any, str | None]:
        """Render a reply as the (content, media_type) pair the thread store holds.

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
        if isinstance(result, AgentReplyAny) and result.media_type:
            return result.content, result.media_type
        if media_type and isinstance(result, (dict, list)):
            return result, media_type
        if isinstance(result, str):
            return result, None
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str), None
        return str(result), None
