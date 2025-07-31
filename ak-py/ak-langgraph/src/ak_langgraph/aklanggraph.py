from ak import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner

from typing import Any, Sequence, TypedDict, Annotated, Callable, List, Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from langchain_community.chat_models.litellm import ChatLiteLLM
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]

class LiteLLMModel(BaseModel):
    model_name: str
    temperature: float
    api_key: str

class StructuredLLMResponse(BaseModel):
    llm_response_message: str
    handoff_to_agent: Optional[str] = None

class LangGraphAgent(BaseAgent):
    def __init__(
        self, 
        name: str,
        description: str, 
        model: LiteLLMModel, 
        system_prompt: str, 
        runner: BaseRunner,
        tool_functions: List[Callable[..., Any]] = [], 
        handoffs: Optional[List['LangGraphAgent']] = None
    ):
        self.handoff_agents = {}
        if handoffs:
            for agent in handoffs:
                # Ensure each handoff agent is properly initialized
                if not hasattr(agent, 'graph') or agent.graph is None:
                    agent._initialize_graph()
                self.handoff_agents[agent.name] = agent
        self.description = description
        self.system_message = SystemMessage(content=self._build_system_prompt(system_prompt))
        self.model = ChatLiteLLM(model=model.model_name, temperature=model.temperature, api_key=model.api_key)
        self.tools = [
            StructuredTool.from_function(func=fn, name=fn.__name__, description=fn.__doc__)
            for fn in tool_functions
        ]
        super().__init__(name=name, runner=runner)
        self._initialize_graph()

    def _build_system_prompt(self, base_prompt: str) -> str:
        """Build system prompt with handoff instructions if handoffs are available"""
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
        messages = [self.system_message] + list(state["messages"])
        if self.handoff_agents:
            runnable = self.model.with_structured_output(StructuredLLMResponse)
            response: StructuredLLMResponse = runnable.invoke(messages)
            return {
                "messages": [response.llm_response_message],
                "handoff_to_agent": response.handoff_to_agent
            }
        else:
            response: BaseMessage = self.model.invoke(messages)
            return {"messages": [response]}

    def _select_next_node(self, state: AgentState) -> str:
        handoff = state.get("handoff_to_agent")
        if handoff and handoff in self.handoff_agents:
            return handoff
        return tools_condition(state)


    def _create_handoff_node(self, target_agent: 'LangGraphAgent'):
        """Create a handoff node function for a specific agent"""

        def handoff_node(state: AgentState) -> dict:
            # Execute the target agent with the current state
            result = target_agent.graph.invoke(state)
            return result[-1].content

        return handoff_node

    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(AgentState)
        
        # Add the main agent node
        graph.add_node(self._name, self._llm_call)
        
        # Add tool node if tools exist
        if self.tool_node:
            graph.add_node("tools", self.tool_node)
        
        # Add handoff agent nodes
        for agent_name, agent in self.handoff_agents.items():
            handoff_node = self._create_handoff_node(agent)
            graph.add_node(agent_name, handoff_node)
        
        # Build conditional edges mapping
        edge_mapping = {"__end__": END}
        
        # Add tools to edge mapping if available
        if self.tool_node:
            edge_mapping["tools"] = "tools"
        
        # Add handoff agents to edge mapping
        for agent_name in self.handoff_agents.keys():
            edge_mapping[agent_name] = agent_name
        
        # Add conditional edges from agent node
        graph.add_conditional_edges(
            self._name,
            self._select_next_node,
            edge_mapping
        )
        
        # Add edge from tools back to agent if tools exist
        if self.tool_node:
            graph.add_edge("tools", self._name)
        
        # Handoff nodes end the current agent's execution (no return edge)
        # This allows the handoff agent to complete the task
        for agent_name in self.handoff_agents.keys():
            graph.add_edge(agent_name, END)
        
        graph.set_entry_point(self._name)
        return graph.compile()

    def _initialize_graph(self) -> None:
        self.model = self.model.bind_tools(self.tools, tool_choice="auto")
        self.tool_node = ToolNode(self.tools) if self.tools else None
        self.graph = self._build_graph()


# class LangGraphAgent(BaseAgent):
#     """
#     LangGraphAgent class provides an agent wrapping for LangGraph Agent SDK based agents.
#     """

#     def __init__(self, name: str, runner: LangGraphRunner, agent: LangGraphBaseAgent):
#         """
#         Initializes an LangGraphAgent instance.
#         :param name: Name of the agent.
#         :param runner: Runner associated with the agent.
#         :param agent: The LangGraph agent instance.
#         """
#         super().__init__(name, runner)
#         self._agent = agent

#     @property
#     def agent(self) -> LangGraphBaseAgent:
#         """
#         Returns the LangGraph agent instance.
#         """
#         return self._agent


class LangGraphRunner(BaseRunner):
    """
    LangGraphRunner class provides a runner for LangGraph Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an LangGraphRunner instance.
        """
        super().__init__("langgraph")

    async def run(self, agent: LangGraphAgent, prompt: Any) -> Any:
        result = await agent.graph.ainvoke({"messages": [HumanMessage(content=prompt)]})
        last_message = result[-1]
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
