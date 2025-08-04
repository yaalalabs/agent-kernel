import uuid

from ak import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner, Session as BaseSession
from ak_common.log.logger import get_logger

from typing import Any, Sequence, TypedDict, Annotated, Callable, List, Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from langchain_community.chat_models.litellm import ChatLiteLLM
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from langchain_core.output_parsers.json import parse_json_markdown
from langgraph.checkpoint.memory import MemorySaver

FRAMEWORK = "langgraph"

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    handoff_to_agent: Optional[str] = None

class LiteLLMModel(BaseModel):
    model_name: str
    temperature: float
    api_key: str

class StructuredLLMResponse(BaseModel):
    llm_response_message: str
    handoff_to_agent: Optional[str] = None

class LangGraphSessionConfigurable(BaseModel):
    thread_id: str
class LangGraphSessionConfigModel(BaseModel):
    configurable: LangGraphSessionConfigurable

class LangGraphAgent(BaseAgent):
    def __init__(
        self, 
        name: str,
        description: str, 
        model: LiteLLMModel, 
        system_prompt: str, 
        runner: BaseRunner,
        tool_functions: List[Callable[..., Any]] = [], 
        handoffs: Optional[List['LangGraphAgent']] = None,
        session: Optional['LangGraphSession'] = None
    ):
        self.log = get_logger(name)
        self.handoff_agents = {}
        if handoffs:
            for agent in handoffs:
                if not hasattr(agent, 'graph') or agent.graph is None:
                    agent._initialize_graph()
                self.handoff_agents[agent.name] = agent
        self.description = description
        self.system_message = SystemMessage(content=self._build_system_prompt(system_prompt))
        self.model = ChatLiteLLM(model=model.model_name, temperature=model.temperature, api_key=model.api_key)
        self.tools = [
            StructuredTool.from_function(func=fn, name=fn.__name__, description=fn.__doc__)
            if not isinstance(fn, BaseTool) else fn
            for fn in tool_functions
        ]
        self.session = session
        super().__init__(name=name, runner=runner)
        self._initialize_graph()

    def _build_system_prompt(self, base_prompt: str) -> str:
        if not self.handoff_agents:
            return base_prompt

        handoff_prompt = f"""

HANDOFF CAPABILITIES:
You can transfer control to the following specialized agents:
{chr(10).join([f"- {name}: {agent.description}" for name, agent in self.handoff_agents.items()])}

Respond in JSON with keys:
- "llm_response_message": your response to the user
- optional "handoff_to_agent": one of [{', '.join(self.handoff_agents.keys())}]

Only use handoffs when the task genuinely requires the other agent's specialized capabilities."""
        
        return base_prompt + handoff_prompt

    def _llm_call(self, state: AgentState) -> dict:
        """Call the LLM with optional handoff processing."""
        messages = [self.system_message] + list(state["messages"])
        use_handoff = bool(self.handoff_agents)
        self.log.info(f"Invoking LLM {'with' if use_handoff else 'without'} handoff... Input State: {state}")
        response: BaseMessage = self.model.invoke(messages)
        self.log.info(f"LLM {'with' if use_handoff else 'without'} handoff... Response Type: {response.type}, Response: {response}")
        if use_handoff and response.content:
            try:
                response_dict = parse_json_markdown(response.content)
                structured_response = StructuredLLMResponse.model_validate(response_dict)
                tool_calls = response.additional_kwargs.get("tool_calls", [])

                self.log.info(f"Parsed LLM response with handoff check: {response_dict}")
                return {
                    "messages": [AIMessage(content=structured_response.llm_response_message, metadata={"agent_name": self._name}, 
                                           additional_kwargs={"tool_calls": tool_calls} if tool_calls else {})],
                    "handoff_to_agent": structured_response.handoff_to_agent
                }
            except Exception as e:
                self.log.info(f"Error parsing LLM response therefore returning raw response. ERROR: {e}")
        self.log.info("Returning raw response without handoff processing")
        return {"messages": [response]}


    def _select_next_node(self, state: AgentState) -> str:
        handoff = state.get("handoff_to_agent")
        self.log.info(f"Selecting next node, handoff requested: {handoff}")
        if handoff and handoff in self.handoff_agents:
            self.log.info(f"Valid handoff to agent: {handoff}")
            return handoff
        elif handoff:
            self.log.info(f"WARNING: Invalid handoff requested to '{handoff}', available agents: {list(self.handoff_agents.keys())}")
        return tools_condition(state)

    def _create_handoff_node(self, target_agent: 'LangGraphAgent'):
        def handoff_node(state: AgentState) -> dict:
            state_for_handoff_node = {"messages": state["messages"][:-1], "handoff_to_agent": None}
            self.log.info(f"Executing handoff to agent: {target_agent.name}")
            result = target_agent.graph.invoke(state_for_handoff_node)["messages"][-1]
            self.log.info(f"Result from handoff agent '{target_agent.name}': {result}")
            return {"messages": result, "handoff_to_agent": None}
        return handoff_node

    def _build_graph(self) -> CompiledStateGraph:
        self.log.info(f"Building graph for agent: {self._name}")
        graph = StateGraph(AgentState)

        self.log.info(f"Adding main LLM call node: {self._name}")
        graph.add_node(self._name, self._llm_call)

        if self.tool_node:
            self.log.info(f"Adding tools node")
            graph.add_node("tools", self.tool_node)

        for agent_name, agent in self.handoff_agents.items():
            self.log.info(f"Adding handoff node for agent: {agent_name}")
            graph.add_node(agent_name, self._create_handoff_node(agent))

        edge_mapping = {"__end__": END}

        if self.tool_node:
            self.log.info("Adding tools to edge mapping")
            edge_mapping["tools"] = "tools"

        for agent_name in self.handoff_agents.keys():
            self.log.info(f"Adding '{agent_name}' to edge mapping")
            edge_mapping[agent_name] = agent_name

        self.log.info(f"Adding conditional edges from main node EDGE MAPPING: {edge_mapping}")
        graph.add_conditional_edges(
            self._name,
            self._select_next_node,
            edge_mapping
        )

        if self.tool_node:
            self.log.info(f"Adding edge from tools back to main node")
            graph.add_edge("tools", self._name)

        for agent_name in self.handoff_agents.keys():
            self.log.info(f"Adding edge from handoff agent '{agent_name}' to END")
            graph.add_edge(agent_name, END)

        self.log.info(f"Setting entry point: {self._name}")
        graph.set_entry_point(self._name)
        compiled = graph.compile(checkpointer=self.session.checkpointer if self.session else None)
        self.log.info(f"Graph compilation complete")
        return compiled

    def _initialize_graph(self) -> None:
        self.log.info(f"Initializing graph and binding tools for: {self._name}")
        self.model = self.model.bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools) if self.tools else None
        self.graph = self._build_graph()


class LangGraphSession(BaseSession):
    """
    LangGraphSession class provides a session for LangGraph Agents SDK based agents.
    """

    def __init__(self, checkpointer:MemorySaver=None):
        """
        Initializes a LangGraphSession instance.
        """
        super().__init__(FRAMEWORK)
        self.checkpointer = checkpointer or MemorySaver()

    async def get_state(self) -> AgentState:
        """Retrieve full AgentState, loading messages from checkpoint."""
        tup = await self.checkpointer.aget_tuple(self._config())
        if tup is not None and tup.checkpoint.channel_values.get("messages") is not None:
            msgs = tuple(tup.checkpoint.channel_values["messages"])
        else:
            msgs = ()
        return AgentState(messages=msgs, handoff_to_agent=self._handoff)

    async def get_items(self, limit: Optional[int] = None) -> list[BaseMessage]:
        """
        Return list of BaseMessage in chronological order,
        optionally truncated to the most recent `limit` messages.
        """
        state = await self.get_state()
        if limit is None:
            return list(state["messages"])
        return list(state["messages"][-limit:])

    async def summarize_chat_history(self, previous_chat_history_summary:str):
        new_messages = await self.get_items(limit=5)
        # invoke llm to generate a new chat history summary by giving the previous summary and new messages
        pass


class LangGraphRunner(BaseRunner):
    """
    LangGraphRunner class provides a runner for LangGraph Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an LangGraphRunner instance.
        """
        self.thread_id = str(uuid.uuid4()) # Have to be replaced by the actual thread ID determined by the system
        super().__init__(FRAMEWORK)

    async def run(self, agent: LangGraphAgent, session: LangGraphSession, prompt: Any) -> Any:
        session_config = LangGraphSessionConfigModel(
            configurable=LangGraphSessionConfigurable(
                thread_id=session.id
            )
        )
        result = await agent.graph.ainvoke(input={"messages": [HumanMessage(content=prompt)]}, config=session_config.model_dump())
        last_message = result["messages"][-1]
        return last_message.content


class LangGraphModule(BaseModule):
    """
    LangGraphModule class provides a module for LangGraph Agent SDK based agents.
    """

    def __init__(self, agents: list[LangGraphAgent]):
        """
        Initializes a LangGraphModule instance.
        :param agents: List of agents in the module.
        """
        # runner = LangGraphRunner()
        super().__init__(agents=agents)
