from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, AsyncIterator, Callable, ClassVar, Iterator, List, Mapping, Optional, Sequence
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel

from ...core import Agent as BaseAgent
from ...core import Module as BaseModule
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
    AgentRequestText,
    ResumeDecision,
)
from ...core.paused_run import PausedRun, PausedRunState
from ...core.tool import SystemToolFactory
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "langgraph"
_logger = logging.getLogger("ak.langgraph.runner")

INTERRUPT_KEY = "__interrupt__"
"""The key `ainvoke` returns a graph's pending `interrupt()` calls under.

Spelled literally rather than imported as `langgraph.constants.INTERRUPT`, which still resolves at
1.2.11 but raises `LangGraphDeprecatedSinceV10` on access."""


class CheckPointer(BaseCheckpointSaver):
    """
    A pickle-serializable checkpointer implementation for LangGraph.
    This stores checkpoint data in a simple dictionary structure that can be pickled

    **Pending writes are part of the contract, not an optimisation.** A graph that calls
    `interrupt()` records the pause as a write, and `Command(resume=...)` records the answer the
    same way; both are invisible unless `get_tuple` hands them back on `CheckpointTuple.pending_writes`.
    Without that, `aget_state(...).interrupts` is always empty and a resume silently re-runs the node
    from the top — which is how human-in-the-loop (#606) found this. Writes are keyed by
    `(thread_id, checkpoint_ns, checkpoint_id)` and `(task_id, index)`, mirroring LangGraph's own
    `InMemorySaver`, so writes from one turn cannot leak into the next and a replayed task replaces
    rather than duplicates its entries.
    """

    def __init__(self):
        super().__init__()
        self._storage = {}
        self._writes = {}

    def __getstate__(self) -> dict:
        """
        Pickles the stored data only, leaving the inherited serializer behind.

        `BaseCheckpointSaver.__init__` attaches a `JsonPlusSerializer` whose msgpack hook is a
        closure, so the default `__dict__` pickle of this object fails — and because the session
        store pickles the whole session, that made a LangGraph session silently unstorable on every
        shared backend. Only `_storage` and `_writes` carry state worth keeping; the serializer is
        rebuilt on load.

        :return: The picklable half of this checkpointer's state.
        """
        return {"_storage": self._storage, "_writes": self._writes}

    def __setstate__(self, state: dict) -> None:
        """
        Restores the stored data and rebuilds the serializer `__getstate__` dropped.

        :param state: What `__getstate__` returned.
        """
        BaseCheckpointSaver.__init__(self)
        self._storage = state.get("_storage", {})
        self._writes = state.get("_writes", {})

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        if not thread_id:
            return None

        thread_data = self._storage.get(thread_id, {})
        checkpoint_data = thread_data.get(checkpoint_ns)

        if checkpoint_data is None:
            return None

        checkpoint = checkpoint_data["checkpoint"]
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=checkpoint_data.get("metadata", {}),
            parent_config=checkpoint_data.get("parent_config"),
            pending_writes=self._pending_writes(thread_id, checkpoint_ns, checkpoint.get("id", "")),
        )

    def list(
        self,
        config: Optional[dict] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        result = []
        if config:
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id and thread_id in self._storage:
                thread_data = self._storage[thread_id]
                for ns, data in thread_data.items():
                    checkpoint_config: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}}
                    result.append(
                        CheckpointTuple(
                            config=checkpoint_config,
                            checkpoint=data["checkpoint"],
                            metadata=data.get("metadata", {}),
                            parent_config=data.get("parent_config"),
                        )
                    )
                if limit:
                    result = result[:limit]
        return iter(result)

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        if not thread_id:
            raise ValueError("thread_id is required in config")

        if thread_id not in self._storage:
            self._storage[thread_id] = {}

        self._storage[thread_id][checkpoint_ns] = {
            "checkpoint": checkpoint,
            "metadata": metadata,
            "parent_config": config.get("parent_config"),
        }

        return config

    def put_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        Records one task's writes against the checkpoint they belong to.

        The negative indices in `WRITES_IDX_MAP` are what make a replayed task overwrite its own
        `__interrupt__` / `__resume__` entries instead of stacking a second copy; every other
        channel keeps its first write, matching LangGraph's own saver.

        :param config: The config naming the thread, namespace and checkpoint.
        :param writes: Channel/value pairs the task produced.
        :param task_id: The task that produced them.
        :param task_path: The task's path, kept for parity with the base contract.
        """
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return

        outer = self._writes.setdefault((thread_id, configurable.get("checkpoint_ns", ""), configurable.get("checkpoint_id", "")), {})
        for idx, (channel, value) in enumerate(writes):
            inner = (task_id, WRITES_IDX_MAP.get(channel, idx))
            if inner[1] >= 0 and inner in outer:
                continue
            outer[inner] = (task_id, channel, value, task_path)

    def _pending_writes(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> list[tuple[str, str, Any]]:
        """
        The writes recorded against one checkpoint, in the shape `CheckpointTuple` expects.

        :param thread_id: The thread the checkpoint belongs to.
        :param checkpoint_ns: The checkpoint namespace.
        :param checkpoint_id: The checkpoint the writes were made against.
        :return: (task_id, channel, value) triples, empty when nothing is recorded.
        """
        recorded = self._writes.get((thread_id, checkpoint_ns, checkpoint_id), {})
        return [(task_id, channel, value) for task_id, channel, value, _ in recorded.values()]

    def delete_thread(self, thread_id: str) -> None:
        if thread_id in self._storage:
            del self._storage[thread_id]
        for key in [key for key in self._writes if isinstance(key, tuple) and key[0] == thread_id]:
            del self._writes[key]

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        return self.get_tuple(config)

    async def alist(
        self,
        config: Optional[dict] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)


class LangGraphSessionConfigurable(BaseModel):
    thread_id: str


class LangGraphSessionConfigModel(BaseModel):
    configurable: LangGraphSessionConfigurable


class LangGraphAgent(BaseAgent):
    """
    LangGraphAgent class provides an agent wrapping for LangGraph Agents SDK based agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "input": "the graph input state is built from the messages and framework_context by the runner",
        "version": "the stream path fixes astream_events(version='v2')",
        "stream_mode": "the runner reads result['messages'] and result.get('structured_response'); a changed result shape breaks the reply mapping",
        "output_keys": "the runner reads result['messages'] and result.get('structured_response'); a changed result shape breaks the reply mapping",
        "print_mode": "the runner reads result['messages'] and result.get('structured_response'); a changed result shape breaks the reply mapping",
    }

    RUNNABLE_CONFIG_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"callbacks", "tags", "metadata", "run_name", "max_concurrency", "recursion_limit", "configurable", "run_id"}
    )
    """RunnableConfig keys; declared at the top level LangGraph drops them silently, so they are rejected there."""

    def validate_run_options(self, options: Mapping[str, Any]) -> None:
        """
        Rejects reserved keys, a RunnableConfig key declared at the top level (ainvoke / astream_events ignore unknown
        keywords, so it would silently never apply), and the nested `config.configurable.thread_id`, which is the
        Agent Kernel session id.
        :param options: The run options about to be declared for this agent.
        :raises ValueError: Naming the offending key.
        """
        super().validate_run_options(options)
        misplaced = sorted(set(options) & self.RUNNABLE_CONFIG_KEYS)
        if misplaced:
            details = ", ".join(f"'{key}'" for key in misplaced)
            raise ValueError(
                f"Run option(s) {details} for agent '{self.name}' are RunnableConfig keys and belong inside config={{...}}; "
                f"the '{self.runner.name}' adapter rejects them at the top level because LangGraph would silently drop them"
            )
        config = options.get("config")
        if isinstance(config, Mapping) and "thread_id" in (config.get("configurable") or {}):
            raise ValueError(
                f"Run option 'config.configurable.thread_id' is reserved by the '{self.runner.name}' adapter for agent "
                f"'{self.name}': the thread id is the Agent Kernel session id"
            )

    def __init__(self, name: str, runner: "LangGraphRunner", agent: CompiledStateGraph):
        """
        Initializes a LangGraphAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The LangGraph agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._tools: list[Any] = []
        self._system_prompt: str = ""
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> CompiledStateGraph:
        """
        Returns the LangGraph CompiledStateGraph instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        # TODO improve this description
        return "I am a LangGraph agent."

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        graph = self.agent.get_graph()
        skills = []
        for node_name, node_data in graph.nodes.items():
            # TODO improve this to better extract tools
            if hasattr(node_data, "tools"):
                for tool in node_data.tools:
                    skills.append(
                        AgentSkill(
                            id=tool.name,
                            name=tool.name,
                            description=tool.description,
                            tags=[],
                        )
                    )
        # TODO extract description from graph
        return A2ACardBuilder.build(name=self.name, description="", skills=skills)

    def attach_tool(self, tool: Any) -> None:
        """
        Satisfies the base Agent contract, but does nothing for LangGraph.
        LangGraph tools must be bound explicitly via LangGraphToolBuilder.bind()
        before the CompiledStateGraph is created, because the graph is immutable.
        """
        pass

    def override_system_prompt(self, prompt: str) -> None:
        """
        Stores the system prompt suffix on the agent wrapper.
        The runner injects this as a SystemMessage on the first turn of each session,
        so the LLM receives tool instructions with the correct role.
        Follows the same pattern as ADK, OpenAI, and CrewAI.
        """
        if prompt not in self._system_prompt:
            self._system_prompt += ("\n" if self._system_prompt else "") + prompt


class LangGraphSession:
    """
    LangGraphSession class provides a session for LangGraph Agents SDK-based agents
    """

    def __init__(self):
        """
        Initializes a LangGraphSession instance with a pickle-serializable checkpointer.
        """
        self._checkpointer = CheckPointer()
        self._system_prompt_injected: bool = False

    @property
    def checkpointer(self):
        return self._checkpointer


class LangGraphRunner(BaseRunner):
    """
    LangGraphRunner class provides a runner for LangGraph Agents SDK-based agents.
    """

    def __init__(self):
        """
        Initializes a LangGraphRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    if item.strip():
                        text_parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text)
            if text_parts:
                return " ".join(text_parts)
            # No usable text parts found - log structured content for debugging
            _logger.debug("No usable text parts extracted from content list: %s", content)
            return ""
        # Fallback: log and return empty string instead of str(content)
        _logger.debug("Unable to extract text from content type %s: %s", type(content).__name__, content)
        return ""

    @staticmethod
    def _session(session: Session) -> Any | None:
        """
        Returns the LangGraph session associated with the provided session.
        :param session: The session to retrieve the LangGraph session for.
        :return: LangGraphSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, LangGraphSession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, bool]:
        """
        Process requests and extract prompt text.
        :param requests: The requests to process.
        :return: Tuple of (prompt, is_valid).
        """
        prompt = ""
        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue
            if isinstance(req, AgentRequestText):
                prompt = prompt + "\n" + req.prompt if prompt else req.prompt
            else:
                return prompt, False
        return prompt, True

    def _prepare_session_and_messages(self, agent: Any, session: Session, prompt: str) -> tuple[dict, list]:
        """
        Prepare session config and messages for LangGraph agent.
        :param agent: The LangGraph agent.
        :param session: The AgentKernel session.
        :param prompt: The prompt text.
        :return: Tuple of (session_config, messages).
        """
        session_config = LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=session.id))
        lg_session = self._session(session)
        agent.agent.checkpointer = lg_session.checkpointer

        messages = []
        system_prompt = getattr(agent, "_system_prompt", "")
        if system_prompt and not lg_session._system_prompt_injected:
            messages.append(SystemMessage(content=system_prompt))
            lg_session._system_prompt_injected = True
        messages.append(HumanMessage(content=prompt))

        return session_config.model_dump(), messages

    @staticmethod
    def _merge_run_config(base: dict, caller: Mapping[str, Any] | None) -> dict:
        """
        Deep-merges a caller's declared `config` under the RunnableConfig the runner built.
        Dict-valued keys merge with the runner's entries winning (so `configurable.thread_id` stays the session id
        while every other `configurable` entry is the caller's); list-valued keys concatenate with the runner's
        entries first (so a trace runner's callback handler is kept beside the caller's callbacks); any other key
        the runner set wins. Neither input is mutated.
        :param base: The config the runner built (possibly decorated by a trace runner).
        :param caller: The caller's declared `config` run option, or None.
        :return: A new merged config dict.
        """
        merged: dict[str, Any] = dict(caller or {})
        for key, value in base.items():
            current = merged.get(key)
            if isinstance(value, Mapping) and isinstance(current, Mapping):
                merged[key] = {**current, **value}
            elif isinstance(value, list) and isinstance(current, list):
                merged[key] = [*value, *(item for item in current if item not in value)]
            else:
                merged[key] = value
        return merged

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the LangGraph agent with provided multi modal inputs.

        A pending `interrupt()` is checked before either reply mapping: on an interrupted run
        `messages[-1]` is whatever the graph said on its way to stopping, so reading it first turns
        a pause into a partial answer.

        :param agent: The LangGraph agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, is_valid = self._process_requests(requests)

            if not is_valid:
                return AgentReplyText(
                    response="Sorry. Agent kernel LangGraph runner is unable to handle content other than text at the moment",
                    prompt=prompt,
                )

            if prompt.strip() == "":
                return AgentReplyText(response="Sorry. No valid text prompt found in the requests")

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            config, messages = self._prepare_session_and_messages(agent, session, prompt)

            # Spread the context's top-level keys into the input state so they map onto the graph's state
            # channels. `messages` is written last so a caller key cannot replace it.
            incoming = self._load_framework_context(session)
            input_state: dict[str, Any] = {}
            if incoming:
                input_state.update(incoming)
            input_state["messages"] = messages

            # Resolved run options first; `input` and the merged `config` are written last.
            kwargs = self._native_kwargs(
                options,
                input=input_state,
                config=self._merge_run_config(config, options.get("config")),
            )
            result = await agent.agent.ainvoke(**kwargs)

            # Only keys the graph declares as state channels come back on `result`; the rest keep their value.
            if incoming is not None:
                produced = {k: result[k] for k in incoming if k in result}
                self._store_framework_context(session, incoming, produced)

            if INTERRUPT_KEY in result:
                return self._paused_reply(agent, session, result[INTERRUPT_KEY])

            structured = AgentReplyAny.from_output(result.get("structured_response"), prompt)
            if structured is not None:
                return structured
            last_message = result["messages"][-1]
            return AgentReplyText(response=self._extract_text_content(last_message.content), prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    @property
    def supports_pause(self) -> bool:
        """
        :return: True — `interrupt()` parks the graph in AK's own checkpointer, which the session persists.
        """
        return True

    def _paused_reply(self, agent: Any, session: Session, interrupts: Sequence[Any]) -> AgentPausedReplyAny:
        """
        Records a paused graph and returns the reply that carries it back to the caller.

        Replaces rather than appends: LangGraph keeps one thread per session (`thread_id` is the
        session id), so a second pause is the same conversation stopping again and the earlier
        record could never be resumed. Only OpenAI, whose `RunState` is a self-contained snapshot,
        can genuinely hold two.

        The record's own payload is deliberately thin — the graph state lives in AK's checkpointer,
        which the session already persists, so there is nothing framework-shaped to store. Each
        question's own shape rides on `PausedInterruption.payload`, exactly as the node passed it
        to `interrupt()`.

        :param agent: The agent that paused.
        :param session: The session the record is written to.
        :param interrupts: The `Interrupt` objects the graph returned.
        :return: The paused reply, carrying the assigned run id.
        """
        for stale in PausedRunState.list(session):
            PausedRunState.clear(session, stale.id)

        record = PausedRunState.add(
            session,
            agent=agent.name,
            interruptions=[PausedInterruption(id=item.id, kind="input_required", payload=item.value) for item in interrupts],
            payload={"thread_id": session.id},
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    @staticmethod
    def _decision_value(decision: ResumeDecision) -> Any:
        """
        The value a node's `interrupt()` call returns for one decision.

        The human's own answer, not an Agent-Kernel envelope: a node written as
        `choice = interrupt("pick one")` gets the choice. `payload` wins because it is the
        structured answer, `message` is the free-text one, and the bare status verb is what is left
        when the human only pressed a button — so `"cancelled"` reaches the node as `"cancelled"`.

        :param decision: One human decision.
        :return: The value to resume that interrupt with.
        """
        if decision.payload is not None:
            return decision.payload
        if decision.message:
            return decision.message
        return decision.status

    def _resume_config(self, agent: Any, session: Session) -> dict:
        """
        The RunnableConfig a resume addresses, with AK's checkpointer reattached.

        Deliberately not `_prepare_session_and_messages`: that also appends a `HumanMessage` and
        consumes the one-shot system-prompt injection, both of which belong to a new turn rather
        than to continuing a parked one.

        :param agent: The agent being resumed.
        :param session: The session whose id is the graph's `thread_id`.
        :return: The config dict addressing this session's thread.
        """
        agent.agent.checkpointer = self._session(session).checkpointer
        return LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=session.id)).model_dump()

    def _resume_command(self, decisions: list[ResumeDecision], prompt: str) -> Command:
        """
        Builds the `Command` that continues the graph.

        A prompt riding along with a decision has no native LangGraph feature — `Command.update`
        means *update the graph state*. Agent Kernel encodes it as a write to the `messages`
        channel its adapter already feeds, so the prompt reaches the model the same way an ordinary
        turn's would. **This mapping is Agent Kernel's, not LangGraph's**, and the adapter docs say so.

        :param decisions: The human's decisions.
        :param prompt: Text sent alongside them, empty when there is none.
        :return: The command to invoke the graph with.
        """
        resume = {decision.id: self._decision_value(decision) for decision in decisions}
        if prompt.strip():
            return Command(resume=resume, update={"messages": [HumanMessage(content=prompt)]})
        return Command(resume=resume)

    async def resume(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AgentReply:
        """
        Continues a paused graph from the human's decisions.

        The interrupting node **re-runs from the top** on resume — LangGraph replays it rather than
        continuing inside it — so any side effect before its `interrupt()` call happens twice. That
        is the framework's behaviour, not Agent Kernel's, and the docs pass it through verbatim.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The continued run's reply, which may itself be paused again.
        """
        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, _ = self._process_requests(requests)

            options = await agent.resolve_run_options(session, requests)
            config = self._resume_config(agent, session)
            incoming = self._load_framework_context(session)

            kwargs = self._native_kwargs(
                options,
                input=self._resume_command(decisions, prompt),
                config=self._merge_run_config(config, options.get("config")),
            )
            result = await agent.agent.ainvoke(**kwargs)

            if incoming is not None:
                produced = {k: result[k] for k in incoming if k in result}
                self._store_framework_context(session, incoming, produced)

            PausedRunState.clear(session, record.id)

            if INTERRUPT_KEY in result:
                return self._paused_reply(agent, session, result[INTERRUPT_KEY])

            structured = AgentReplyAny.from_output(result.get("structured_response"), prompt)
            if structured is not None:
                return structured
            return AgentReplyText(response=self._extract_text_content(result["messages"][-1].content), prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the LangGraph agent response as Agent Kernel stream events.

        Correlation ids are LangChain `run_id`s (one per runnable invocation), so nested model
        calls do not collide. Tool arguments arrive whole on `on_tool_start` and are emitted as a
        single fragment — LangChain has no per-token argument stream.

        The state read-back after the drain is also the only place a streamed pause is visible,
        since `astream_events` carries no interrupt event. A failed read loses both concerns, so it
        logs the established framework-context message and a second one naming the missed pause.

        :param agent: The LangGraph agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, is_valid = self._process_requests(requests)

            if not is_valid:
                return

            if prompt.strip() == "":
                return

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            config, messages = self._prepare_session_and_messages(agent, session, prompt)

            incoming = self._load_framework_context(session)
            started: set[str] = set()  # run ids with an open MessageStart; local, never on self
            reasoning: dict[str, str] = {}  # run id -> open reasoning stream id; local for the same reason
            input_state: dict[str, Any] = {}
            if incoming:
                input_state.update(incoming)
            input_state["messages"] = messages

            # One merged config for the stream call and the state read-back below, so both address the same checkpoint.
            merged_config = self._merge_run_config(config, options.get("config"))
            kwargs = self._native_kwargs(options, input=input_state, config=merged_config, version="v2")
            async for event in agent.agent.astream_events(**kwargs):
                for stream_event in self._map_event(event, started, reasoning):
                    yield stream_event

            # astream_events yields events, not a final state, so read the state back once the stream drains
            # normally. A disconnect or mid-stream error unwinds first, leaving the stored context intact.
            state = None
            try:
                state = await agent.agent.aget_state(merged_config)
            except Exception as e:
                if incoming is not None:
                    self._log_framework_context_stream_failure(session, e)
                _logger.warning(
                    f"LangGraph state could not be read back after the stream drained for session '{session.id}', "
                    f"so a pause this run may have produced is not reported: {e!r}"
                )

            if state is not None:
                if incoming is not None:
                    try:
                        produced = {k: state.values[k] for k in incoming if k in state.values}
                        self._store_framework_context(session, incoming, produced)
                    except Exception as e:
                        self._log_framework_context_stream_failure(session, e)

                if state.interrupts:
                    paused = self._paused_reply(agent, session, state.interrupts)
                    yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
        finally:
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
        Streaming counterpart of `resume()`, mapping events exactly as `stream()` does.

        Like `stream()`, the pause is only visible in the state read back after the drain, and a
        failed read logs both the framework-context message and the missed pause.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The events the continued graph produces, ending in RunPaused if it pauses again.
        """
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, _ = self._process_requests(requests)

            options = await agent.resolve_run_options(session, requests)
            config = self._resume_config(agent, session)
            incoming = self._load_framework_context(session)
            started: set[str] = set()
            reasoning: dict[str, str] = {}

            merged_config = self._merge_run_config(config, options.get("config"))
            kwargs = self._native_kwargs(
                options,
                input=self._resume_command(decisions, prompt),
                config=merged_config,
                version="v2",
            )
            async for event in agent.agent.astream_events(**kwargs):
                for stream_event in self._map_event(event, started, reasoning):
                    yield stream_event

            state = None
            try:
                state = await agent.agent.aget_state(merged_config)
            except Exception as e:
                if incoming is not None:
                    self._log_framework_context_stream_failure(session, e)
                _logger.warning(
                    f"LangGraph state could not be read back after the resumed stream drained for session '{session.id}', "
                    f"so a pause this run may have produced is not reported: {e!r}"
                )

            PausedRunState.clear(session, record.id)

            if state is not None:
                if incoming is not None:
                    try:
                        produced = {k: state.values[k] for k in incoming if k in state.values}
                        self._store_framework_context(session, incoming, produced)
                    except Exception as e:
                        self._log_framework_context_stream_failure(session, e)

                if state.interrupts:
                    paused = self._paused_reply(agent, session, state.interrupts)
                    yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
        finally:
            if context is not None:
                context.reset()

    @staticmethod
    def _map_event(event: dict, started: set[str], reasoning: dict[str, str]) -> list[StreamEvent]:
        """
        Translate one LangChain `astream_events` event into AK events.

        `MessageStart` is deferred until text arrives: LangChain fires chat-model start/end even
        on tool-only turns, and unconditional bracketing would emit an empty assistant message
        (§4 rule 4). `started` is keyed by `run_id` (not a single flag) so nested calls close
        correctly, and must stay a per-stream local — a `Runner` is shared across sessions.
        Chain/prompt/etc. events are ignored (`on_chain_*` is too coarse for `StepStart`/`StepEnd`).

        Reasoning is a second boundary stream with its own id (message id is already `run_id`).
        A reasoning id is generated on first use and stored in `reasoning` per `run_id`. Per chunk,
        reasoning opens first; answer text closes any open reasoning stream before the message
        opens (same order as the ADK adapter).

        :param event: One event from `astream_events(version="v2")`.
        :param started: Run ids whose `MessageStart` has been emitted. Mutated in place.
        :param reasoning: Run id to its open reasoning stream's id. Mutated in place.
        :return: The AK events this event produces, or an empty list when unmapped.
        """
        kind = event["event"]
        run_id = event["run_id"]

        if kind == "on_chat_model_end":
            closing: list[StreamEvent] = []
            thinking_id = reasoning.pop(run_id, None)
            if thinking_id is not None:
                closing.append(ReasoningEnd(message_id=thinking_id))
            if run_id in started:
                started.discard(run_id)
                closing.append(MessageEnd(message_id=run_id))
            return closing
        if kind == "on_chat_model_stream":
            texts, thoughts = LangGraphRunner._chunk_content(event)
            if not texts and not thoughts:
                return []
            events: list[StreamEvent] = []

            if thoughts:
                thinking_id = reasoning.get(run_id)
                if thinking_id is None:
                    thinking_id = uuid4().hex
                    reasoning[run_id] = thinking_id
                    events.append(ReasoningStart(message_id=thinking_id))
                events.extend(ReasoningDelta(message_id=thinking_id, content=thought) for thought in thoughts)

            if texts:
                thinking_id = reasoning.pop(run_id, None)
                if thinking_id is not None:
                    events.append(ReasoningEnd(message_id=thinking_id))
                if run_id not in started:
                    started.add(run_id)
                    events.append(MessageStart(message_id=run_id))
                events.extend(TextDelta(message_id=run_id, content=text) for text in texts)
            return events
        if kind == "on_tool_start":
            call: list[StreamEvent] = [ToolCallStart(tool_call_id=run_id, name=event.get("name") or "")]
            arguments = LangGraphRunner._tool_arguments(event)
            if arguments:
                call.append(ToolCallArgs(tool_call_id=run_id, delta=arguments))
            call.append(ToolCallEnd(tool_call_id=run_id))
            return call
        if kind == "on_tool_end":
            return [ToolCallResult(tool_call_id=run_id, content=LangGraphRunner._tool_output(event))]
        return []

    @staticmethod
    def _chunk_content(event: dict) -> tuple[list[str], list[str]]:
        """
        Split one `on_chat_model_stream` chunk into (answer text, reasoning text).

        Reads `content_blocks` (not raw `content`) so provider-specific reasoning placement is
        normalised. Reasoning text comes from the block's `reasoning` key, with `summary[].text`
        as fallback for `output_version="v1"`. Empty fragments are dropped.

        :param event: An `on_chat_model_stream` event from `astream_events`.
        :return: Answer fragments and reasoning fragments (either may be empty).
        """
        answer: list[str] = []
        thoughts: list[str] = []
        for block in event["data"]["chunk"].content_blocks:
            kind = block.get("type")
            if kind == "text":
                if block.get("text"):
                    answer.append(block["text"])
            elif kind == "reasoning":
                thought = block.get("reasoning") or LangGraphRunner._summary_text(block)
                if thought:
                    thoughts.append(thought)
        return answer, thoughts

    @staticmethod
    def _summary_text(block: dict) -> str:
        """Flatten a reasoning block's `summary` list into text.

        The shape `content_blocks` leaves alone at `output_version="v1"`: a list of
        `{"type": "summary_text", "text": ...}` parts rather than a single `reasoning` string.

        :param block: One reasoning content block.
        :return: The concatenated summary text, empty when the block carries no usable summary.
        """
        summary = block.get("summary")
        if not isinstance(summary, list):
            return ""
        return "".join(part["text"] for part in summary if isinstance(part, dict) and part.get("text"))

    @staticmethod
    def _tool_arguments(event: dict) -> str:
        """
        Serialise an `on_tool_start` input dict into a JSON arguments fragment.

        LangChain hands over a parsed dict rather than the model's original JSON, so it is
        re-serialised here. On encode failure the call is still bracketed with no arguments —
        safer mid-stream than letting an exception fail the run.

        :param event: An `on_tool_start` event from `astream_events`.
        :return: JSON string for `ToolCallArgs.delta`, or `""` if missing/unencodable.
        """
        data = event.get("data") or {}
        tool_input = data.get("input")
        if tool_input is None:
            return ""
        try:
            return json.dumps(tool_input, default=str)
        except Exception as e:
            _logger.warning(f"LangGraph tool input could not be serialised; the tool call is emitted with no arguments: {e!r}")
            return ""

    @staticmethod
    def _tool_output(event: dict) -> str:
        """
        Read an `on_tool_end` output as text.

        Prefer `ToolMessage.content` when present; otherwise fall back to `str(output)`.

        :param event: An `on_tool_end` event from `astream_events`.
        :return: Text for `ToolCallResult.content`.
        """
        data = event.get("data") or {}
        output = data.get("output")
        content = getattr(output, "content", None)
        if content is not None:
            return content if isinstance(content, str) else str(content)
        return "" if output is None else str(output)


class LangGraphModule(BaseModule):
    """
    LangGraphModule class provides a module for LangGraph Agent SDK-based agents.
    """

    def __init__(self, agents: list[CompiledStateGraph], runner: LangGraphRunner = None):
        """
        Initializes a LangGraphModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().langgraph()
        else:
            self.runner = LangGraphRunner()
        self.load(agents)

    def _wrap(self, agent: CompiledStateGraph, agents: List[CompiledStateGraph]) -> BaseAgent:
        return LangGraphAgent(name=agent.name, runner=self.runner, agent=agent)

    def load(self, agents: list[CompiledStateGraph]) -> "LangGraphModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: LangGraphModule instance.
        """
        super().load(agents)
        return self


class LangGraphToolBuilder(ToolBuilder):
    """
    Tool builder for LangGraph / LangChain.

    Wraps generic tool functions into LangChain StructuredTool instances
    that are compatible with LangGraph agent graphs.
    """

    @classmethod
    def bind(cls, funcs: list[Callable], *, agent_name: str | None = None) -> list[Any]:
        """
        Bind generic tool functions to LangChain StructuredTool instances.
        Also automatically appends global system tools (such as multimodal attachments).

        :param funcs: List of generic tool functions to bind.
        :param agent_name: When known, the agent these tools are bound for, so per-capability
                           `agents` scoping (e.g. `sandbox.agents`, `multimodal.agents`) is
                           honored. Omitted → no scoping filter (all enabled system tools).
        :return: List of LangChain StructuredTool instances.
        :raises TypeError: If any item in funcs is not callable.
        """
        # Inject system tools (e.g., analyze_attachments). Pass agent_name so per-capability
        # `agents` scoping applies when the caller knows the agent; without it (the historical
        # call), scoping still holds at agent wrap time (Agent._attach_system_tools).
        all_funcs = list(funcs)
        for sys_tool in SystemToolFactory.get_all(agent_name):
            if sys_tool.func not in all_funcs:
                all_funcs.append(sys_tool.func)

        tools = []
        for func in all_funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")

            if asyncio.iscoroutinefunction(func):
                tools.append(
                    StructuredTool.from_function(
                        coroutine=func,
                        name=func.__name__,
                        description=func.__doc__ or func.__name__,
                    )
                )
            else:
                tools.append(
                    StructuredTool.from_function(
                        func=func,
                        name=func.__name__,
                        description=func.__doc__ or func.__name__,
                    )
                )
        return tools
