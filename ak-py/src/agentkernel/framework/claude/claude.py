from __future__ import annotations

import asyncio
import base64
import contextvars
import copy
import dataclasses
import inspect
import json
import logging
import typing
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, List, Mapping
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SdkMcpTool,
    ServerToolResultBlock,
)
from claude_agent_sdk import StreamEvent as ClaudeStreamEvent
from claude_agent_sdk import TextBlock, ToolAnnotations, ToolResultBlock, UserMessage, create_sdk_mcp_server
from pydantic import Field, create_model

from ...core import Agent as BaseAgent
from ...core import Module
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.event import (
    MessageEnd,
    MessageStart,
    PausedInterruption,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    RunPaused,
    StreamEvent,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from ...core.model import (
    AgentPausedReplyAny,
    AgentReply,
    AgentReplyAny,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentRequestVoice,
    ResumeDecision,
)
from ...core.paused_run import PausedRun, PausedRunState
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "claude"

_log = logging.getLogger("ak.claude.runner")


class ClaudeSession:
    """
    ClaudeSession stores each agent's Claude conversation: the Claude session id and the transcript the CLI
    mirrored out of it. It is also the SDK `SessionStore` the run is given, as `OpenAISession` is the OpenAI
    SDK's session.

    The CLI keeps its transcript on local disk, which another replica does not have, so the transcript is kept
    here and persisted with the Agent Kernel session. Entries are the CLI's own transcript lines as plain JSON
    objects, so a pickled session carries no SDK objects. Each agent has its own conversation, because the CLI
    records an agent's system prompt in its transcript. The SDK mirrors entries as the CLI runs and they are
    stored as they arrive, so a turn that fails part way leaves its entries in the conversation, which the CLI
    resumes from.
    """

    def __init__(self) -> None:
        """
        Initializes a ClaudeSession instance.
        """
        self._session_ids: dict[str, str] = {}
        self._transcripts: dict[str, dict[str, list[dict]]] = {}

    def session_id(self, agent_name: str) -> str | None:
        """
        :param agent_name: The agent whose conversation to read.
        :return: The Claude session id the agent's conversation is on, or None before its first turn.
        """
        return self._session_ids.get(agent_name)

    def transcript(self, agent_name: str) -> dict[str, list[dict]]:
        """
        :param agent_name: The agent whose conversation to read.
        :return: The transcript entries by subpath: "" is the main transcript, "subagents/agent-<id>" a subagent's.
        """
        session_id = self._session_ids.get(agent_name)
        return self._transcripts.get(session_id, {}) if session_id is not None else {}

    def bind(self, agent_name: str, session_id: str) -> None:
        """
        Points an agent's conversation at a Claude session id, dropping the transcript of the one it was on.
        :param agent_name: The agent whose conversation to point.
        :param session_id: The Claude session id its turns are recorded under.
        """
        previous = self._session_ids.get(agent_name)
        if previous is not None and previous != session_id:
            self._transcripts.pop(previous, None)
        self._session_ids[agent_name] = session_id

    async def append(self, key: Mapping[str, Any], entries: list[dict]) -> None:
        """
        Stores mirrored transcript entries, skipping any whose `uuid` is already stored.
        :param key: The SDK SessionKey the entries belong to. `project_key` is ignored: the conversation is
            already scoped to one agent, so the CLI's working directory does not need to match across replicas.
        :param entries: The transcript entries.
        """
        stored = self._transcripts.setdefault(key["session_id"], {}).setdefault(key.get("subpath") or "", [])
        seen = {entry["uuid"] for entry in stored if entry.get("uuid")}
        for entry in entries:
            uid = entry.get("uuid")
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            stored.append(entry)

    async def load(self, key: Mapping[str, Any]) -> list[dict] | None:
        """
        :param key: The SDK SessionKey to load.
        :return: The stored entries, or None when there are none.
        """
        return list(self._transcripts.get(key["session_id"], {}).get(key.get("subpath") or "", [])) or None

    async def list_subkeys(self, key: Mapping[str, Any]) -> list[str]:
        """
        :param key: The SDK key naming the Claude session.
        :return: The subagent transcripts held for it, so a resume restores them too.
        """
        return sorted(subpath for subpath in self._transcripts.get(key["session_id"], {}) if subpath)


class _ClaudeApprovalGuard:
    """One-use approvals for AK tools in a single Claude run."""

    def __init__(self) -> None:
        self._grants: list[tuple[str, dict[str, Any]]] = []

    def grant(self, name: str, arguments: dict[str, Any]) -> None:
        self._grants.append((name, arguments))

    def consume(self, name: str, arguments: dict[str, Any]) -> bool:
        for index, (allowed_name, allowed_arguments) in enumerate(self._grants):
            if allowed_name == name and allowed_arguments == arguments:
                self._grants.pop(index)
                return True
        return False


_approval_guard: contextvars.ContextVar[_ClaudeApprovalGuard | None] = contextvars.ContextVar("claude_approval_guard", default=None)


class _ClaudeStreamMapper:
    """
    Maps one run's SDK messages onto Agent Kernel stream events.

    Boundaries come from the raw Anthropic stream events the SDK forwards with `include_partial_messages`; tool
    results from the `ToolResultBlock`s in the following user message. Ids are the framework's own: a text or
    thinking stream is `<message id>:<block index>`, a tool call keeps its `tool_use` id. Traffic inside a
    subagent (`parent_tool_use_id` set) is not emitted. One instance per run: it holds the run's open blocks.
    """

    def __init__(self) -> None:
        self._message_id: str | None = None
        self._open: dict[int, tuple[str, str]] = {}  # block index -> (kind, stream id)

    def events(self, message: Any) -> list[StreamEvent]:
        """
        :param message: Any message the SDK yields.
        :return: The Agent Kernel events it produces, possibly none.
        """
        if isinstance(message, ClaudeStreamEvent):
            return self._raw_events(message.event) if message.parent_tool_use_id is None else []
        if isinstance(message, (UserMessage, AssistantMessage)) and message.parent_tool_use_id is None and isinstance(message.content, list):
            return [
                ToolCallResult(tool_call_id=block.tool_use_id, content=self._as_text(block.content))
                for block in message.content
                if isinstance(block, (ToolResultBlock, ServerToolResultBlock))
            ]
        return []

    def close(self) -> list[StreamEvent]:
        """
        :return: The closing events for any block left open by a stream that ended mid-block.
        """
        return [event for index in sorted(self._open) for event in self._close(index)]

    def _raw_events(self, event: dict[str, Any]) -> list[StreamEvent]:
        """
        :param event: A raw Anthropic stream event.
        :return: The Agent Kernel events it produces.
        """
        kind = event.get("type")
        if kind == "message_start":
            self._message_id = (event.get("message") or {}).get("id") or uuid4().hex
            return []
        index = event.get("index")
        if not isinstance(index, int):
            return []
        if kind == "content_block_start":
            return self._open_block(index, event.get("content_block") or {})
        if kind == "content_block_delta":
            return self._delta(index, event.get("delta") or {})
        if kind == "content_block_stop":
            return self._close(index)
        return []

    def _open_block(self, index: int, block: dict[str, Any]) -> list[StreamEvent]:
        events = self._close(index)
        block_type = block.get("type")
        if block_type in ("text", "thinking"):
            stream_id = f"{self._message_id or uuid4().hex}:{index}"
            self._open[index] = (block_type, stream_id)
            if block_type == "text":
                events.append(MessageStart(message_id=stream_id))
                if block.get("text"):
                    events.append(TextDelta(message_id=stream_id, content=block["text"]))
            else:
                events.append(ReasoningStart(message_id=stream_id))
                if block.get("thinking"):
                    events.append(ReasoningDelta(message_id=stream_id, content=block["thinking"]))
        elif block_type in ("tool_use", "server_tool_use") and block.get("id"):
            self._open[index] = ("tool", block["id"])
            events.append(ToolCallStart(tool_call_id=block["id"], name=ClaudeToolBuilder.ak_tool_name(block.get("name") or "")))
        return events

    def _delta(self, index: int, delta: dict[str, Any]) -> list[StreamEvent]:
        opened = self._open.get(index)
        if opened is None:
            return []
        kind, stream_id = opened
        delta_type = delta.get("type")
        if kind == "text" and delta_type == "text_delta" and delta.get("text"):
            return [TextDelta(message_id=stream_id, content=delta["text"])]
        if kind == "thinking" and delta_type == "thinking_delta" and delta.get("thinking"):
            return [ReasoningDelta(message_id=stream_id, content=delta["thinking"])]
        if kind == "tool" and delta_type == "input_json_delta" and delta.get("partial_json"):
            return [ToolCallArgs(tool_call_id=stream_id, delta=delta["partial_json"])]
        return []

    def _close(self, index: int) -> list[StreamEvent]:
        opened = self._open.pop(index, None)
        if opened is None:
            return []
        kind, stream_id = opened
        if kind == "text":
            return [MessageEnd(message_id=stream_id)]
        if kind == "thinking":
            return [ReasoningEnd(message_id=stream_id)]
        return [ToolCallEnd(tool_call_id=stream_id)]

    @staticmethod
    def _as_text(value: Any) -> str:
        """
        :param value: A tool result: a string, a list of content blocks, or any JSON value.
        :return: The text content for `ToolCallResult`.
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value and all(isinstance(block, dict) and block.get("type") == "text" for block in value):
            return "".join(str(block.get("text", "")) for block in value)
        return json.dumps(value, default=str)


class ClaudeRunner(BaseRunner):
    """
    ClaudeRunner class provides a runner for Claude Agent SDK agents.

    Each run spawns its own `ClaudeSDKClient` (one Claude Code CLI subprocess), created after the ToolContext and
    `ToolContext` (with its per-run `framework_context`) are set so the in-process tool handlers, which run in tasks the client spawns, inherit
    them.
    """

    def __init__(self) -> None:
        """
        Initializes a ClaudeRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> ClaudeSession:
        """
        Returns the Claude session associated with the provided session.
        :param session: The session to retrieve the Claude session for.
        :return: ClaudeSession instance.
        """
        if session is None:
            return ClaudeSession()
        claude_session: ClaudeSession = session.get(FRAMEWORK) or session.set(FRAMEWORK, ClaudeSession())
        return claude_session

    @staticmethod
    def _split_data_uri(data: str, mime_type: str | None) -> tuple[str, str | None]:
        """
        :param data: Image or file data: a URL, base64, or a `data:<mime>;base64,<payload>` URI.
        :param mime_type: The request's explicit mime type, if any.
        :return: The data with any `data:` prefix removed, and the mime type (the URI's own when it has one).
        """
        if not data.startswith("data:"):
            return data, mime_type
        header, _, payload = data.partition(",")
        return payload, header[5:].split(";")[0] or mime_type

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[dict[str, Any]]]:
        """
        Process requests and extract prompt text and Anthropic content blocks.
        :param requests: The requests to process.
        :return: Tuple of (prompt, content).
        :raises ValueError: For an image or file the Claude Agent SDK cannot take.
        """
        prompt = ""
        content: list[dict[str, Any]] = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                prompt = prompt + "\n" + req.prompt if prompt else req.prompt
                content.append({"type": "text", "text": req.prompt})

            elif isinstance(req, AgentRequestImage):
                if not req.image_data:
                    raise ValueError("no image input provided")
                image_data, mime_type = ClaudeRunner._split_data_uri(req.image_data, req.mime_type)
                if image_data.startswith(("http://", "https://")):
                    content.append({"type": "image", "source": {"type": "url", "url": image_data}})
                elif image_data.startswith("s3://"):
                    raise ValueError("s3:// image references are not supported by the Claude Agent SDK; provide base64 data or an https URL")
                elif not mime_type:
                    raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                else:
                    content.append({"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_data}})

            elif isinstance(req, AgentRequestFile):
                if not req.file_data:
                    raise ValueError("no file input provided")
                file_data, mime_type = ClaudeRunner._split_data_uri(req.file_data, req.mime_type)
                if file_data.startswith(("http://", "https://")):
                    content.append({"type": "document", "source": {"type": "url", "url": file_data}})
                elif file_data.startswith("s3://"):
                    raise ValueError("s3:// file references are not supported by the Claude Agent SDK; provide base64 data or an https URL")
                elif not mime_type:
                    raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                elif mime_type == "application/pdf":
                    content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": file_data}})
                elif mime_type.startswith("text/"):
                    text = base64.b64decode(file_data).decode("utf-8", errors="replace")
                    content.append({"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": text}})
                else:
                    raise ValueError(f"file type '{mime_type}' is not supported by the Claude Agent SDK; send a PDF or a text file")

            elif isinstance(req, AgentRequestVoice):
                raise ValueError("voice input is not supported by the Claude Agent SDK; Claude models take no audio input")

        return prompt, content

    @staticmethod
    def _prompt(content: list[dict[str, Any]]) -> str | AsyncIterator[dict[str, Any]]:
        """
        Text-only content goes as a string (empty content becomes an empty string, which is how a bare resume
        decision carries no extra text); content with an image or document goes as one streaming-input user
        message, the only form the SDK accepts it in.
        :param content: The content blocks for this turn.
        :return: The prompt for `ClaudeSDKClient.query`.
        """
        if all(block["type"] == "text" for block in content):
            return "\n".join(block["text"] for block in content)

        async def message() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

        return message()

    @staticmethod
    def _gated_tools(spec: ClaudeAgentSpec) -> frozenset[str]:
        """
        :param spec: The agent declaration whose tools to inspect.
        :return: The fully-qualified `mcp__ak__<name>` names of its tools bound with `needs_approval=True`.
        """
        return frozenset(ClaudeToolBuilder.mcp_tool_name(tool.name) for tool in spec.tools if getattr(tool, "ak_needs_approval", False))

    def _decision_hook(self, gated: frozenset[str], resume_decision: tuple[str, ResumeDecision] | None) -> Any:
        """
        Builds the one `PreToolUse` hook that both gates approval-required tools and resolves the one deferred
        call a resume answers. One hook, not two: two hooks matching the same tool would race under the SDK's
        `deny > defer > ask > allow` precedence, where the still-standing gate's `defer` would override an
        `allow` the resume hook just granted for that call.

        :param gated: The tool names (see `_gated_tools`) that defer on their first attempt.
        :param resume_decision: The `(tool_use_id, decision)` a resume is answering, or None on an ordinary run.
        :return: The hook callback.
        """

        async def hook(input_data: dict[str, Any], tool_use_id: str | None, context: dict[str, Any]) -> dict[str, Any]:
            if resume_decision is not None and tool_use_id == resume_decision[0]:
                decision = resume_decision[1]
                name = input_data.get("tool_name")
                if decision.status == "approved" and name in gated:
                    guard = _approval_guard.get()
                    if guard is not None:
                        arguments = decision.payload if isinstance(decision.payload, dict) else input_data.get("tool_input", {})
                        guard.grant(name, arguments)
                return self._hook_decision(decision)
            if input_data.get("tool_name") in gated:
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}}
            return {}

        return hook

    def _hook_decision(self, decision: ResumeDecision) -> dict[str, Any]:
        """
        Renders a human's decision as the `PreToolUse` hook response that resolves the one deferred call it answers.

        :param decision: The human's decision. `approved` becomes `allow`, with the payload (if an object) as
            `updatedInput`; `denied` becomes `deny` with the human's message, if any; `cancelled` becomes `deny`
            with Agent Kernel's own wording, since the SDK has no third verb and "nobody decided" must not read
            as a refusal.
        :return: The raw hook response dict the SDK expects.
        """
        if decision.status == "approved":
            output: dict[str, Any] = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
            if isinstance(decision.payload, dict):
                output["updatedInput"] = decision.payload
            return {"hookSpecificOutput": output}
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
        reason = decision.message if decision.status == "denied" else self.CANCELLED_DECISION_MESSAGE
        if reason:
            output["permissionDecisionReason"] = reason
        return {"hookSpecificOutput": output}

    def _native_options(
        self,
        agent: Any,
        options: Mapping[str, Any],
        claude_session: ClaudeSession,
        *,
        stream: bool,
        resume_decision: tuple[str, ResumeDecision] | None = None,
    ) -> ClaudeAgentOptions:
        """
        Builds the options for one run: the agent's options, the resolved run options over them, and the fields
        Agent Kernel owns written last. The parent's bound tools are served by an in-process MCP server and
        approved by name, except one bound with `needs_approval=True`, which a merged `PreToolUse` hook gates
        instead; declared hooks are merged into, never replaced. Native `agents=` definitions are reached
        through the `Agent` tool.
        :param agent: The ClaudeAgent being run.
        :param options: The run options resolved for this run.
        :param claude_session: The ClaudeSession holding the agent's conversation.
        :param stream: Whether this is a streamed run.
        :param resume_decision: The `(tool_use_id, decision)` a resume answers, or None on an ordinary run.
        :return: A new ClaudeAgentOptions; the agent's own is untouched.
        """
        spec: ClaudeAgentSpec = agent.agent
        declared = dataclasses.replace(spec.options, **options)
        ak_owned: dict[str, Any] = {
            "session_store": claude_session,
            "session_store_flush": "batched",
            "resume": None,
            "session_id": None,
            "continue_conversation": False,
            "fork_session": False,
            "resume_session_at": None,
            "resume_drops_turn": None,
            "enable_file_checkpointing": False,
            "include_partial_messages": stream,
        }
        if claude_session.transcript(agent.name).get(""):
            ak_owned["resume"] = claude_session.session_id(agent.name)
        else:
            ak_owned["session_id"] = str(uuid4())
            claude_session.bind(agent.name, ak_owned["session_id"])
        # Native subagents can use the tools served in the parent's session.
        served = {tool.name: tool for tool in spec.tools}
        gated = self._gated_tools(spec)
        approved = [ClaudeToolBuilder.mcp_tool_name(name) for name in served if ClaudeToolBuilder.mcp_tool_name(name) not in gated]
        if served:
            server = create_sdk_mcp_server(ClaudeToolBuilder.MCP_SERVER, tools=list(served.values()))
            # A dict whenever the agent has tools: ClaudeAgent rejects a config-file path at declaration.
            servers = declared.mcp_servers if isinstance(declared.mcp_servers, dict) else {}
            ak_owned["mcp_servers"] = {**servers, ClaudeToolBuilder.MCP_SERVER: server}
        if declared.agents:
            if isinstance(declared.tools, list) and "Agent" not in declared.tools:
                ak_owned["tools"] = [*declared.tools, "Agent"]
            approved.append("Agent")
        if approved:
            ak_owned["allowed_tools"] = declared.allowed_tools + [name for name in approved if name not in declared.allowed_tools]
        if gated or resume_decision is not None:
            hooks = {event: list(matchers) for event, matchers in (declared.hooks or {}).items()}
            hooks.setdefault("PreToolUse", []).append(HookMatcher(matcher=None, hooks=[self._decision_hook(gated, resume_decision)]))
            ak_owned["hooks"] = hooks
        native: ClaudeAgentOptions = dataclasses.replace(spec.options, **self._native_kwargs(options, **ak_owned))
        return native

    @staticmethod
    def _error(result: ResultMessage) -> RuntimeError:
        """
        :param result: A ResultMessage with `is_error` set.
        :return: An error naming why the turn failed. An API failure arrives as subtype "success", so the HTTP
            status is named instead.
        """
        detail = "; ".join(result.errors or []) or result.result or ""
        if result.subtype != "success":
            reason = result.subtype
        else:
            reason = f"API error {result.api_error_status}" if result.api_error_status else "error result"
        return RuntimeError(f"Claude Agent SDK run failed ({reason}){': ' + detail if detail else ''}")

    def _paused_reply(self, agent: Any, session: Session, result: ResultMessage) -> AgentPausedReplyAny:
        """
        Records a paused run and returns the reply that carries it back to the caller.

        Replaces rather than appends: Claude's `defer` resolves exactly one pending tool call at a time, so an
        earlier record for this runner could never be resumed once a newer one exists. Scoped to this runner,
        since a pause another framework holds on the same session is a separate conversation and still
        answerable. The payload holds the deferred call's id and the saved transcript position, so a later
        ordinary turn cannot silently redirect a decision to the wrong conversation state. The conversation
        itself is durable through `ClaudeSession`.

        :param agent: The agent that paused.
        :param session: The session the record is written to.
        :param result: The ResultMessage whose `deferred_tool_use` is set.
        :return: The paused reply, carrying the assigned run id.
        """
        PausedRunState.clear_for_runner(session, self.name)

        deferred = result.deferred_tool_use
        assert deferred is not None  # the caller checks this before calling _paused_reply
        interruption = PausedInterruption(
            id=deferred.id,
            kind="tool_call",
            tool_name=ClaudeToolBuilder.ak_tool_name(deferred.name),
            arguments=json.dumps(deferred.input, default=str),
        )
        record = PausedRunState.add(
            session,
            agent=agent.name,
            runner=self.name,
            interruptions=[interruption],
            payload={
                "tool_use_id": deferred.id,
                "session_id": result.session_id,
                "main_entries": len(self._session(session).transcript(agent.name).get("", [])),
            },
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    def _require_resume_state(self, agent: Any, session: Session, record: PausedRun) -> None:
        """Reject a pause whose Claude transcript is missing or has advanced since it was recorded."""
        claude_session = session.get(FRAMEWORK)
        payload = record.payload
        if not isinstance(claude_session, ClaudeSession) or not isinstance(payload, dict):
            raise ValueError(f"Paused Claude run '{record.id}' has no saved conversation to resume")
        transcript = claude_session.transcript(agent.name).get("", [])
        if not transcript or claude_session.session_id(agent.name) != payload.get("session_id") or len(transcript) != payload.get("main_entries"):
            raise ValueError(f"Paused Claude run '{record.id}' cannot resume: its saved conversation changed after the pause")

    @staticmethod
    def _reject_not_the_one_deferred_call(decisions: list[ResumeDecision], record: PausedRun) -> None:
        """
        Refuses a resume that does not answer exactly the one call `defer` is waiting on, before the adapter's
        `try` opens. Claude's defer mechanism resolves a single pending tool call; Runtime's own generic checks
        (unknown interruption ids, a missing status) do not know that a Claude pause can only ever hold one.

        :param decisions: The human's decisions.
        :param record: The record Runtime validated.
        :raises ValueError: If more or fewer than the one expected decision is given.
        """
        expected = record.interruptions[0].id
        if len(decisions) != 1 or decisions[0].id != expected:
            raise ValueError(
                f"Claude Agent SDK resumes exactly the one deferred tool call in run '{record.id}' (interruption "
                f"'{expected}'); got decision(s) {[d.id for d in decisions]}. The SDK's defer mechanism answers a "
                f"single pending tool call at a time."
            )

    @staticmethod
    def _reject_unusable_override(decisions: list[ResumeDecision]) -> None:
        """
        Refuses an approval payload that cannot become the tool's updated input, before the adapter's `try` opens.

        :param decisions: The human's decisions.
        :raises ValueError: If an approved decision carries a payload that is not a JSON object.
        """
        offenders = [d.id for d in decisions if d.status == "approved" and d.payload is not None and not isinstance(d.payload, dict)]
        if offenders:
            raise ValueError(
                f"A Claude Agent SDK approval can only carry a JSON object as its payload; decision(s) {offenders} carry "
                f"another shape. The payload becomes the tool call's updated input, so send an object of argument names."
            )

    @property
    def supports_pause(self) -> bool:
        """
        :return: True — a `PreToolUse` hook's `defer` is durable (the transcript is already committed when the
            paused reply returns) and `resume=<session_id>` re-fires it. Only honored for a single tool call per
            turn; several at once fall through to the ordinary permission flow instead of pausing.
        """
        return True

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Claude agent with the provided multi modal inputs.
        :param agent: The Claude agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        context: ToolContext | None = None
        approval_token: contextvars.Token | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            approval_token = _approval_guard.set(_ClaudeApprovalGuard())
            prompt, content = self._process_requests(requests)

            if not content:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            context.framework_context = produced
            claude_session = self._session(session)

            texts: list[str] = []
            result: ResultMessage | None = None
            async with ClaudeSDKClient(options=self._native_options(agent, options, claude_session, stream=False)) as client:
                await client.query(self._prompt(content))
                async for message in client.receive_response():
                    if isinstance(message, ResultMessage):
                        result = message
                    elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
                        texts.extend(block.text for block in message.content if isinstance(block, TextBlock))

            if result is None:
                raise RuntimeError("Claude Agent SDK run ended without a result")

            if result.deferred_tool_use is not None and not result.is_error:
                self._store_framework_context(session, incoming, produced)
                return self._paused_reply(agent, session, result)
            if result.is_error:
                raise self._error(result)

            self._store_framework_context(session, incoming, produced)
            structured = AgentReplyAny.from_output(result.structured_output, prompt)
            if structured is not None:
                return structured
            return AgentReplyText(response=result.result if result.result is not None else "\n".join(texts), prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if approval_token is not None:
                _approval_guard.reset(approval_token)
            if context is not None:
                context.reset()

    async def resume(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AgentReply:
        """
        Continues a paused run from the human's decision on the one deferred tool call.

        The bare decision needs no accompanying text: `resume=<session_id>` replays the pending call, re-firing
        the same `PreToolUse` hook.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The continued run's reply, which may itself be paused again.
        """
        self._reject_not_the_one_deferred_call(decisions, record)
        self._reject_unusable_override(decisions)
        self._require_resume_state(agent, session, record)

        context: ToolContext | None = None
        approval_token: contextvars.Token | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            approval_token = _approval_guard.set(_ClaudeApprovalGuard())
            prompt, content = self._process_requests(requests)

            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            context.framework_context = produced
            claude_session = self._session(session)
            resume_decision = (record.payload["tool_use_id"], decisions[0])

            texts: list[str] = []
            result: ResultMessage | None = None
            native_options = self._native_options(agent, options, claude_session, stream=False, resume_decision=resume_decision)
            async with ClaudeSDKClient(options=native_options) as client:
                await client.query(self._prompt(content))
                async for message in client.receive_response():
                    if isinstance(message, ResultMessage):
                        result = message
                    elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
                        texts.extend(block.text for block in message.content if isinstance(block, TextBlock))

            if result is None:
                raise RuntimeError("Claude Agent SDK resume ended without a result")

            if result.deferred_tool_use is not None and not result.is_error:
                # A fresh pause (the same call deferred again, or a new one later in the turn) supersedes this
                # record; _paused_reply's clear_for_runner removes it as part of adding the new one.
                self._store_framework_context(session, incoming, produced)
                return self._paused_reply(agent, session, result)
            if result.is_error:
                raise self._error(result)

            PausedRunState.clear(session, record.id)
            self._store_framework_context(session, incoming, produced)
            structured = AgentReplyAny.from_output(result.structured_output, prompt)
            if structured is not None:
                return structured
            return AgentReplyText(response=result.result if result.result is not None else "\n".join(texts), prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if approval_token is not None:
                _approval_guard.reset(approval_token)
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the Claude agent response as Agent Kernel stream events. The client lives inside the generator, so
        closing the generator early disconnects it and stops the CLI.
        :param agent: The Claude agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        context: ToolContext | None = None
        approval_token: contextvars.Token | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            approval_token = _approval_guard.set(_ClaudeApprovalGuard())
            _, content = self._process_requests(requests)

            if not content:
                return

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            context.framework_context = produced
            claude_session = self._session(session)
            mapper = _ClaudeStreamMapper()  # local — the runner is shared across sessions

            result: ResultMessage | None = None
            async with ClaudeSDKClient(options=self._native_options(agent, options, claude_session, stream=True)) as client:
                await client.query(self._prompt(content))
                async for message in client.receive_response():
                    if isinstance(message, ResultMessage):
                        result = message
                        continue
                    for event in mapper.events(message):
                        yield event

            for event in mapper.close():
                yield event

            if result is None:
                raise RuntimeError("Claude Agent SDK stream ended without a result")

            if result.deferred_tool_use is not None and not result.is_error:
                try:
                    self._store_framework_context(session, incoming, produced)
                except Exception as e:
                    self._log_framework_context_stream_failure(session, e)
                paused = self._paused_reply(agent, session, result)
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
                return
            if result.is_error:
                raise self._error(result)

            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if approval_token is not None:
                _approval_guard.reset(approval_token)
            if context is not None:
                context.reset()

    async def resume_stream(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Streaming counterpart of `resume()`, mapping events exactly as `stream()` does and ending in `RunPaused`
        if the run pauses again.
        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The events the continued run produces.
        """
        self._reject_not_the_one_deferred_call(decisions, record)
        self._reject_unusable_override(decisions)
        self._require_resume_state(agent, session, record)

        context: ToolContext | None = None
        approval_token: contextvars.Token | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            approval_token = _approval_guard.set(_ClaudeApprovalGuard())
            _, content = self._process_requests(requests)

            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            context.framework_context = produced
            claude_session = self._session(session)
            mapper = _ClaudeStreamMapper()
            resume_decision = (record.payload["tool_use_id"], decisions[0])

            result: ResultMessage | None = None
            native_options = self._native_options(agent, options, claude_session, stream=True, resume_decision=resume_decision)
            async with ClaudeSDKClient(options=native_options) as client:
                await client.query(self._prompt(content))
                async for message in client.receive_response():
                    if isinstance(message, ResultMessage):
                        result = message
                        continue
                    for event in mapper.events(message):
                        yield event

            for event in mapper.close():
                yield event

            if result is None:
                raise RuntimeError("Claude Agent SDK resume stream ended without a result")

            if result.deferred_tool_use is not None and not result.is_error:
                try:
                    self._store_framework_context(session, incoming, produced)
                except Exception as e:
                    self._log_framework_context_stream_failure(session, e)
                paused = self._paused_reply(agent, session, result)
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
                return
            if result.is_error:
                raise self._error(result)

            PausedRunState.clear(session, record.id)
            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if approval_token is not None:
                _approval_guard.reset(approval_token)
            if context is not None:
                context.reset()


@dataclass
class ClaudeAgentSpec:
    """
    Declares a Claude Agent SDK agent. The SDK configures an agent with `ClaudeAgentOptions`, which carries no
    name or description; this adds those two and the agent's tools, and passes the options through
    unchanged.

    name: str : the name Agent Kernel registers the agent under
    description: str : what the main AK agent does, used for routing and its A2A card
    options: ClaudeAgentOptions : the SDK's options, passed to every run
    tools: list[SdkMcpTool] : in-process tools, from `ClaudeToolBuilder.bind` or the SDK's `@tool`
    """

    name: str
    description: str = ""
    options: ClaudeAgentOptions = field(default_factory=ClaudeAgentOptions)
    tools: list[SdkMcpTool] = field(default_factory=list)


class ClaudeAgent(BaseAgent):
    """
    ClaudeAgent class provides an agent wrapping for Claude Agent SDK agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "resume": "the runner resumes the Claude session stored on the Agent Kernel session",
        "session_id": "the runner assigns the Claude session id on a conversation's first turn",
        "continue_conversation": "the runner resumes the Claude session stored on the Agent Kernel session",
        "fork_session": "the runner keeps one transcript per agent conversation",
        "resume_session_at": "the runner keeps one transcript per agent conversation",
        "resume_drops_turn": "the runner keeps one transcript per agent conversation",
        "session_store": "the runner keeps the transcript on the Agent Kernel session through the ClaudeSession",
        "session_store_flush": "the runner sets how the SDK mirrors the transcript into the Agent Kernel session",
        "enable_file_checkpointing": "the SDK does not allow file checkpointing together with a SessionStore",
        "include_partial_messages": "set by the runner in stream mode, where its token events are mapped",
    }

    def __init__(self, name: str, runner: ClaudeRunner, spec: ClaudeAgentSpec) -> None:
        """
        Initializes a ClaudeAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param spec: The agent declaration. Its options and tool list are copied, so ones shared between
            declarations are not altered when this agent's system instructions and tools are added.
        """
        super().__init__(name, runner)
        spec.options = dataclasses.replace(spec.options)
        spec.tools = list(spec.tools)
        self._agent = spec
        self._attach_system_tools()
        self._setup_system_prompt()
        self._check_mcp_servers(spec.options.mcp_servers)

    @property
    def agent(self) -> ClaudeAgentSpec:
        """
        Returns the Claude agent declaration.
        """
        return self._agent

    def _check_mcp_servers(self, servers: Any) -> None:
        """
        :param servers: An `mcp_servers` value for this agent.
        :raises ValueError: If it names the server the runner serves the agent's tools from, or, for an agent with
            tools, is a config-file path the runner cannot add that server to.
        """
        if isinstance(servers, Mapping):
            if ClaudeToolBuilder.MCP_SERVER in servers:
                raise ValueError(f"MCP server name '{ClaudeToolBuilder.MCP_SERVER}' is reserved by the '{FRAMEWORK}' adapter for agent tools")
        elif self.agent.tools:
            raise ValueError(f"mcp_servers for agent '{self.name}' must be a dict, so the '{FRAMEWORK}' adapter can add its tool server")

    def validate_run_options(self, options: Mapping[str, Any]) -> None:
        """
        Rejects reserved keys, keys that are not ClaudeAgentOptions fields, and an `mcp_servers` value the runner
        cannot add its tool server to.
        :param options: The run options about to be declared for this agent.
        :raises ValueError: Naming the offending keys.
        """
        super().validate_run_options(options)
        unknown = sorted(set(options) - {f.name for f in dataclasses.fields(ClaudeAgentOptions)})
        if unknown:
            raise ValueError(f"Run option(s) {unknown} for agent '{self.name}' are not ClaudeAgentOptions fields")
        if "mcp_servers" in options:
            self._check_mcp_servers(options["mcp_servers"])

    def get_description(self) -> str:
        """
        Returns the description of the agent, falling back to a plain-string system prompt.
        """
        if self.agent.description:
            return self.agent.description
        prompt = self.agent.options.system_prompt
        return prompt if isinstance(prompt, str) else ""

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends additional instructions to the system prompt in the form it was declared: a string, a custom
        prompt, or the `claude_code` preset's `append`. The SDK's default (None) sends an empty system prompt, so
        the instructions become the prompt. A prompt loaded from a file cannot be extended.
        :param prompt: The instruction text to append. Text the prompt already carries is not added again, so
            wrapping the same declaration twice does not repeat it, as the other adapters.
        """
        if not prompt:
            return
        current = self.agent.options.system_prompt
        declared: dict[str, Any] = dict(current) if isinstance(current, Mapping) else {}
        existing = current if isinstance(current, str) else str(declared.get("append") or declared.get("prompt") or "")
        if prompt in existing:
            return
        if current is None:
            updated: Any = prompt
        elif isinstance(current, str):
            updated = f"{current}\n\n{prompt}"
        elif declared.get("type") == "preset":
            updated = {**declared, "append": f"{declared['append']}\n\n{prompt}" if declared.get("append") else prompt}
        elif declared.get("type") == "custom":
            updated = {**declared, "prompt": f"{declared.get('prompt', '')}\n\n{prompt}"}
        else:
            _log.warning(f"Agent '{self.name}' loads its system prompt from a file, which cannot be extended; system instructions were not added")
            return
        self.agent.options.system_prompt = updated

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable, wraps it with ClaudeToolBuilder, and adds it to the agent's tools unless a tool of
        that name is already present. Called by the base Agent._attach_system_tools() at init.
        :param tool: Raw Python callable to attach.
        """
        names = {t.name for t in self.agent.tools}
        self.agent.tools.extend(t for t in ClaudeToolBuilder.bind([tool]) if t.name not in names)

    def get_a2a_card(self) -> Any:
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = [AgentSkill(id=t.name, name=t.name, description=t.description or "", tags=[]) for t in self.agent.tools]
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class ClaudeModule(Module):
    """
    ClaudeModule class provides a module for Claude Agent SDK agents.
    """

    def __init__(self, agents: list[ClaudeAgentSpec], runner: ClaudeRunner | None = None) -> None:
        """
        Initializes a ClaudeModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        self.runner: ClaudeRunner
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = typing.cast(ClaudeRunner, Trace.get().claude())
        else:
            self.runner = ClaudeRunner()
        self.load(agents)

    def _wrap(self, agent: ClaudeAgentSpec, agents: List[ClaudeAgentSpec]) -> BaseAgent:
        """
        Wraps the provided agent in a ClaudeAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: ClaudeAgent instance.
        :raises ValueError: If the agent has no name.
        """
        if not agent.name:
            raise ValueError("ClaudeAgentSpec passed to ClaudeModule must have a name")
        return ClaudeAgent(agent.name, self.runner, agent)

    def load(self, agents: list[ClaudeAgentSpec]) -> ClaudeModule:
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: ClaudeModule instance.
        """
        super().load(agents)
        return self


class ClaudeToolBuilder(ToolBuilder):
    """
    Tool builder for the Claude Agent SDK. Wraps generic tool functions into the SDK's in-process `SdkMcpTool`s;
    AK tools reach execution context via `ToolContext.get()`, whose `framework_context` is the per-run caller state.
    """

    MCP_SERVER: ClassVar[str] = "ak"
    """The in-process MCP server the runner serves an agent's tools from; the model calls them mcp__ak__<tool>."""

    @classmethod
    def bind(cls, funcs: list[Callable], *, needs_approval: bool = False, **options: Any) -> list[SdkMcpTool]:
        """
        Bind generic tool functions to Claude Agent SDK tools.

        Keyword options become the tools' `ToolAnnotations` (e.g. `readOnlyHint=True`, `maxResultSizeChars=N`) and
        apply to every function in the call, so tools wanting different options are bound in separate calls.

        `needs_approval` is this adapter's human-in-the-loop gate — the SDK has no such flag, so it is recorded
        as a plain extra attribute on the returned `SdkMcpTool`, invisible to the wire protocol, and read back by
        `ClaudeRunner` to build the gating hook. The handler also requires a matching one-use approval, so a
        parallel call that the SDK cannot defer cannot execute through a permissive permission setting.

        :param funcs: List of generic tool functions to bind.
        :param needs_approval: If True, calling this tool defers for a human decision instead of running
            immediately; see `Runner.supports_pause` for the single-tool-call-per-turn limit this is subject to.
        :param options: Keyword arguments for `ToolAnnotations`.
        :return: List of `SdkMcpTool` definitions.
        :raises TypeError: If any item in funcs is not callable.
        """
        annotations = ToolAnnotations(**options) if options else None
        tools = [cls._wrap(func, annotations) for func in funcs]
        for tool in tools:
            setattr(tool, "ak_needs_approval", needs_approval)  # noqa: B010 — SdkMcpTool has no such field
            if needs_approval:
                original = tool.handler

                async def guarded(args: dict[str, Any], *, _name: str = tool.name, _handler: Callable = original) -> dict[str, Any]:
                    guard = _approval_guard.get()
                    if guard is None or not guard.consume(cls.mcp_tool_name(_name), args):
                        return {"content": [{"type": "text", "text": "Agent Kernel approval is required for this tool call."}], "isError": True}
                    return await _handler(args)

                tool.handler = guarded
        return tools

    @classmethod
    def mcp_tool_name(cls, name: str) -> str:
        """
        :param name: A tool name.
        :return: The name the model calls the tool by, for example in an `AgentDefinition`'s `tools`.
        """
        return f"mcp__{cls.MCP_SERVER}__{name}"

    @classmethod
    def ak_tool_name(cls, name: str) -> str:
        """
        :param name: A tool name as the model or SDK reported it.
        :return: The bare name, with this adapter's `mcp__ak__` prefix removed if present; any other name is
            returned unchanged (a built-in tool, or one from a different MCP server).
        """
        return name.removeprefix(f"mcp__{cls.MCP_SERVER}__")

    @classmethod
    def _wrap(cls, func: Callable, annotations: ToolAnnotations | None) -> SdkMcpTool:
        """
        Wraps a generic tool function as an `SdkMcpTool`. The SDK takes a JSON schema rather than a function, so the
        schema is built from the signature (parameters without a default are required) and the description is the
        docstring. Sync functions run on a worker thread, which keeps the SDK's message loop serviced.

        :param func: The generic tool function to wrap.
        :param annotations: The annotations to attach, if any.
        :return: The SdkMcpTool serving the function.
        :raises TypeError: If the function is not callable or has variadic parameters that cannot be represented in the MCP schema.
        """
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__}")

        name = getattr(func, "__name__", type(func).__name__)
        hints = typing.get_type_hints(func)
        fields: dict[str, Any] = {}
        parameters = list(inspect.signature(func).parameters.values())
        for param in parameters:
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                raise TypeError(f"Tool '{name}' cannot bind variadic parameter '{param.name}' to an MCP input schema")
            annotation = hints.get(param.name, Any if param.annotation is inspect.Parameter.empty else param.annotation)
            fields[param.name] = (annotation, Field(... if param.default is inspect.Parameter.empty else param.default))
        arguments = create_model(f"{name}_arguments", **fields)
        is_async = inspect.iscoroutinefunction(func)

        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            values = arguments.model_validate(args)
            positional = [getattr(values, param.name) for param in parameters if param.kind is inspect.Parameter.POSITIONAL_ONLY]
            kwargs = {param.name: getattr(values, param.name) for param in parameters if param.kind is not inspect.Parameter.POSITIONAL_ONLY}
            result = await func(*positional, **kwargs) if is_async else await asyncio.to_thread(func, *positional, **kwargs)
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            return {"content": [{"type": "text", "text": text}]}

        description = inspect.getdoc(func) or name
        return SdkMcpTool(name=name, description=description, input_schema=arguments.model_json_schema(), handler=handler, annotations=annotations)
