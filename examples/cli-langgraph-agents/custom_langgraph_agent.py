from typing import Any, Sequence, TypedDict, Annotated, Callable, List
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "add_messages"]

class CustomLangGraphAgent:
    def __init__(
        self,
        name: str,
        description: str,
        model: ChatOpenAI,
        system_prompt: str,
        tool_functions: List[Callable[..., Any]] = [],
        checkpointer: MemorySaver = None,
        verbose: bool = False
    ):
        self.name = name
        self.description = description
        self.verbose = verbose

        self.system_message = SystemMessage(content=system_prompt)
        self.model = model

        self.tools = [
            StructuredTool.from_function(func=fn, name=fn.__name__, description=fn.__doc__)
            if not isinstance(fn, BaseTool) else fn
            for fn in tool_functions
        ]

        self.checkpointer = checkpointer
        self._initialize_graph()

    def _log(self, *args, force: bool = False, **kwargs):
        if self.verbose or force:
            print(*args, **kwargs)

    def _llm_call(self, state: AgentState) -> dict:
        messages = [self.system_message] + list(state["messages"])
        self._log("Invoking LLM with messages:", messages)
        response: BaseMessage = self.model.invoke(messages)
        self._log("LLM Response:", response)
        return {"messages": [response]}

    def _build_graph(self) -> CompiledStateGraph:
        self._log(f"Building graph for agent: {self.name}")
        graph = StateGraph(AgentState)

        graph.add_node(self.name, self._llm_call)

        if self.tool_node:
            graph.add_node("tools", self.tool_node)
            graph.add_edge("tools", self.name)
            graph.add_conditional_edges(self.name, tools_condition, {"tools": "tools", "__end__": END})
        else:
            graph.add_edge(self.name, END)

        graph.set_entry_point(self.name)

        compiled = graph.compile(name=self.name, checkpointer=self.checkpointer)
        self._log("Graph compilation complete")
        return compiled

    def _initialize_graph(self):
        self._log(f"Initializing graph and binding tools for: {self.name}")
        self.model = self.model.bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools) if self.tools else None
        self.graph = self._build_graph()