from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, AsyncIterator, Callable, Iterator, List, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ...core import Agent as BaseAgent
from ...core import Module as BaseModule
from ...core import PostHook, PreHook
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.event import (
    MessageEnd,
    MessageStart,
    StreamEvent,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from ...core.model import AgentReply, AgentReplyAny, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText
from ...core.tool import SystemToolFactory
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "langgraph"
_logger = logging.getLogger(__name__)


class CheckPointer(BaseCheckpointSaver):
    """
    A pickle-serializable checkpointer implementation for LangGraph.
    This stores checkpoint data in a simple dictionary structure that can be pickled
    """

    def __init__(self):
        super().__init__()
        self._storage = {}
        self._writes = {}

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        if not thread_id:
            return None

        thread_data = self._storage.get(thread_id, {})
        checkpoint_data = thread_data.get(checkpoint_ns)

        if checkpoint_data is None:
            return None

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint_data["checkpoint"],
            metadata=checkpoint_data.get("metadata", {}),
            parent_config=checkpoint_data.get("parent_config"),
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
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        if not thread_id:
            return

        if thread_id not in self._writes:
            self._writes[thread_id] = {}

        if checkpoint_ns not in self._writes[thread_id]:
            self._writes[thread_id][checkpoint_ns] = []

        self._writes[thread_id][checkpoint_ns].append({"task_id": task_id, "task_path": task_path, "writes": writes})

    def delete_thread(self, thread_id: str) -> None:
        if thread_id in self._storage:
            del self._storage[thread_id]
        if thread_id in self._writes:
            del self._writes[thread_id]

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

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the LangGraph agent with provided multi modal inputs.
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

            config, messages = self._prepare_session_and_messages(agent, session, prompt)

            # Spread the context's top-level keys into the input state so they map onto the graph's state
            # channels. `messages` is written last so a caller key cannot replace it.
            incoming = self._load_framework_context(session)
            input_state: dict[str, Any] = {}
            if incoming:
                input_state.update(incoming)
            input_state["messages"] = messages

            result = await agent.agent.ainvoke(
                input=input_state,
                config=config,
            )

            # Only keys the graph declares as state channels come back on `result`; the rest keep their value.
            if incoming is not None:
                produced = {k: result[k] for k in incoming if k in result}
                self._store_framework_context(session, incoming, produced)

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

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the LangGraph agent response as Agent Kernel stream events.

        Every correlation id is `event["run_id"]`, which LangChain assigns per runnable invocation
        and declares as a required field of its `StreamEvent` (`langchain_core/runnables/schema.py`).
        One chat-model call and one tool call each get their own, so a start pairs with its end
        without the adapter remembering anything — a nested model call inside a tool gets a distinct
        id rather than colliding with the outer one.

        Tool arguments arrive whole in `on_tool_start`, so the call is opened, its arguments emitted
        as one fragment and the call closed together. LangChain exposes no per-token argument
        stream, so there is nothing finer to forward.

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

            config, messages = self._prepare_session_and_messages(agent, session, prompt)

            incoming = self._load_framework_context(session)
            input_state: dict[str, Any] = {}
            if incoming:
                input_state.update(incoming)
            input_state["messages"] = messages

            async for event in agent.agent.astream_events(
                input=input_state,
                config=config,
                version="v2",
            ):
                for stream_event in self._map_event(event):
                    yield stream_event

            # astream_events yields events, not a final state, so read the state back once the stream drains
            # normally. A disconnect or mid-stream error unwinds first, leaving the stored context intact.
            if incoming is not None:
                try:
                    state = await agent.agent.aget_state(config)
                    produced = {k: state.values[k] for k in incoming if k in state.values}
                    self._store_framework_context(session, incoming, produced)
                except Exception as e:
                    self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()

    @staticmethod
    def _map_event(event: dict) -> list[StreamEvent]:
        """Translate one LangChain `astream_events` event into AK events.

        Every other event name — `on_chain_*`, `on_prompt_*`, retriever and parser events — maps to
        nothing. Graph nodes would be the natural source for `StepStart`/`StepEnd`, but `on_chain_*`
        fires for every runnable in the graph, not only the nodes a user would recognise as steps,
        so naming them is a decision on its own rather than part of this mapping.

        :param event: One event from `astream_events(version="v2")`.
        :return: The AK events this event produces, empty when it maps to nothing.
        """
        kind = event["event"]
        run_id = event["run_id"]

        if kind == "on_chat_model_start":
            return [MessageStart(message_id=run_id)]
        if kind == "on_chat_model_end":
            return [MessageEnd(message_id=run_id)]
        if kind == "on_chat_model_stream":
            return [TextDelta(message_id=run_id, content=text) for text in LangGraphRunner._chunk_text(event)]
        if kind == "on_tool_start":
            events: list[StreamEvent] = [ToolCallStart(tool_call_id=run_id, name=event.get("name") or "")]
            arguments = LangGraphRunner._tool_arguments(event)
            if arguments:
                events.append(ToolCallArgs(tool_call_id=run_id, delta=arguments))
            events.append(ToolCallEnd(tool_call_id=run_id))
            return events
        if kind == "on_tool_end":
            return [ToolCallResult(tool_call_id=run_id, content=LangGraphRunner._tool_output(event))]
        return []

    @staticmethod
    def _chunk_text(event: dict) -> list[str]:
        """Pull the prose out of an `on_chat_model_stream` chunk.

        A chunk's `content` is a plain string for most providers and a list of content blocks for
        those that interleave text with other block types (Anthropic's tool-use blocks, for one), so
        both shapes are read and blocks without text are skipped. Empty fragments are dropped rather
        than forwarded as empty events.
        """
        content = event["data"]["chunk"].content
        if isinstance(content, str):
            return [content] if content else []
        if isinstance(content, list):
            return [item["text"] for item in content if isinstance(item, dict) and item.get("text")]
        return []

    @staticmethod
    def _tool_arguments(event: dict) -> str:
        """Serialise an `on_tool_start` input dict into a JSON arguments fragment.

        `ToolCallArgs.delta` is documented as a raw fragment as frameworks emit it, and LangChain
        hands over a parsed dict rather than the model's original JSON text — so it is re-serialised
        here. A value the encoder cannot handle yields no arguments event at all, which is better
        than a fragment a client cannot parse.

        The `except` is deliberately broad. `default=str` hands any unencodable value to its own
        `__str__`, which is arbitrary user code and can raise anything at all — and this runs
        mid-stream, where an escaping exception turns an in-flight response into a failed run. The
        arguments are the most expendable part of a tool call: dropping them still leaves the call
        bracketed and its result correlated.
        """
        data = event.get("data") or {}
        tool_input = data.get("input")
        if tool_input is None:
            return ""
        try:
            return json.dumps(tool_input, default=str)
        except Exception as e:
            _logger.debug(f"LangGraph tool input could not be serialised; emitting no arguments: {e!r}")
            return ""

    @staticmethod
    def _tool_output(event: dict) -> str:
        """Read an `on_tool_end` output as text.

        LangChain wraps a tool's return value in a `ToolMessage` on most paths but hands the bare
        value back on others, so the message's `content` is preferred and the value itself is the
        fallback.
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

    def pre_hook(self, agent: CompiledStateGraph, hooks: list[PreHook]) -> "LangGraphModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: LangGraphModule instance.
        """
        super().get_agent(agent.name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: CompiledStateGraph, hooks: list[PostHook]) -> "LangGraphModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: LangGraphModule instance.
        """
        super().get_agent(agent.name).post_hooks.extend(hooks)
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
