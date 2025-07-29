from typing import Any
from crewai import Agent, Crew, Task

from ak import Agent as BaseAgent, Module as BaseModule, Runner as BaseRunner

class CrewAIRunner(BaseRunner):
    """
    CrewAIRunner class provides a runner for CrewAI based agents.
    """

    def __init__(self):     
        """
        Initializes a CrewAIRunner instance.
        """
        super().__init__("crewai")

    async def run(self, agent: Any, prompt: Any) -> Any:
        """
        Runs the CrewAI agent with the provided prompt.
        :param agent: The CrewAI agent to run.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        task = Task(description=prompt, expected_output="An answer is plain text", agent=agent.agent)
        crew = Crew(agents=[agent.agent], tasks=[task], verbose=False)
        return crew.kickoff(inputs={"topic": "France"})

class CrewAIAgent(BaseAgent):
    """
    CrewAIAgent class provides an agent wrapping for CrewAI based agents.
    """

    def __init__(self, name: str, runner: CrewAIRunner, agent: Agent):
        """
        Initializes a CrewAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The CrewAI agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

    @property
    def agent(self) -> Agent:
        """
        Returns the CrewAI agent instance.
        """
        return self._agent

class CrewAIModule(BaseModule):
    """
    CrewAIModule class provides a module for CrewAI based agents.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes a CrewAIModule instance.
        :param agents: List of agents in the module.
        """
        runner = CrewAIRunner()
        super().__init__(list(map(lambda agent: CrewAIAgent(agent.role, runner, agent), agents)))
