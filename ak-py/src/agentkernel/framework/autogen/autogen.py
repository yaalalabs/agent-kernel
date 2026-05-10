import asyncio
from typing import Any, Callable, List

import autogen
from autogen import ConversableAgent

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
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "autogen"
AutogenSupportedAgent = ConversableAgent


class AutogenSession:
    """
    Session store for autogen based agents.
    """

    def __init__(self):
        self._history: list[dict] = []

    def get_history(self) -> list[dict]:
        return self._history

    def set_history(self, history: list[dict]) -> None:
        self._history = history

    def clear(self) -> None:
        self._history.clear()


class AutogenRunner(Runner):
    def __init__(self):
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> AutogenSession | None:
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, AutogenSession())

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            for req in requests:
                if isinstance(req, AgentRequestAny):  # AgentRequestAny is handled only by pre-hooks, not by the agent itself
                    continue
                if isinstance(req, AgentRequestText):
                    prompt = prompt + "\n" + req.text if prompt else req.text
                else:
                    return AgentReplyText(
                        text="Sorry. Agent kernel AutoGen runner is unable to handle content other than text at the moment",
                        prompt=prompt,
                    )

            if prompt.strip() == "":
                return AgentReplyText(text="Sorry. No valid text prompt found in the requests")

            # Create a user proxy to act on behalf of the user and trigger the interaction
            user_proxy = autogen.UserProxyAgent(
                name="user_proxy",
                human_input_mode="NEVER",
                max_consecutive_auto_reply=10,
                code_execution_config=False,
                is_termination_msg=lambda x: not x.get("tool_calls", None) and not x.get("function_call", None),
            )

            # Register tools
            if hasattr(agent, "_ak_tools"):
                for tool in agent._ak_tools:
                    autogen.register_function(
                        tool,
                        caller=agent.agent,
                        executor=user_proxy,
                        name=getattr(tool, "name", tool.__name__),
                        description=getattr(tool, "description", tool.__doc__ or tool.__name__),
                    )

            # Rehydrate history
            ag_session = self._session(session)
            if ag_session and ag_session.get_history():
                agent.agent.chat_messages[user_proxy] = ag_session.get_history().copy()

            # Execute reasoning in separate thread
            result = await asyncio.to_thread(user_proxy.initiate_chat, agent.agent, message=prompt, clear_history=False, summary_method="last_msg")

            # Extract reply text from the result
            reply_text = result.summary if result.summary else str(result.chat_history[-1].get("content", ""))

            # Sync history
            if ag_session:
                ag_session.set_history(agent.agent.chat_messages[user_proxy].copy())

            return AgentReplyText(text=reply_text, prompt=prompt)
        except Exception as e:
            return AgentReplyText(text=user_facing_error_message(e), prompt=prompt)
        finally:
            if "user_proxy" in locals() and hasattr(agent, "agent"):
                agent.agent.chat_messages.pop(user_proxy, None)
            if context is not None:
                context.reset()


class AutogenToolBuilder(ToolBuilder):
    @classmethod
    def bind(cls, tools: list[Callable]) -> list[Any]:
        return tools


class AutogenAgent(BaseAgent):
    def __init__(self, name: str, runner: AutogenRunner, agent: AutogenSupportedAgent):
        super().__init__(name, runner)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> AutogenSupportedAgent:
        return self._agent

    def get_description(self):
        return getattr(self.agent, "system_message", "autogen agent")

    def override_system_prompt(self, prompt: str) -> None:
        if hasattr(self.agent, "system_message") and self.agent.system_message:
            if prompt not in self.agent.system_message:
                self.agent.update_system_message(self.agent.system_message + "\n" + prompt)

    def attach_tool(self, tool: Any) -> None:
        wrapped = AutogenToolBuilder.bind([tool])
        for w in wrapped:
            if not hasattr(self, "_ak_tools"):
                self._ak_tools = []
            if w not in self._ak_tools:
                self._ak_tools.append(w)

    def get_a2a_card(self):
        from a2a.types import AgentSkill

        skills = []
        tools_list = getattr(self, "_ak_tools", [])
        for tool in tools_list:
            skills.append(
                AgentSkill(
                    id=getattr(tool, "name", tool.__name__),
                    name=getattr(tool, "name", tool.__name__),
                    description=getattr(tool, "description", tool.__doc__ or tool.__name__),
                    tags=[],
                )
            )
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class AutogenModule(Module):
    def __init__(self, agents: list[AutogenSupportedAgent], runner: AutogenRunner = None):
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            # Fallback gracefully if Trace doesn't implement autogen() yet
            if hasattr(Trace.get(), "autogen"):
                self.runner = Trace.get().autogen()
            else:
                self.runner = AutogenRunner()
        else:
            self.runner = AutogenRunner()
        self.load(agents)

    def _wrap(self, agent: AutogenSupportedAgent, agents: List[AutogenSupportedAgent]) -> BaseAgent:
        return AutogenAgent(agent.name if hasattr(agent, "name") else "autogen_agent", self.runner, agent)

    def load(self, agents: list[AutogenSupportedAgent]) -> "AutogenModule":
        super().load(agents)
        return self

    def pre_hook(self, agent: AutogenSupportedAgent, hooks: list[PreHook]) -> "AutogenModule":
        name = getattr(agent, "name", "autogen_agent")
        self.get_agent(name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: AutogenSupportedAgent, hooks: list[PostHook]) -> "AutogenModule":
        name = getattr(agent, "name", "autogen_agent")
        self.get_agent(name).post_hooks.extend(hooks)
        return self
