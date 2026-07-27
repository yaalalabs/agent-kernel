from __future__ import annotations

import asyncio
import base64
import functools
import inspect
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any, Callable, List

from google.adk.agents import BaseAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, State
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
from pydantic import ValidationError

from agentkernel.core.model import (
    AgentReply,
    AgentReplyAny,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)

from ...core import Agent as AKBaseAgent
from ...core import Module, PostHook, PreHook
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder
from ...core import ToolContext as AKToolContext
from ...core.config import AKConfig
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "adk"


class GoogleADKSession:
    """
    Manages Google ADK user sessions and underlying session service.
    """

    def __init__(self):
        """
        Initialize the session store and logging for Google ADK sessions.
        """
        self._session_service = InMemorySessionService()
        self._log = logging.getLogger("ak.adk.session")
        self._session = None

    @property
    def session_service(self) -> BaseSessionService:
        """
        Return the in-memory session service instance.
        """
        return self._session_service

    async def create_session(self, app_name: str, user_id: str, session_id: str) -> Any:
        if self._session is None:
            self._session = await self._session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
        return self._session

    async def update_session_state(self, invocation_id: str, author: str, state: dict) -> None:
        if self._session:
            event = Event(
                invocation_id=invocation_id,
                author=author,
                actions=EventActions(state_delta=state),
                timestamp=time.time(),
            )
            await self._session_service.append_event(self._session, event)

    async def get_state(self) -> dict:
        """
        Returns the current session-scoped ADK state with non-caller keys stripped.

        ADK's native state lives in an InMemorySessionService and is not part of the pickled AK
        session, so the runner reads it back here to give the framework_context cross-turn
        durability. Two groups of keys are removed because they are not caller state:

        - ``ak_tool_context`` — AK-internal, seeded fresh every turn, so the caller's context never
          accumulates a stale internal id.
        - ``app:`` / ``user:`` / ``temp:`` prefixed keys — the first two are app- and user-scoped
          values that ``InMemorySessionService`` merges into the returned session on read
          (``_merge_state``), the third is invocation-scoped. None belong in a per-session caller
          context that gets pickled into the AK session.

        Note that the returned state is accumulate-only: ADK keeps every key written to this session
        for its lifetime, so a key the caller drops from framework_context reappears here on the next
        turn, and values an agent writes itself (e.g. ``LlmAgent(output_key=...)``) are
        indistinguishable from tool writes and round-trip too.
        :return: The accumulated session-scoped ADK state, or an empty dict when no session exists.
        """
        if self._session is None:
            return {}
        refreshed = await self._session_service.get_session(
            app_name=self._session.app_name, user_id=self._session.user_id, session_id=self._session.id
        )
        state = dict(getattr(refreshed, "state", {}) or {})
        state.pop("ak_tool_context", None)
        return {k: v for k, v in state.items() if not k.startswith((State.APP_PREFIX, State.USER_PREFIX, State.TEMP_PREFIX))}


class GoogleADKRunner(BaseRunner):
    def __init__(self):
        """
        Initializes a GoogleADKRunner instance.
        """
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.runner")

    @staticmethod
    def _session(session: Session) -> GoogleADKSession | None:
        """
        Returns the Google ADK session associated with the provided session.
        :param session: The session to retrieve the Google ADK session for.
        :return: GoogleADKSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, GoogleADKSession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[types.Part]]:
        """
        Process requests and extract prompt text and ADK parts.
        :param requests: The requests to process.
        :return: Tuple of (prompt, parts).
        """
        prompt = ""
        parts = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                text = req.prompt
                prompt = prompt + "\n" + text if prompt else text
                parts.append(types.Part(text=text))

            if isinstance(req, (AgentRequestImage, AgentRequestFile)):
                base64_data = ""
                if isinstance(req, AgentRequestImage):
                    if not req.image_data:
                        raise ValueError("no image input provided")
                    base64_data = req.image_data

                elif isinstance(req, AgentRequestFile):
                    if not req.file_data:
                        raise ValueError("no file input provided")
                    base64_data = req.file_data

                if base64_data.startswith(("http://", "https://", "s3://")):
                    parts.append(types.Part(file_data=types.FileData(file_uri=base64_data)))
                    continue

                if base64_data.startswith(("data:")):
                    mime_type = base64_data.split(";")[0][5:]
                else:
                    if not req.mime_type:
                        raise ValueError("mime_type is missing for image input")
                    mime_type = req.mime_type

                raw_data = base64.b64decode(base64_data.split(",")[-1]) if base64_data.startswith("data:") else base64.b64decode(base64_data)
                parts.append(types.Part(inline_data=types.Blob(mime_type=mime_type, data=raw_data)))

        return prompt, parts

    async def _setup_session_context(
        self, agent: Any, session: Session, requests: list[AgentRequest], injected: dict | None = None
    ) -> tuple[str, Runner, AKToolContext, GoogleADKSession]:
        """
        Setup ADK session and tool context.
        :param agent: The ADK agent.
        :param session: The AgentKernel session.
        :param requests: The requests.
        :param injected: The per-run framework context to seed into the ADK session state alongside
                         the AK-internal ``ak_tool_context`` id, or None to seed nothing extra.
        :return: Tuple of (user_id, runner, tool_context, adk_session). The caller is responsible for
                 entering/exiting the returned tool_context around the runner's actual execution, since
                 tools invoked by the agent look up this context by id from the cache while the agent is
                 running; the returned adk_session lets the caller read state back without re-fetching.
        """
        app_name = "AgentKernel"
        user_id = "AgentKernel"
        adk_session = self._session(session)

        ctx: AKToolContext = AKToolContext(Runtime.current(), agent, session, requests)
        await adk_session.create_session(app_name=app_name, user_id=user_id, session_id=session.id)
        # The AK-internal key is assigned LAST so a caller key named `ak_tool_context` can never
        # replace the id tools resolve their context by (AKToolContext.fetch would raise KeyError for
        # every tool call in the run). Same "internal key wins" ordering as LangGraph's `messages`.
        state = dict(injected or {})
        state["ak_tool_context"] = ctx.id
        await adk_session.update_session_state(ctx.id, agent.name, state)

        runner = Runner(agent=agent.agent, app_name=app_name, session_service=adk_session.session_service)
        return user_id, runner, ctx, adk_session

    @staticmethod
    async def get_response(runner: Runner, user_id: str, session_id: str, parts: list[types.Part]) -> str:
        """
        Send a message to the agent and return the final response text asynchronously.
        :param runner: The Google ADK Runner to use for the agent.
        :param user_id: The user ID to use for the agent.
        :param session_id: The session ID to use for the agent.
        :param parts: The message parts to send to the agent.
        :return: The final response text from the agent.
        """
        new_message = types.Content(role="user", parts=parts)
        response_text = ""

        if hasattr(runner, "run_async"):
            # Drain the stream instead of breaking on the first final response. Stopping early makes
            # ADK cancel its still-running root agent task ("Root node <name> was cancelled."), and the
            # last final response is the right one when sub-agents are involved. Matches `stream()`.
            async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=new_message):
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(text_parts) if text_parts else ""
        else:
            for event in runner.run(user_id=user_id, session_id=session_id, new_message=new_message):
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(text_parts) if text_parts else ""
                    break
        return response_text

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        try:
            prompt, parts = self._process_requests(requests)

            if not parts:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            incoming = self._load_framework_context(session)
            user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming)
            with ctx:
                reply = await self.get_response(runner=runner, session_id=session.id, parts=parts, user_id=user_id)

            # Read ADK's accumulated state back (ak_tool_context already stripped by get_state) and
            # write it back in FULL — keys a tool ADDED during the run round-trip here (the deliberate
            # divergence from smolagents). Inside the try, after the run, so a framework error skips
            # write-back and leaves the previously stored context intact.
            if incoming is not None:
                produced = await adk_session.get_state()
                self._store_framework_context(session, incoming, produced)

            output_schema = getattr(agent.agent, "output_schema", None)
            if output_schema is not None:
                try:
                    parsed = output_schema.model_validate_json(reply)
                    return AgentReplyAny(content=parsed.model_dump(mode="json"), prompt=prompt)
                except ValidationError:
                    self._log.warning(f"Agent '{agent.name}' has output_schema set but reply is not valid JSON for it; returning text")
            return AgentReplyText(response=reply, prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[str, None]:
        """
        Streams the Google ADK agent response token by token using SSE mode.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding string token deltas.
        """
        prompt, parts = self._process_requests(requests)

        if not parts:
            return

        incoming = self._load_framework_context(session)
        user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming)
        new_message = types.Content(role="user", parts=parts)
        run_config = RunConfig(streaming_mode=StreamingMode.SSE)

        if hasattr(runner, "run_async"):
            with ctx:
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session.id,
                    new_message=new_message,
                    run_config=run_config,
                ):
                    if not getattr(event, "partial", False):
                        continue
                    if not event.content or not event.content.parts:
                        continue
                    chunk = "".join(getattr(part, "text", "") or "" for part in event.content.parts)
                    if chunk:
                        yield chunk

                # Write back only after the event stream drains normally. A disconnect
                # (GeneratorExit at a yield) or a mid-stream error unwinds before this line, so the
                # stored context is left intact — never moved into a finally. A failed state read
                # or write-back is logged rather than raised, so the response already streamed to
                # the client does not turn into a transport error that also skips Runtime.stream's
                # session store().
                if incoming is not None:
                    try:
                        produced = await adk_session.get_state()
                        self._store_framework_context(session, incoming, produced)
                    except Exception as e:
                        self._log_framework_context_stream_failure(session, e)


class GoogleADKAgent(AKBaseAgent):
    """
    GoogleADKAgent class provides an agent wrapping for Google ADK Agent SDK based agents.
    """

    def __init__(self, name: str, runner: GoogleADKRunner, agent: BaseAgent):
        """
        Initializes a GoogleADKAgent instance.
        :param name: Name of the agent.
        :param runner: BaseRunner associated with the agent.
        :param agent: The Google ADK agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> BaseAgent:
        """
        Returns the GoogleADK agent instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.description

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends the given prompt text to the ADK agent's description.
        Called by the base Agent._setup_system_prompt() at init when multimodal is enabled.
        """
        if hasattr(self._agent, "description") and self._agent.description and prompt not in self._agent.description:
            self._agent.description += "\n" + prompt

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable and wraps it with GoogleADKToolBuilder before attaching,
        so the base Agent._attach_system_tools() can pass raw functions generically.
        :param tool: Raw Python callable or already-wrapped ADK FunctionTool.
        """
        # Delegate to the tool builder to handle binding
        wrapped = GoogleADKToolBuilder.bind([tool])
        for w in wrapped:
            if not hasattr(self._agent, "tools") or self._agent.tools is None:
                self._agent.tools = []
            if w not in self._agent.tools:
                self._agent.tools.append(w)

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        # TODO Add A2A card support
        pass


class GoogleADKModule(Module):
    """
    GoogleADKModule class provides a module for Google ADK-based agents.
    """

    def __init__(self, agents: list[BaseAgent], runner: GoogleADKRunner = None):
        """
        Initializes a Google ADK Module instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().adk()
        else:
            self.runner = GoogleADKRunner()
        self.load(agents)

    def _wrap(self, agent: BaseAgent, agents: List[BaseAgent]) -> AKBaseAgent:
        """
        Wraps the provided agent in a GoogleADKAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: GoogleADKAgent instance.
        """
        return GoogleADKAgent(agent.name, self.runner, agent)

    def load(self, agents: list[BaseAgent]) -> "GoogleADKModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: GoogleADKModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: BaseAgent, hooks: list[PreHook]) -> "GoogleADKModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: GoogleADKModule instance.
        """
        super().get_agent(agent.name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: BaseAgent, hooks: list[PostHook]) -> "GoogleADKModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: GoogleADKModule instance.
        """
        super().get_agent(agent.name).post_hooks.extend(hooks)
        return self


class GoogleADKToolBuilder(ToolBuilder):
    """
    Tool builder for Google ADK.

    Wraps generic tool functions into ADK-compatible FunctionTool instances.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to ADK FunctionTool instances.

        :param funcs: List of generic tool functions to bind.
        :return: List of ADK-compatible FunctionTool instances.
        """
        tools = []
        for func in funcs:
            tools.append(FunctionTool(cls._wrap(func)))
        return tools

    @classmethod
    def _wrap(cls, func: Callable) -> Callable:
        """
        Wraps a generic tool function to ensure it can be used with the Google ADK.

        :param func: The generic tool function to wrap.
        :return: A wrapped version of the function that is compatible with the Google ADK.
        :raises TypeError: If the function is not callable.
        """
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__}")

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, tool_context: ToolContext, **kwargs: Any) -> Any:
                tctx: AKToolContext | None = None
                try:
                    if tool_context and tool_context.state and tool_context.state.get("ak_tool_context"):
                        tctx = AKToolContext.fetch(tool_context.state["ak_tool_context"]).set()
                    return await func(*args, **kwargs)
                finally:
                    if tctx:
                        tctx.reset()

        else:

            @functools.wraps(func)
            def wrapper(*args: Any, tool_context: ToolContext, **kwargs: Any) -> Any:
                tctx: AKToolContext | None = None
                try:
                    if tool_context and tool_context.state and tool_context.state.get("ak_tool_context"):
                        tctx = AKToolContext.fetch(tool_context.state["ak_tool_context"]).set()
                    return func(*args, **kwargs)
                finally:
                    if tctx:
                        tctx.reset()

        signature = inspect.signature(func)
        parameters = list(signature.parameters.values())

        # Only add a tool_context parameter if the original function does not already
        # declare one, and insert it before any **kwargs (VAR_KEYWORD) parameter to
        # maintain a valid inspect.Signature ordering.
        if "tool_context" not in signature.parameters:
            tool_context_param = inspect.Parameter(
                "tool_context",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
            )

            insert_index = None
            for idx, param in enumerate(parameters):
                if param.kind is inspect.Parameter.VAR_KEYWORD:
                    insert_index = idx
                    break

            if insert_index is not None:
                parameters.insert(insert_index, tool_context_param)
            else:
                parameters.append(tool_context_param)

        wrapper.__signature__ = signature.replace(parameters=parameters)
        return wrapper
