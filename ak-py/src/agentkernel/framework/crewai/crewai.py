import logging
from typing import Any, Callable, List

from crewai import Agent, Crew, Memory, Task
from crewai.memory.storage.interface import Storage
from crewai.tools import tool as crewai_tool

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook, Runner, Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "crewai"


class CrewAISession(Storage):
    """
    CrewAISession class provides a session for CrewAI based agents.
    """

    def __init__(self):
        """
        Initializes a CrewAISession instance.
        """
        self._items = []
        self._log = logging.getLogger("ak.crewai.session")

    def save(self, value: Any, metadata=None, agent=None) -> None:
        """
        Saves an item to the session.
        :param value: The value to save.
        :param metadata: Optional metadata associated with the value.
        :param agent: Optional agent associated with the value.
        """
        self._log.debug(f"save: {value}, {metadata}, {agent}")
        if metadata is None:
            metadata = {}
        if agent is None:
            agent = "Unknown"
        self._items.append({"value": value, "metadata": metadata, "agent": agent})

    def search(self, query: str, limit: int = 10, score_threshold: float = 0.5) -> list[dict]:
        """
        Searches for items in the session that match the query.
        :param query: The search query.
        :param limit: Maximum number of results to return.
        :param score_threshold: Minimum score threshold for results.
        :return: List of items matching the query.
        """
        self._log.debug(f"search: {query}, {limit}, {score_threshold}")
        return list(map(lambda item: {"content": item["value"], "context": item["value"]}, self._items[-limit:]))

    def reset(self) -> None:
        """
        Resets the session by clearing all items.
        """
        self._log.debug("reset")
        self._items = []


class CrewAIRunner(Runner):
    """
    CrewAIRunner class provides a runner for CrewAI based agents.
    """

    def __init__(self):
        """
        Initializes a CrewAIRunner instance.
        """
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.crewai.runner")

    def _memory(self, session: Session) -> Memory | None:
        """
        Returns the external memory associated with the session.
        :param session: The session to retrieve the memory for.
        :return: The external memory for the session, or None if the session is not provided.
        """
        if session is None:
            self._log.debug("Running without session")
            return None
        if session.get(FRAMEWORK) is None:
            self._log.debug("Creating new CrewAISession")
            previous = session.set(FRAMEWORK, CrewAISession())
        else:
            self._log.debug("Reusing existing CrewAISession")
            previous = session.get(FRAMEWORK)
        return Memory(previous)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the CrewAI agent with provided multi modal inputs.
        :param agent: The CrewAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
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
                        text="Sorry. Agent kernel CrewAI runner is unable to handle content other than text at the moment",
                        prompt=prompt,
                    )

            if prompt.strip() == "":
                return AgentReplyText(text="Sorry. No valid text prompt found in the requests")

            ext_memory = self._memory(session)

            # Persist the user's prompt so it is available via external memory search on subsequent turns
            if ext_memory and ext_memory.storage:
                ext_memory.storage.save(f"User: {prompt}")

            task = Task(
                description=prompt,
                expected_output="An answer is plain text",
                agent=agent.agent,
            )
            crew = Crew(
                agents=agent.crew,
                tasks=[task],
                verbose=False,
                external_memory=ext_memory,
            )
            reply = crew.kickoff(inputs={})
            if hasattr(reply, "raw"):
                raw_reply = reply.raw
                reply_text = "" if raw_reply is None else str(raw_reply)
            else:
                reply_text = "" if reply is None else str(reply)

            return AgentReplyText(text=reply_text, prompt=prompt)
        except Exception as e:
            return AgentReplyText(text=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()


class CrewAIAgent(BaseAgent):
    """
    CrewAIAgent class provides an agent wrapping for CrewAI based agents.
    """

    def __init__(self, name: str, runner: CrewAIRunner, agent: Agent, crew: list[Agent]):
        """
        Initializes a CrewAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The CrewAI agent instance.
        :param crew: List of CrewAI agents in the crew.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._crew = crew
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Agent:
        """
        Returns the CrewAI agent instance.
        """
        return self._agent

    @property
    def crew(self) -> list[Agent]:
        """
        Returns the list of CrewAI agents in the crew.
        """
        return self._crew

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.goal or self.agent.backstory

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []
        for tool in self.agent.tools:
            skills.append(AgentSkill(id=tool.name, name=tool.name, description=tool.description, tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.agent.backstory, skills=skills)

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable and wraps it with CrewAIToolBuilder before attaching,
        so the base Agent._attach_system_tools() can pass raw functions generically.
        :param tool: Raw Python callable or already-wrapped CrewAI tool.
        """
        # Delegate to the tool builder to handle binding
        wrapped = CrewAIToolBuilder.bind([tool])
        for w in wrapped:
            if not hasattr(self.agent, "tools") or self.agent.tools is None:
                self.agent.tools = []
            if w not in self.agent.tools:
                self.agent.tools.append(w)

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends the given prompt text to the CrewAI agent's backstory.
        Called by the base Agent._setup_system_prompt() at init when multimodal is enabled.
        """
        if prompt not in self._agent.backstory:
            self._agent.backstory += "\n" + prompt


class CrewAIModule(Module):
    """
    CrewAIModule class provides a module for CrewAI based agents.
    """

    def __init__(self, agents: list[Agent], runner: CrewAIRunner = None):
        """
        Initializes a CrewAIModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().crewai()
        else:
            self.runner = CrewAIRunner()
        self.load(agents)

    def _wrap(self, agent: Agent, agents: List[Agent]) -> BaseAgent:
        """
        Wraps the provided agent in a CrewAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: CrewAIAgent instance.
        """
        return CrewAIAgent(agent.role, self.runner, agent, agents)

    def load(self, agents: list[Agent]) -> "CrewAIModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: CrewAIModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: Agent, hooks: list[PreHook]) -> "CrewAIModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: CrewAIModule instance.
        """
        super().get_agent(agent.role).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: Agent, hooks: list[PostHook]) -> "CrewAIModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: CrewAIModule instance.
        """
        super().get_agent(agent.role).post_hooks.extend(hooks)
        return self


class CrewAIToolBuilder(ToolBuilder):
    """
    Tool builder for CrewAI.

    Wraps generic tool functions into CrewAI-compatible tool definitions
    using the ``@tool`` decorator from the CrewAI SDK.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to CrewAI tool definitions.

        :param funcs: List of generic tool functions to bind.
        :return: List of CrewAI-compatible tool definitions.
        :raises TypeError: If any item in funcs is not callable.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(crewai_tool(func))
        return tools
