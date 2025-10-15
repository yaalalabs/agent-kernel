from typing import Any, Optional

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ..core import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner, Session as BaseSession

FRAMEWORK = "langgraph"


class LangGraphSessionConfigurable(BaseModel):
    thread_id: str


class LangGraphSessionConfigModel(BaseModel):
    configurable: LangGraphSessionConfigurable


class LangGraphAgent(BaseAgent):
    """
    LangGraphAgent class provides an agent wrapping for LangGraph Agents SDK based agents.
    """

    def __init__(self, name: str, runner: 'LangGraphRunner', agent: CompiledStateGraph):
        """
        Initializes an LangGraphAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The LangGraph agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

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
            if hasattr(node_data, 'tools'):
                for tool in node_data.tools:
                    skills.append(AgentSkill(
                        id=tool.name,
                        name=tool.name,
                        description=tool.description,
                        tags=[]
                    ))
        # TODO extract description from graph
        return self._generate_a2a_card(
            agent_name=self.name,
            description="",
            skills=skills
        )


class LangGraphSession(BaseSession):
    """
    LangGraphSession class provides a session for LangGraph Agents SDK-based agents,
    without relying on a custom TypedDict like AgentState.
    """

    def __init__(self):
        """
        Initializes a LangGraphSession instance.
        """
        super().__init__(FRAMEWORK)
        self._checkpointer = MemorySaver()

    def _get_config(self) -> dict:
        """
        Returns the configuration for the LangGraph session.
        This includes the thread ID and any other necessary configuration.
        """
        return LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=self.id)).model_dump()

    async def get_state(self) -> dict:
        """
        Retrieve the current state from the checkpoint system.
        Returns a dictionary with keys like 'messages'.
        """
        raw_config = self._get_config()
        tup = await self._checkpointer.aget_tuple(RunnableConfig(configurable=raw_config.get("configurable", {})))

        if tup is not None:
            messages = tuple(tup.checkpoint.channel_values.get("messages", ()))
        else:
            messages = ()

        return {
            "messages": messages,
        }

    async def get_items(self, limit: Optional[int] = None) -> list[BaseMessage]:
        """
        Return list of BaseMessage in chronological order,
        optionally truncated to the most recent `limit` messages.
        """
        state = await self.get_state()
        messages = state["messages"]
        return list(messages[-limit:] if limit else messages)


class LangGraphRunner(BaseRunner):
    """
    LangGraphRunner class provides a runner for LangGraph Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an LangGraphRunner instance.
        """
        super().__init__(FRAMEWORK)

    def _session(self, session: BaseSession) -> LangGraphSession:
        """
        Returns the LangGraph session associated with the provided session.
        :param session: The session to retrieve the LangGraph session for.
        :return: LangGraphSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, LangGraphSession())

    async def run(self, agent: LangGraphAgent, session: BaseSession, prompt: Any) -> Any:
        """
        Runs the LangGraph agent with the provided session and prompt.
        :param agent: The LangGraph agent to run.
        :param session: The session to run the agent in.
        :param prompt: The input prompt for the agent.
        :return: The response from the agent.
        """
        session_config = LangGraphSessionConfigModel(
            configurable=LangGraphSessionConfigurable(
                thread_id=session.id
            )
        )
        agent.agent.checkpointer = self._session(session)._checkpointer
        result = await agent.agent.ainvoke(input={"messages": [HumanMessage(content=prompt)]},
                                           config=session_config.model_dump())
        last_message = result["messages"][-1]
        return last_message.content


class LangGraphModule(BaseModule):
    """
    LangGraphModule class provides a module for LangGraph Agent SDK based agents.
    """

    def __init__(self, agents: list[CompiledStateGraph]):
        """
        Initializes a LangGraphModule instance.
        :param agents: List of agents in the module.
        """
        runner = LangGraphRunner()
        super().__init__(list(map(lambda agent: LangGraphAgent(name=agent.name, runner=runner, agent=agent), agents)))
