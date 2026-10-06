import base64
import copy
import json
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any, ClassVar
from uuid import uuid4

from agent_framework import Agent, AgentSession, Content
from agent_framework import tool as maf_tool

from ...core import Agent as BaseAgent
from ...core import Module, Runner, Runtime, Session, ToolBuilder, ToolContext
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


class MAFSession:
    """
    MAFSession class provides a simple session wrapper for MAF agents.
    """

    def __init__(self):
        self._state = None

    def get_state(self):
        return self._state

    def set_state(self, state):
        self._state = state


class MAFRunner(Runner):
    """
    MAFRunner class provides a runner for Microsoft Agent Framework-based agents.
    """

    def __init__(self):
        super().__init__(FRAMEWORK)

    def _session(self, session: Session) -> MAFSession:
        """
        Retrieves the MAFSession from the AgentKernel session, initializing it if not present.
        """
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, MAFSession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[Any]]:
        """
        Process requests and extract prompt text and MAF Content items.
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
                        mime_type = getattr(req, "mime_type", None)
                        if mime_type:
                            inputs.append(Content.from_uri(uri=req.image_data, media_type=mime_type))
                        else:
                            inputs.append(Content.from_uri(uri=req.image_data))
                        continue

                    base64_data = req.image_data
                    if base64_data.startswith("data:"):
                        mime_type = base64_data.split(";")[0][5:]
                        raw_data = base64.b64decode(base64_data.split(",")[-1])
                    else:
                        mime_type = getattr(req, "mime_type", None)
                        if not mime_type:
                            raise ValueError("MIME type is required for raw image data but was not provided.")
                        raw_data = base64.b64decode(base64_data)
                    inputs.append(Content.from_data(data=raw_data, media_type=mime_type))

            elif isinstance(req, AgentRequestFile):
                if not req.file_data:
                    raise ValueError("no file input provided")
                prompt += f"\n[File attached: {req.name or 'file'}]"
                if Content is not None:
                    if req.file_data.startswith(("http://", "https://", "s3://")):
                        mime_type = getattr(req, "mime_type", None)
                        if mime_type:
                            inputs.append(Content.from_uri(uri=req.file_data, media_type=mime_type))
                        else:
                            inputs.append(Content.from_uri(uri=req.file_data))
                        continue

                    base64_data = req.file_data
                    if base64_data.startswith("data:"):
                        mime_type = base64_data.split(";")[0][5:]
                        raw_data = base64.b64decode(base64_data.split(",")[-1])
                    else:
                        mime_type = getattr(req, "mime_type", None)
                        if not mime_type:
                            raise ValueError("MIME type is required for raw file data but was not provided.")
                        raw_data = base64.b64decode(base64_data)
                    inputs.append(Content.from_data(data=raw_data, media_type=mime_type))

        return prompt, inputs

    def _prepare_session(self, session: Session, options: dict) -> tuple[dict, Any, dict | None]:
        maf_session = self._session(session)
        produced = maf_session.get_state()
        native_session = None

        if AgentSession and session:
            if produced:
                native_session = AgentSession.from_dict(produced)
            else:
                native_session = AgentSession(session_id=session.id)
            kwargs = self._native_kwargs(options, session=native_session)
        else:
            kwargs = self._native_kwargs(options)
            native_session = kwargs.get("session")

        incoming = self._load_framework_context(session)
        if native_session is not None:
            if incoming is not None:
                native_session.state["ak_context"] = copy.deepcopy(incoming)
            elif "ak_context" in native_session.state:
                del native_session.state["ak_context"]

        return kwargs, native_session, incoming

    def _finalize_session(self, session: Session, maf_session: MAFSession, native_session: Any, incoming: dict | None):
        if native_session is not None:
            produced_context = native_session.state.get("ak_context")
            self._store_framework_context(session, incoming, produced_context)
            maf_session.set_state(native_session.to_dict())

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        context: ToolContext | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, inputs = self._process_requests(requests)

            if not prompt and not inputs:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            options = await agent.resolve_run_options(session, requests)

            kwargs, native_session, incoming = self._prepare_session(session, options)

            payload = inputs if inputs else prompt
            result = await agent.agent.run(payload, **kwargs)

            # Only write back after successful run
            self._finalize_session(session, self._session(session), native_session, incoming)

            value = getattr(result, "value", None)
            if value is not None:
                structured = AgentReplyAny.from_output(value, prompt)
                if structured is not None:
                    return structured

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
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, inputs = self._process_requests(requests)

            if not prompt and not inputs:
                return

            options = await agent.resolve_run_options(session, requests)
            kwargs, native_session, incoming = self._prepare_session(session, options)

            payload = inputs if inputs else prompt
            stream_result = await agent.agent.run(payload, stream=True, **kwargs)

            fallback_id = uuid4().hex
            current_text_id = None
            current_reasoning_id = None
            open_calls = set()

            async for update in stream_result:
                native_id = getattr(update, "message_id", None)
                contents = getattr(update, "contents", [])

                for item in contents:
                    item_type = getattr(item, "type", "")

                    if item_type == "text_reasoning":
                        text = getattr(item, "text", "")
                        if text:
                            effective_id = native_id or current_reasoning_id or fallback_id
                            if current_reasoning_id != effective_id:
                                if current_reasoning_id is not None:
                                    yield ReasoningEnd(message_id=current_reasoning_id)
                                yield ReasoningStart(message_id=effective_id)
                                current_reasoning_id = effective_id
                            yield ReasoningDelta(message_id=effective_id, content=text)

                    elif item_type == "text":
                        text = getattr(item, "text", "")
                        if text:
                            effective_id = native_id or current_text_id or fallback_id
                            if current_text_id != effective_id:
                                if current_text_id is not None:
                                    yield MessageEnd(message_id=current_text_id)
                                yield MessageStart(message_id=effective_id)
                                current_text_id = effective_id
                            yield TextDelta(message_id=effective_id, content=text)

                    elif item_type == "function_call":
                        call_id = getattr(item, "call_id", uuid4().hex)
                        if call_id not in open_calls:
                            yield ToolCallStart(tool_call_id=call_id, name=getattr(item, "name", ""))
                            open_calls.add(call_id)
                        args = getattr(item, "arguments", "")
                        if args:
                            yield ToolCallArgs(tool_call_id=call_id, delta=args if isinstance(args, str) else json.dumps(args))

                    elif item_type == "function_result":
                        call_id = getattr(item, "call_id", uuid4().hex)
                        if call_id in open_calls:
                            yield ToolCallEnd(tool_call_id=call_id)
                            open_calls.remove(call_id)
                        content = getattr(item, "result", "")
                        yield ToolCallResult(tool_call_id=call_id, content=content if isinstance(content, str) else json.dumps(content))

            for call_id in list(open_calls):
                yield ToolCallEnd(tool_call_id=call_id)

            if current_reasoning_id is not None:
                yield ReasoningEnd(message_id=current_reasoning_id)
            if current_text_id is not None:
                yield MessageEnd(message_id=current_text_id)

            # Only write back on successful completion
            try:
                self._finalize_session(session, self._session(session), native_session, incoming)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()


class MAFAgent(BaseAgent):
    """
    MAFAgent class provides an agent wrapping for Microsoft Agent Framework-based agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "messages": "built from the AgentRequest list by the runner",
        "stream": "managed by the runner based on the execution mode",
        "session": "managed by the runner based on the AK session",
    }

    def __init__(self, name: str, runner: MAFRunner, agent: Agent):
        super().__init__(name, runner)
        self._agent = agent
        if getattr(self._agent, "default_options", None) is None:
            self._agent.default_options = {}
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Agent:
        return self._agent

    def get_description(self) -> str:
        return getattr(self.agent, "description", None) or self.agent.default_options.get("instructions", "") or ""

    def override_system_prompt(self, prompt: str) -> None:
        if prompt:
            current = self.agent.default_options.get("instructions", "")
            self.agent.default_options["instructions"] = f"{current}\n{prompt}" if current else prompt

    def attach_tool(self, tool: Any) -> None:
        wrapped = MAFToolBuilder.bind([tool])
        tools = self.agent.default_options.get("tools")
        if tools is None:
            tools = []
            self.agent.default_options["tools"] = tools
        for w in wrapped:
            w_name = getattr(w, "name", "")
            if not any(getattr(t, "name", "") == w_name for t in tools):
                tools.append(w)

    def get_a2a_card(self) -> Any:
        from a2a.types import AgentSkill

        skills = []
        tools = self.agent.default_options.get("tools", []) or []
        for t in tools:
            name = getattr(t, "name", "tool")
            desc = getattr(t, "description", "")
            skills.append(AgentSkill(id=name, name=name, description=desc, tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class MAFModule(Module):
    """
    MAFModule class provides a module for Microsoft Agent Framework-based agents.
    """

    def __init__(self, agents: list[Agent | BaseAgent], runner: MAFRunner = None):
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().maf()
        else:
            self.runner = MAFRunner()
        self.load(agents)

    def _wrap(self, agent: Agent | BaseAgent, agents: list[Agent | BaseAgent]) -> BaseAgent:
        if isinstance(agent, BaseAgent):
            return agent
        if getattr(agent, "name", None) is None:
            raise ValueError("MAF agents passed to MAFModule must have an explicit name= — " "AK registers agents by name immediately.")
        return MAFAgent(agent.name, self.runner, agent)

    def load(self, agents: list[Agent | BaseAgent]) -> "MAFModule":
        super().load(agents)
        return self

    def get_runner(self) -> Runner:
        return self.runner


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
            tools.append(maf_tool(func))
        return tools
