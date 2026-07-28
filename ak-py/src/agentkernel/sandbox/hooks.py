"""Task-completion ingestion — the sandbox system pre-hook.

When a promoted sandbox task finishes, its completion event re-enters the agent as an
``AgentRequestAny(name="sandbox_task_completion")`` carried on the inbound request
(``ChatService`` maps extra body fields to ``AgentRequestAny`` unchanged). This hook
consumes that event under the session lock: it dedups against the task registry
(at-least-once delivery), updates the sandbox-session handle, and injects a bounded
result summary into the agent's text request — the multimodal injection precedent.

``SandboxPreHookFactory`` mirrors ``MultimodalPreHookFactory``: a no-op hook when the
capability is disabled, and no-op-on-failure so the hook chain never breaks the runtime.
"""

import json
import logging
from typing import Any, Optional

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.hooks import PreHook
from ..core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText
from .broker.base import SandboxCompletion
from .manager import SandboxManager
from .model import SandboxTask

COMPLETION_REQUEST_NAME = "sandbox_task_completion"


class NoOpSandboxPreHook(PreHook):
    """No-op pre-hook when the sandbox capability is disabled."""

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest]:
        """Pass the requests through unchanged."""
        return requests

    def name(self) -> str:
        """Return the hook name."""
        return "NoOpSandboxPreHook"


class SandboxPreHook(PreHook):
    """Consumes sandbox task-completion events before the agent's turn."""

    def __init__(self) -> None:
        """Initialize the hook (logger only; all state lives in the session registry)."""
        self._log = logging.getLogger("ak.sandbox.hooks")

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        """Ingest any ``sandbox_task_completion`` requests before the agent's turn.

        No completion present: pass through. Fresh completion: mark the task consumed and
        terminal, refresh the session handle, strip the completion request, and inject a
        bounded summary into the last text request. Unknown/duplicate/malformed: return a
        halting ``AgentReplyText`` so the queued re-invocation ends as a no-op.
        """
        completions = [r for r in requests if isinstance(r, AgentRequestAny) and r.name == COMPLETION_REQUEST_NAME]
        if not completions:
            return requests

        manager = SandboxManager.get()
        if manager is None:
            # A completion arrived while the capability is disabled: strip it, never crash the turn.
            return [r for r in requests if not (isinstance(r, AgentRequestAny) and r.name == COMPLETION_REQUEST_NAME)]

        summaries = []
        for item in completions:
            completion = self._parse_completion(item.content)
            task = manager.ingest_completion(completion) if completion is not None else None
            if task is not None:
                summaries.append(self._summary(completion, task))

        if not summaries:
            # Unknown task, already-consumed duplicate, or malformed payload: halt the run so the
            # queued re-invocation ends as a no-op (at-least-once dedup).
            return AgentReplyText(response="Duplicate or unknown sandbox task completion ignored.")

        filtered: list[AgentRequest] = []
        last_text_idx = -1
        for req in requests:
            if isinstance(req, AgentRequestAny) and req.name == COMPLETION_REQUEST_NAME:
                continue
            if isinstance(req, AgentRequestText):
                last_text_idx = len(filtered)
            filtered.append(req)

        summary_text = "\n\n".join(summaries)
        if last_text_idx >= 0:
            last_text = filtered[last_text_idx]
            filtered[last_text_idx] = AgentRequestText(prompt=f"{last_text.prompt}\n\n{summary_text}")
        else:
            filtered.append(AgentRequestText(prompt=summary_text))
        return filtered

    @staticmethod
    def _parse_completion(content: Any) -> Optional[SandboxCompletion]:
        """Coerce the request content (model instance, dict, or JSON string) into a
        ``SandboxCompletion``; ``None`` when malformed (dropped, never raised)."""
        try:
            if isinstance(content, SandboxCompletion):
                return content
            if isinstance(content, str):
                content = json.loads(content)
            return SandboxCompletion.model_validate(content)
        except Exception:  # noqa: BLE001 — a malformed completion is dropped, not raised
            return None

    @staticmethod
    def _summary(completion: SandboxCompletion, task: SandboxTask) -> str:
        """Render the bounded result summary injected into the agent's text: status, exit
        code, stdout/stderr truncated at ``tool_output_max_chars``, the ref location when
        the result was offloaded, and the sandbox_session_id to continue with."""
        limit = AKConfig.get().sandbox.tool_output_max_chars
        lines = [f"[Sandbox task '{task.task_id}' completed: {completion.status}]"]
        if completion.result is not None:
            lines.append(f"exit_code: {completion.result.exit_code}")
            if completion.result.stdout:
                lines.append(f"stdout:\n{completion.result.stdout[:limit]}")
            if completion.result.stderr:
                lines.append(f"stderr:\n{completion.result.stderr[:limit]}")
            if completion.result.notice:
                lines.append(f"notice: {completion.result.notice}")
        if completion.result_ref:
            lines.append(f"full result stored at: {completion.result_ref}")
        if completion.error:
            lines.append(f"error: {completion.error}")
        lines.append(f"sandbox_session_id: {completion.sandbox_session.sandbox_session_id}")
        return "\n".join(lines)

    def name(self) -> str:
        """Return the hook name."""
        return "SandboxPreHook"


class SandboxPreHookFactory:
    """Factory returning the sandbox pre-hook, or a no-op when the capability is disabled."""

    @staticmethod
    def get() -> PreHook:
        """Return ``SandboxPreHook`` when ``sandbox.enabled`` is true, else the no-op hook;
        any initialization failure also falls back to the no-op (the hook chain must never
        break the runtime)."""
        try:
            config = getattr(AKConfig.get(), "sandbox", None)
            if config and config.enabled:
                return SandboxPreHook()
            return NoOpSandboxPreHook()
        except Exception:  # noqa: BLE001 — the hook chain must never break the runtime
            logging.getLogger("ak.sandbox.hooks").exception("Failed to initialize SandboxPreHook; falling back to NoOpSandboxPreHook.")
            return NoOpSandboxPreHook()
