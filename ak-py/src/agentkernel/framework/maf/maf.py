from __future__ import annotations

import base64
import copy
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, ClassVar, List, Mapping
from uuid import uuid4

from agent_framework import AgentSession, Content
from agent_framework import tool as maf_tool

from ...core import Agent as BaseAgent
from ...core import Module
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    StreamEvent,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from ...core.model import (
    AgentReply,
    AgentReplyAny,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "maf"

_log = logging.getLogger("ak.maf.runner")


class MAFSession:
    """
    MAFSession class provides a session for MAF-based agents.
    """

    def __init__(self):
        """
        Initializes a MAFSession instance.
        """
        self._state: dict | None = None

    def get_state(self) -> dict | None:
        """
        Retrieve the underlying session state dict.
        :return: The session state dict, or None.
        """
        return self._state

    def set_state(self, state: dict | None) -> None:
        """
        Set the underlying session state dict.
        :param state: The session state dict.
        """
        self._state = state


class MAFRunner(BaseRunner):
    """
    MAFRunner class provides a runner for Microsoft Agent Framework based agents.
    """

    def __init__(self):
        """
        Initializes a MAFRunner instance.
        """
        super().__init__(FRAMEWORK)

    @classmethod
    def _session(cls, session: Session) -> MAFSession:
        """
        Retrieves the MAFSession from the AgentKernel session, initializing it if not present.
        """
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, MAFSession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[Any]]:
        """
        Process requests and extract prompt text and MAF Content items.
        :param requests: The requests to process.
        :return: Tuple containing the prompt string and a list of MAF inputs (str or Content).
        """
        prompt = ""
        inputs = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                text = req.prompt
                prompt = prompt + "\n" + text if prompt else text
                inputs.append(text)

            elif isinstance(req, AgentRequestImage):
                if not req.image_data:
                    raise ValueError("no image input provided")
                prompt += f"\n[Image attached: {req.name or 'image'}]"
                if Content is not None:
                    if req.image_data.startswith(("http://", "https://", "s3://")):
                        inputs.append(Content.from_uri(uri=req.image_data))
                        continue
                    
                    base64_data = req.image_data
                    if base64_data.startswith("data:"):
                        mime_type = base64_data.split(";")[0][5:]
                        raw_data = base64.b64decode(base64_data.split(",")[-1])
                    else:
                        mime_type = getattr(req, "mime_type", "image/png")
                        raw_data = base64.b64decode(base64_data)
                    inputs.append(Content.from_data(data=raw_data, media_type=mime_type))

            elif isinstance(req, AgentRequestFile):
                if not req.file_data:
                    raise ValueError("no file input provided")
                prompt += f"\n[File attached: {req.name or 'file'}]"
                if Content is not None:
                    if req.file_data.startswith(("http://", "https://", "s3://")):
                        inputs.append(Content.from_uri(uri=req.file_data))
                        continue
                    
                    base64_data = req.file_data
                    if base64_data.startswith("data:"):
                        mime_type = base64_data.split(";")[0][5:]
                        raw_data = base64.b64decode(base64_data.split(",")[-1])
                    else:
                        mime_type = getattr(req, "mime_type", None) or "application/octet-stream"
                        raw_data = base64.b64decode(base64_data)
                    inputs.append(Content.from_data(data=raw_data, media_type=mime_type))

        return prompt, inputs

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent with the provided inputs.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        context: ToolContext | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, inputs = self._process_requests(requests)

            if not prompt and not inputs:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            options = await agent.resolve_run_options(session, requests)

            incoming = self._load_framework_context(session)
            maf_session = self._session(session)
            
            # Rehydrate framework memory from AgentKernel session
            if incoming is not None:
                maf_session.set_state(copy.deepcopy(incoming))

            produced = maf_session.get_state()
            kwargs = self._native_kwargs(options)

            if AgentSession and session and "session" not in kwargs:
                if produced:
                    kwargs["session"] = AgentSession.from_dict(produced)
                else:
                    kwargs["session"] = AgentSession(session_id=session.id)

            # Fallback to string prompt if inputs list is empty but prompt exists
            payload = inputs if inputs else prompt
            result = await agent.agent.run(payload, **kwargs)

            if AgentSession and "session" in kwargs:
                produced = kwargs["session"].to_dict()
                maf_session.set_state(produced)
            self._store_framework_context(session, incoming, produced)

            output = getattr(result, "text", None)
            if output is None:
                output = str(result)

            structured = AgentReplyAny.from_output(output, prompt)
            if structured is not None:
                return structured

            return AgentReplyText(response=output, prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the MAF agent response as Agent Kernel stream events.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, inputs = self._process_requests(requests)

            if not prompt and not inputs:
                return

            options = await agent.resolve_run_options(session, requests)

            incoming = self._load_framework_context(session)
            maf_session = self._session(session)
            
            # Rehydrate framework memory from AgentKernel session
            if incoming is not None:
                maf_session.set_state(copy.deepcopy(incoming))

            produced = maf_session.get_state()
            kwargs = self._native_kwargs(options)

            if AgentSession and session and "session" not in kwargs:
                if produced:
                    kwargs["session"] = AgentSession.from_dict(produced)
                else:
                    kwargs["session"] = AgentSession(session_id=session.id)

            # Fallback to string prompt if inputs list is empty but prompt exists
            payload = inputs if inputs else prompt
            stream_result = await agent.agent.run(payload, stream=True, **kwargs)

            message_id = uuid4().hex
            yield MessageStart(message_id=message_id)

            reasoning_started = False

            # Using async iterator over the ResponseStream
            if hasattr(stream_result, "__aiter__"):
                async for update in stream_result:
                    reasoning = getattr(update, "reasoning", None)
                    if reasoning:
                        if not reasoning_started:
                            yield ReasoningStart(message_id=message_id)
                            reasoning_started = True
                        yield ReasoningDelta(message_id=message_id, content=reasoning)

                    text = getattr(update, "text", None)
                    if text:
                        yield TextDelta(message_id=message_id, content=text)

                    tool_calls = getattr(update, "tool_calls", [])
                    for tc in tool_calls:
                        call_id = getattr(tc, "id", uuid4().hex)
                        yield ToolCallStart(tool_call_id=call_id, name=getattr(tc, "name", ""))
                        args = getattr(tc, "arguments", "")
                        if args:
                            yield ToolCallArgs(tool_call_id=call_id, delta=args if isinstance(args, str) else json.dumps(args))
                        yield ToolCallEnd(tool_call_id=call_id)

                    tool_results = getattr(update, "tool_results", [])
                    for tr in tool_results:
                        call_id = getattr(tr, "id", uuid4().hex)
                        content = getattr(tr, "result", "")
                        yield ToolCallResult(tool_call_id=call_id, content=content if isinstance(content, str) else json.dumps(content))
            else:
                # If stream_result is not async iterable (e.g., fallback for older versions), handle appropriately
                _log.warning("MAF agent.run(stream=True) did not return an async iterable.")
                yield TextDelta(message_id=message_id, content=str(stream_result))

            if reasoning_started:
                yield ReasoningEnd(message_id=message_id)
            yield MessageEnd(message_id=message_id)

            try:
            
                if AgentSession and "session" in kwargs:
                    produced = kwargs["session"].to_dict()
                    maf_session.set_state(produced)
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()

    @property
    def supports_streaming(self) -> bool:
        """Declared True as MAF supports streaming."""
        return True


class MAFAgent(BaseAgent):
    """
    MAFAgent class provides an agent wrapping for Microsoft Agent Framework-based agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "user_prompt": "built from the AgentRequest list by the runner",
        "stream": "managed by the runner based on the execution mode",
        "session": "managed by the runner based on the AK session",
    }

    def __init__(self, name: str, runner: MAFRunner, agent: Any):
        """
        Initializes a MAFAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The MAF agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Any:
        """
        Returns the MAF agent instance.
        """
        return self._agent

    def get_description(self) -> str:
        """
        Returns the description of the agent.
        """
        return getattr(self.agent, "system_message", "") or getattr(self.agent, "instructions", "") or ""

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends additional instructions to the MAF agent's system prompt.
        """
        if prompt:
            current = getattr(self.agent, "instructions", "")
            self.agent.instructions = f"{current}\n{prompt}" if current else prompt

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable, wraps it with MAFToolBuilder, and registers it.
        :param tool: Raw Python callable to attach.
        """
        wrapped = MAFToolBuilder.bind([tool])
        tools = getattr(self.agent, "tools", [])
        if tools is None:
            tools = []
        for w in wrapped:
            w_name = getattr(w, "name", getattr(w, "__name__", ""))
            if not any(getattr(t, "name", getattr(t, "__name__", "")) == w_name for t in tools):
                tools.append(w)
        self.agent.tools = tools

    def get_a2a_card(self) -> Any:
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []
        tools = getattr(self.agent, "tools", []) or []
        for t in tools:
            name = getattr(t, "__name__", "tool")
            desc = getattr(t, "__doc__", "")
            skills.append(AgentSkill(id=name, name=name, description=desc, tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class MAFModule(Module):
    """
    MAFModule class provides a module for Microsoft Agent Framework-based agents.
    """

    def __init__(self, agents: list[Any], runner: MAFRunner = None):
        """
        Initializes a MAFModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().maf()
        else:
            self.runner = MAFRunner()
        self.load(agents)

    def _wrap(self, agent: Any, agents: List[Any]) -> BaseAgent:
        """
        Wraps the provided agent in a MAFAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: MAFAgent instance.
        :raises ValueError: If the agent has no explicit name.
        """
        name = getattr(agent, "name", None)
        if name is None:
            raise ValueError("MAF agents passed to MAFModule must have an explicit name= — " "AK registers agents by name.")
        return MAFAgent(name, self.runner, agent)

    def load(self, agents: list[Any]) -> MAFModule:
        """
        Loads the specified agents into the module.
        :param agents: List of agents to load.
        :return: MAFModule instance.
        """
        super().load(agents)
        return self


class MAFToolBuilder(ToolBuilder):
    """
    Tool builder for Microsoft Agent Framework.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to MAF ``@tool`` definitions.
        :param funcs: List of generic tool functions to bind.
        :return: List of MAF tool definitions.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            try:
                tools.append(maf_tool(func))
            except ImportError:
                tools.append(func)
        return tools
