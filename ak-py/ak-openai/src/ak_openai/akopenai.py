from typing import Any
from agents import Agent, Runner

from ak import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner

class OpenAIRunner(BaseRunner):
    """
    OpenAIRunner class provides a runner for OpenAI Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAIRunner instance.
        """
        super().__init__("openai")

    async def run(self, agent: Any, prompt: Any) -> Any:
        result = await Runner.run(agent.agent, prompt)
        return result.final_output

class OpenAIAgent(BaseAgent):
    """
    OpenAIAgent class provides an agent wrapping for OpenAI Agent SDK based agents.
    """

    def __init__(self, name: str, runner: OpenAIRunner, agent: Agent):
        """
        Initializes an OpenAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The OpenAI agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

    @property
    def agent(self) -> Agent:
        """
        Returns the OpenAI agent instance.
        """
        return self._agent

class OpenAIModule(BaseModule):
    """
    OpenAIModule class provides a module for OpenAI Agent SDK based agents.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes a OpenAIModule instance.
        :param agents: List of agents in the module.
        """
        runner = OpenAIRunner()
        super().__init__(list(map(lambda agent: OpenAIAgent(agent.name, runner, agent), agents)))
