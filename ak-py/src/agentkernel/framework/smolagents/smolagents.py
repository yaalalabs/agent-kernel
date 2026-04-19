from typing import Any, Callable, List

from smolagents import CodeAgent, MultiStepAgent, ToolCallingAgent
from smolagents import tool as smol_tool

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook, Runner, Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.model import (
    AgentReply,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestText,
)
from ...trace import Trace

FRAMEWORK = "smolagents"
SmolagentsSupportedAgent = MultiStepAgent | CodeAgent | ToolCallingAgent


class SmolagentsSession:
    """Session class for smolagents based agents."""

    def __init__(self):
        self._items: list[Any] = []

    def get_items(self) -> list[Any]:
        return self._items

    def add_items(self, items: list[Any]) -> None:
        self._items.extend(items)

    def clear(self) -> None:
        self._items.clear()


class SmolagentsRunner(Runner):
    """Runner for smolagents based agents."""

    def __init__(self):
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> SmolagentsSession | None:
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, SmolagentsSession())

    @staticmethod
    def _has_memory(agent: Any) -> bool:
        return hasattr(agent.agent, "memory") and hasattr(agent.agent.memory, "steps")

    @classmethod
    def _hydrate_memory(cls, agent: Any, session: Session) -> None:
        if session is None or not cls._has_memory(agent):
            return
        smol_session = cls._session(session)
        saved_steps = smol_session.get_items()
        # Always hydrate when running with reset=False to prevent session bleed.
        agent.agent.memory.steps = saved_steps.copy()

    @classmethod
    def _sync_memory(cls, agent: Any, session: Session) -> None:
        if session is None or not cls._has_memory(agent):
            return
        smol_session = cls._session(session)
        smol_session.clear()
        # Runtime-managed session backends (e.g., Redis/DynamoDB) handle storage.
        smol_session.add_items(agent.agent.memory.steps)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            for req in requests:
                if isinstance(req, AgentRequestAny):
                    continue
                if isinstance(req, AgentRequestText):
                    prompt = prompt + "\n" + req.text if prompt else req.text
                else:
                    return AgentReplyText(
                        text="Sorry. Smolagents runner is unable to handle content other than text at the moment",
                        prompt=prompt,
                    )

            if not prompt.strip():
                return AgentReplyText(text="Sorry. No valid text prompt found in the requests")

            # Rehydrate framework memory from the AgentKernel session before execution.
            self._hydrate_memory(agent, session)

            # Preserve conversational continuity across requests.
            reply = agent.agent.run(prompt, reset=False)

            # Persist updated framework memory back to the AgentKernel session.
            self._sync_memory(agent, session)

            return AgentReplyText(text=str(reply), prompt=prompt)
        except Exception as e:
            return AgentReplyText(text=f"Error during agent execution: {str(e)}", prompt=prompt)
        finally:
            if context is not None:
                context.reset()


class SmolagentsAgent(BaseAgent):
    """Agent wrapping for smolagents based agents."""

    def __init__(self, name: str, runner: SmolagentsRunner, agent: SmolagentsSupportedAgent):
        super().__init__(name, runner)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> SmolagentsSupportedAgent:
        return self._agent

    def get_description(self):
        return getattr(self.agent, "system_prompt", getattr(self.agent, "description", "smolagents agent"))

    def override_system_prompt(self, prompt: str) -> None:
        # Newer smolagents versions expose a read-only `system_prompt`.
        # For those versions, update prompt_templates["system_prompt"] instead.
        prompt_templates = getattr(self.agent, "prompt_templates", None)
        if isinstance(prompt_templates, dict):
            current = prompt_templates.get("system_prompt") or ""
            if prompt not in current:
                prompt_templates["system_prompt"] = f"{current}\n{prompt}" if current else prompt
            return

        if hasattr(self.agent, "system_prompt") and self.agent.system_prompt:
            if prompt not in self.agent.system_prompt:
                try:
                    self.agent.system_prompt += "\n" + prompt
                except Exception:
                    pass
            return

        # Fallback for implementations that use `description` instead of `system_prompt`.
        if hasattr(self.agent, "description") and self.agent.description:
            if prompt not in self.agent.description:
                self.agent.description += "\n" + prompt

    def attach_tool(self, tool: Any) -> None:
        wrapped = SmolagentsToolBuilder.bind([tool])
        for w in wrapped:
            if not hasattr(self.agent, "tools") or self.agent.tools is None:
                self.agent.tools = []
            if isinstance(self.agent.tools, dict):
                if w.name not in self.agent.tools:
                    self.agent.tools[w.name] = w
            elif isinstance(self.agent.tools, list):
                if w not in self.agent.tools:
                    self.agent.tools.append(w)

        # Smolagents caches tool descriptions in the system prompt during init.
        # Rebuild the prompt cache after attaching tools.
        if hasattr(self.agent, "initialize_system_prompt"):
            try:
                new_prompt = self.agent.initialize_system_prompt()
                if hasattr(self.agent, "memory") and hasattr(self.agent.memory, "system_prompt"):
                    self.agent.memory.system_prompt.system_prompt = new_prompt
            except Exception:
                pass

    def get_a2a_card(self):
        from a2a.types import AgentSkill

        skills = []
        raw_tools = getattr(self.agent, "tools", [])
        tools_list = raw_tools.values() if isinstance(raw_tools, dict) else raw_tools

        for tool in tools_list:
            skills.append(AgentSkill(id=tool.name, name=tool.name, description=getattr(tool, "description", ""), tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class SmolagentsModule(Module):
    """Module for compiling smolagents based agents."""

    def __init__(self, agents: list[SmolagentsSupportedAgent], runner: SmolagentsRunner = None):
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().smolagents()
        else:
            self.runner = SmolagentsRunner()
        self.load(agents)

    def _wrap(self, agent: SmolagentsSupportedAgent, agents: List[SmolagentsSupportedAgent]) -> BaseAgent:
        name = getattr(agent, "name", "smolagent")
        return SmolagentsAgent(name, self.runner, agent)

    def load(self, agents: list[SmolagentsSupportedAgent]) -> "SmolagentsModule":
        super().load(agents)
        return self

    def pre_hook(self, agent: SmolagentsSupportedAgent, hooks: list[PreHook]) -> "SmolagentsModule":
        name = getattr(agent, "name", "smolagent")
        super().get_agent(name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: SmolagentsSupportedAgent, hooks: list[PostHook]) -> "SmolagentsModule":
        name = getattr(agent, "name", "smolagent")
        super().get_agent(name).post_hooks.extend(hooks)
        return self


class SmolagentsToolBuilder(ToolBuilder):
    """Tool builder for smolagents."""

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(smol_tool(func))
        return tools
