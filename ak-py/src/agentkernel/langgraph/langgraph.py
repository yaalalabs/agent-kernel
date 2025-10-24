from typing import Any, AsyncIterator, Iterator, Optional, Sequence

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ..core import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner, Session as BaseSession

FRAMEWORK = "langgraph"


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
            parent_config=checkpoint_data.get("parent_config")
        )

    def list(
            self,
            config: Optional[dict] = None,
            *,
            filter: Optional[dict[str, Any]] = None,
            before: Optional[dict] = None,
            limit: Optional[int] = None
    ) -> Iterator[CheckpointTuple]:
        result = []
        if config:
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id and thread_id in self._storage:
                thread_data = self._storage[thread_id]
                for ns, data in thread_data.items():
                    checkpoint_config: RunnableConfig = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": ns
                        }
                    }
                    result.append(CheckpointTuple(
                        config=checkpoint_config,
                        checkpoint=data["checkpoint"],
                        metadata=data.get("metadata", {}),
                        parent_config=data.get("parent_config")
                    ))
                if limit:
                    result = result[:limit]
        return iter(result)

    def put(
            self,
            config: dict,
            checkpoint: Checkpoint,
            metadata: CheckpointMetadata,
            new_versions: dict
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
            "parent_config": config.get("parent_config")
        }

        return config

    def put_writes(
            self,
            config: dict,
            writes: Sequence[tuple[str, Any]],
            task_id: str,
            task_path: str = ""
    ) -> None:
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        if not thread_id:
            return

        if thread_id not in self._writes:
            self._writes[thread_id] = {}

        if checkpoint_ns not in self._writes[thread_id]:
            self._writes[thread_id][checkpoint_ns] = []

        self._writes[thread_id][checkpoint_ns].append({
            "task_id": task_id,
            "task_path": task_path,
            "writes": writes
        })

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
            limit: Optional[int] = None
    ) -> AsyncIterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
            self,
            config: dict,
            checkpoint: Checkpoint,
            metadata: CheckpointMetadata,
            new_versions: dict
    ) -> dict:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
            self,
            config: dict,
            writes: Sequence[tuple[str, Any]],
            task_id: str,
            task_path: str = ""
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

    def __init__(self, name: str, runner: 'LangGraphRunner', agent: CompiledStateGraph):
        """
        Initializes a LangGraphAgent instance.
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


class LangGraphSession:
    """
    LangGraphSession class provides a session for LangGraph Agents SDK-based agents
    """

    def __init__(self):
        """
        Initializes a LangGraphSession instance with a pickle-serializable checkpointer.
        """
        self._checkpointer = CheckPointer()

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
    def _session(session: BaseSession) -> Any | None:
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
        agent.agent.checkpointer = self._session(session).checkpointer
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
