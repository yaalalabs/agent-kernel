"""
Example demonstrating framework-agnostic tool functions with ToolContext.

This example shows how to write tool functions that can access the runtime context
including the session, agent, and other execution details.
"""

from agentkernel import Runtime, Session
from agentkernel.core.model import AgentRequestText
from agentkernel.core.tool import ToolContext


# Example 1: Simple tool without context
def calculate_sum(a: int, b: int) -> int:
    """
    A simple tool that doesn't need access to the runtime context.
    This tool can be used as-is with any framework.
    """
    return a + b


# Example 2: Tool that uses ToolContext
def get_session_info(ctx: ToolContext) -> dict:
    """
    A tool that uses ToolContext to access runtime information.
    This tool will automatically receive the context when bound with a ToolBuilder.
    """
    return {
        "session_id": ctx.session.id,
        "agent_name": ctx.agent.name,
        "runtime_type": type(ctx.runtime).__name__,
        "request_count": len(ctx.requests),
    }


# Example 3: Tool with mixed parameters
def process_with_context(ctx: ToolContext, user_input: str, multiplier: int = 1) -> str:
    """
    A tool that uses both ToolContext and regular parameters.
    The context is automatically injected while regular parameters are passed normally.
    """
    session_data = f"Session {ctx.session.id}"
    processed = f"{session_data}: {user_input}" * multiplier
    return processed


# Example 4: Async tool with context
async def async_process(ctx: ToolContext, value: int) -> dict:
    """
    An async tool that uses ToolContext.
    Tool builders support both sync and async functions.
    """
    # Access session cache
    cache = ctx.session.get_volatile_cache()
    
    # Store or retrieve some data
    count_key = "process_count"
    current_count = cache.get(count_key) or 0
    new_count = current_count + 1
    cache.set(count_key, new_count)
    
    return {
        "value": value,
        "agent": ctx.agent.name,
        "call_count": new_count,
    }


# Example usage with a framework (pseudo-code):
# 
# For OpenAI Agents SDK:
# from agentkernel.framework.openai import OpenAIToolBuilder
# from agents import Agent
#
# weather_agent = Agent(
#     name="WeatherAgent",
#     instructions="You provide weather information.",
#     tools=OpenAIToolBuilder.bind(
#         [get_session_info, process_with_context],
#         runtime=Runtime.current(),
#         session=my_session,
#         agent=weather_agent,
#         requests=[],
#         params={}
#     ),
# )
#
# For Google ADK:
# from agentkernel.framework.adk import ADKToolBuilder
# from google.adk.agents import Agent
#
# # ADK automatically gets context from get_current_context()
# weather_agent = Agent(
#     name="WeatherAgent",
#     model="gemini-2.0-flash-exp",
#     instruction="You provide weather information.",
#     functions=ADKToolBuilder.bind([get_session_info, process_with_context]),
# )


if __name__ == "__main__":
    print("Framework-agnostic Tool Example")
    print("=" * 50)
    
    # Demonstrate tool usage without framework
    print("\n1. Simple tool without context:")
    result = calculate_sum(5, 3)
    print(f"   calculate_sum(5, 3) = {result}")
    
    print("\n2. Tool with ToolContext (direct call for demo):")
    # Create mock context for demonstration
    from agentkernel import Agent, Runner
    from agentkernel.core.base import Session
    
    class MockRunner(Runner):
        async def run(self, agent, session, requests):
            pass
    
    class MockAgent(Agent):
        def __init__(self, name):
            super().__init__(name, MockRunner("mock"))
        
        def get_description(self):
            return "Mock agent"
        
        def get_a2a_card(self):
            return None
    
    runtime = Runtime.current()
    session = Session("demo-session-123")
    agent = MockAgent("demo-agent")
    requests = [AgentRequestText(text="test")]
    
    ctx = ToolContext(
        runtime=runtime,
        session=session,
        agent=agent,
        requests=requests,
        params={"example": "value"}
    )
    
    result = get_session_info(ctx=ctx)
    print(f"   Session info: {result}")
    
    print("\n3. Tool with mixed parameters:")
    result = process_with_context(ctx=ctx, user_input="Hello", multiplier=2)
    print(f"   Result: {result}")
    
    print("\n4. Async tool (would need async execution):")
    print("   async_process requires async execution context")
    
    print("\nNote: In actual usage, the ToolContext is automatically injected")
    print("by the framework-specific ToolBuilder when the tool is bound to an agent.")
