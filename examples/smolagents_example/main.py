import os
import asyncio

try:
    from smolagents import CodeAgent, HfApiModel
except ImportError:
    print("Please install smolagents to run this example: pip install smolagents")
    exit(1)

from agentkernel.core.model import AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.smolagents import SmolagentsModule


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def main():
    # Create the native smolagents components
    model = HfApiModel()
    native_agent = CodeAgent(
        tools=[], 
        model=model,
        name="math_expert",
        description="I am a math expert. I can write and execute python code to solve math problems."
    )

    # 1. Compile into AgentKernel module
    module = SmolagentsModule(agents=[native_agent])

    # 2. Attach standard Python tools via AgentKernel ToolBuilder logic
    module.get_agent("math_expert").attach_tool(add)

    # 3. Create a standardized text request
    requests = [AgentRequestText(text="What is 15 + 27? Show your steps.")]
    
    print("Querying AgentKernel...")
    
    async def run_agent():
        # 4. Execute using the unified AgentKernel runtime
        reply = await Runtime.current().run("math_expert", module, requests)
        print("\nAgent Reply:")
        print(reply.text)

    asyncio.run(run_agent())


if __name__ == "__main__":
    main()
