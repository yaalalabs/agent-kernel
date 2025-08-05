from typing import Any, Sequence, TypedDict, Annotated, Callable, List, Optional, Union
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


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    handoff_to_agent: Optional[str]

class LiteLLMModel(BaseModel):
    model_name: str
    temperature: float
    api_key: str

class StructuredLLMResponse(BaseModel):
    llm_response_message: str
    handoff_to_agent: Optional[str] = None


class LangGraphAgent:
    def __init__(
        self, 
        name: str,
        description: str, 
        model: LiteLLMModel, 
        system_prompt: str, 
        tool_functions: List[Callable[..., Any]] = [], 
        handoffs: Optional[List['LangGraphAgent']] = None,
        checkpointer: Optional[MemorySaver] = None
    ):
        self.name = name
        self.handoff_agents = {}
        if handoffs:
            for agent in handoffs:
                if not isinstance(agent, CompiledStateGraph) and (not hasattr(agent, 'graph') or agent.graph is None):
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
        self.checkpointer = checkpointer
        self._initialize_graph()

    def _build_system_prompt(self, base_prompt: str) -> str:
        if not self.handoff_agents:
            return base_prompt

        handoff_prompt = f"""

HANDOFF CAPABILITIES:
You can transfer control to the following specialized agents:
{chr(10).join([f"- {name}: {getattr(agent, 'description', 'No description available')}" for name, agent in self.handoff_agents.items()])}

Respond in JSON with keys:
- "llm_response_message": your response to the user
- optional "handoff_to_agent": one of [{', '.join(self.handoff_agents.keys())}]

Only use handoffs when the task genuinely requires the other agent's specialized capabilities."""
        
        return base_prompt + handoff_prompt

    def _llm_call(self, state: AgentState) -> dict:
        """Call the LLM with optional handoff processing."""
        messages = [self.system_message] + list(state["messages"])
        use_handoff = bool(self.handoff_agents)
        print(f"Invoking LLM {'with' if use_handoff else 'without'} handoff... Input State: {state}")
        response: BaseMessage = self.model.invoke(messages)
        print(f"LLM {'with' if use_handoff else 'without'} handoff... Response Type: {response.type}, Response: {response}")
        if use_handoff and response.content:
            try:
                response_dict = parse_json_markdown(response.content)
                structured_response = StructuredLLMResponse.model_validate(response_dict)
                tool_calls = response.additional_kwargs.get("tool_calls", [])

                print(f"Parsed LLM response with handoff check: {response_dict}")
                return {
                    "messages": [AIMessage(content=structured_response.llm_response_message, metadata={"agent_name": self.name}, 
                                           additional_kwargs={"tool_calls": tool_calls} if tool_calls else {})],
                    "handoff_to_agent": structured_response.handoff_to_agent
                }
            except Exception as e:
                print(f"Error parsing LLM response therefore returning raw response. ERROR: {e}")
        print("Returning raw response without handoff processing")
        return {"messages": [response]}


    def _select_next_node(self, state: AgentState) -> str:
        handoff = state.get("handoff_to_agent")
        print(f"Selecting next node, handoff requested: {handoff}")
        if handoff and handoff in self.handoff_agents:
            print(f"Valid handoff to agent: {handoff}")
            return handoff
        elif handoff:
            print(f"WARNING: Invalid handoff requested to '{handoff}', available agents: {list(self.handoff_agents.keys())}")
        return tools_condition(state)

    def _create_handoff_node(self, target_agent: Union['LangGraphAgent', CompiledStateGraph]):
        target_agent = target_agent.graph if isinstance(target_agent, LangGraphAgent) else target_agent
        def handoff_node(state: AgentState) -> dict:
            state_for_handoff_node = {"messages": state["messages"][:-1], "handoff_to_agent": None}
            print(f"Executing handoff to agent: {target_agent.name}")
            result = target_agent.invoke(state_for_handoff_node)["messages"][-1]
            print(f"Result from handoff agent '{target_agent.name}': {result}")
            return {"messages": result, "handoff_to_agent": None}
        return handoff_node

    def _build_graph(self) -> CompiledStateGraph:
        print(f"Building graph for agent: {self.name}")
        graph = StateGraph(AgentState)

        print(f"Adding main LLM call node: {self.name}")
        graph.add_node(self.name, self._llm_call)

        if self.tool_node:
            print(f"Adding tools node")
            graph.add_node("tools", self.tool_node)

        for agent_name, agent in self.handoff_agents.items():
            print(f"Adding handoff node for agent: {agent_name}")
            graph.add_node(agent_name, self._create_handoff_node(agent))

        edge_mapping = {"__end__": END}

        if self.tool_node:
            print("Adding tools to edge mapping")
            edge_mapping["tools"] = "tools"

        for agent_name in self.handoff_agents.keys():
            print(f"Adding '{agent_name}' to edge mapping")
            edge_mapping[agent_name] = agent_name

        print(f"Adding conditional edges from main node EDGE MAPPING: {edge_mapping}")
        graph.add_conditional_edges(
            self.name,
            self._select_next_node,
            edge_mapping
        )

        if self.tool_node:
            print(f"Adding edge from tools back to main node")
            graph.add_edge("tools", self.name)

        for agent_name in self.handoff_agents.keys():
            print(f"Adding edge from handoff agent '{agent_name}' to END")
            graph.add_edge(agent_name, END)

        print(f"Setting entry point: {self.name}")
        graph.set_entry_point(self.name)
        compiled = graph.compile(name=self.name, checkpointer=self.checkpointer)
        print(f"Graph compilation complete")
        return compiled

    def _initialize_graph(self) -> None:
        print(f"Initializing graph and binding tools for: {self.name}")
        self.model = self.model.bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools) if self.tools else None
        self.graph = self._build_graph()