from ak import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner, Session as BaseSession

from typing import Any, Sequence, TypedDict, Annotated, Callable, List, Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver

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



class LangGraphSession(BaseSession):
    """
    LangGraphSession class provides a session for LangGraph Agents SDK-based agents,
    without relying on a custom TypedDict like AgentState.
    """

    def __init__(self, checkpointer: MemorySaver = None):
        super().__init__(FRAMEWORK)
        self.checkpointer = checkpointer or MemorySaver()
        self._handoff: Optional[str] = None  # Optional handoff tracking

    async def get_state(self) -> dict:
        """
        Retrieve the current state from the checkpoint system.
        Returns a dictionary with keys like 'messages' and 'handoff_to_agent'.
        """
        tup = await self.checkpointer.aget_tuple(self._config())

        if tup is not None:
            messages = tuple(tup.checkpoint.channel_values.get("messages", ()))
        else:
            messages = ()

        return {
            "messages": messages,
            "handoff_to_agent": self._handoff,
        }

    async def get_items(self, limit: Optional[int] = None) -> list[BaseMessage]:
        """
        Return list of BaseMessage in chronological order,
        optionally truncated to the most recent `limit` messages.
        """
        state = await self.get_state()
        messages = state["messages"]
        return list(messages[-limit:] if limit else messages)

    async def summarize_chat_history(self, previous_chat_history_summary: str):
        """
        Stub method to be implemented by subclasses or injected logic.
        Should summarize the chat using previous summary and recent messages.
        """
        raise NotImplementedError("summarize_chat_history must be implemented by the subclass or session logic.")


class LangGraphRunner(BaseRunner):
    """
    LangGraphRunner class provides a runner for LangGraph Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an LangGraphRunner instance.
        """
        super().__init__(FRAMEWORK)

    async def run(self, agent: LangGraphAgent, session: LangGraphSession, prompt: Any) -> Any:
        session_config = LangGraphSessionConfigModel(
            configurable=LangGraphSessionConfigurable(
                thread_id=session.id
            )
        )
        result = await agent.agent.ainvoke(input={"messages": [HumanMessage(content=prompt)]}, config=session_config.model_dump())
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
