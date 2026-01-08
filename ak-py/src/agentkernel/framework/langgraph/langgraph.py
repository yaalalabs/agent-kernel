from __future__ import annotations

from typing import Any, AsyncIterator, Iterator, List, Optional, Sequence

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from agentkernel.core.base import Session
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText

from ...core import Agent as BaseAgent
from ...core import Module as BaseModule
from ...core import PostHook, PreHook
from ...core import Runner as BaseRunner
from ...core import Session as BaseSession
from ...core.config import AKConfig
from ...trace import Trace

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
            parent_config=checkpoint_data.get("parent_config"),
        )

    def list(
        self,
        config: Optional[dict] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        result = []
        if config:
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id and thread_id in self._storage:
                thread_data = self._storage[thread_id]
                for ns, data in thread_data.items():
                    checkpoint_config: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}}
                    result.append(
                        CheckpointTuple(
                            config=checkpoint_config,
                            checkpoint=data["checkpoint"],
                            metadata=data.get("metadata", {}),
                            parent_config=data.get("parent_config"),
                        )
                    )
                if limit:
                    result = result[:limit]
        return iter(result)

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
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
            "parent_config": config.get("parent_config"),
        }

        return config

    def put_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        if not thread_id:
            return

        if thread_id not in self._writes:
            self._writes[thread_id] = {}

        if checkpoint_ns not in self._writes[thread_id]:
            self._writes[thread_id][checkpoint_ns] = []

        self._writes[thread_id][checkpoint_ns].append({"task_id": task_id, "task_path": task_path, "writes": writes})

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
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
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

    def __init__(self, name: str, runner: "LangGraphRunner", agent: CompiledStateGraph):
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
            if hasattr(node_data, "tools"):
                for tool in node_data.tools:
                    skills.append(
                        AgentSkill(
                            id=tool.name,
                            name=tool.name,
                            description=tool.description,
                            tags=[],
                        )
                    )
        # TODO extract description from graph
        return self._generate_a2a_card(agent_name=self.name, description="", skills=skills)


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

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the LangGraph agent with provided multi modal inputs.
        :param agent: The LangGraph agent to run.
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
                    text="Sorry. Agent kernel LangGraph runner is unable to handle content other than text at the moment",
                    prompt=prompt,
                )

        if prompt.strip() == "":
            return AgentReplyText(text="Sorry. No valid text prompt found in the requests")

        session_config = LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=session.id))
        agent.agent.checkpointer = self._session(session).checkpointer
        result = await agent.agent.ainvoke(
            input={"messages": [HumanMessage(content=prompt)]},
            config=session_config.model_dump(),
        )
        last_message = result["messages"][-1]
        return AgentReplyText(text=last_message.content, prompt=prompt)


class LangGraphModule(BaseModule):
    """
    LangGraphModule class provides a module for LangGraph Agent SDK-based agents.
    """

    def __init__(self, agents: list[CompiledStateGraph], runner: LangGraphRunner = None):
        """
        Initializes a LangGraphModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().langgraph()
        else:
            self.runner = LangGraphRunner()
        self.load(agents)

    def _wrap(self, agent: CompiledStateGraph, agents: List[CompiledStateGraph]) -> BaseAgent:
        return LangGraphAgent(name=agent.name, runner=self.runner, agent=agent)

    def load(self, agents: list[CompiledStateGraph]) -> "LangGraphModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: LangGraphModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: CompiledStateGraph, hooks: list[PreHook]) -> "LangGraphModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: LangGraphModule instance.
        """
        super().get_agent(agent.name).attach_pre_hooks(hooks)
        return self

    def post_hook(self, agent: CompiledStateGraph, hooks: list[PostHook]) -> "LangGraphModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: LangGraphModule instance.
        """
        super().get_agent(agent.name).attach_post_hooks(hooks)
        return self
