import logging
from typing import Any, List

from crewai import Agent, Crew, Task
from crewai.memory.external.external_memory import ExternalMemory
from crewai.memory.storage.interface import Storage

from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook, Runner, Session
from ...core.config import AKConfig
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
        return list(map(lambda item: {"context": item["value"]}, self._items[:limit]))  # CrewAI expects a list of dicts with a "context" key

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

    def _memory(self, session: Session) -> ExternalMemory | None:
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
        return ExternalMemory(previous)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the CrewAI agent with provided multi modal inputs.
        :param agent: The CrewAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
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

        task = Task(
            description=prompt,
            expected_output="An answer is plain text",
            agent=agent.agent,
        )
        crew = Crew(
            agents=agent.crew,
            tasks=[task],
            verbose=False,
            external_memory=self._memory(session),
        )
        reply = crew.kickoff(inputs={})
        if hasattr(reply, "raw"):
            reply = str(reply.raw)
        else:
            reply = str(reply)

        return AgentReplyText(text=reply, prompt=prompt)


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
        return self._generate_a2a_card(agent_name=self.name, description=self.agent.backstory, skills=skills)


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
        super().get_agent(agent.role).attach_pre_hooks(hooks)
        return self

    def post_hook(self, agent: Agent, hooks: list[PostHook]) -> "CrewAIModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: CrewAIModule instance.
        """
        super().get_agent(agent.role).attach_post_hooks(hooks)
        return self
