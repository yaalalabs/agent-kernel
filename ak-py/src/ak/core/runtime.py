from importlib import import_module
from logging import getLogger
from typing import Any

from .base import Agent, Session

class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    _log = getLogger("ak.runtime")
    _agents = {}

    @staticmethod
    def load(module):
        """
        Loads an agent module dynamically.
        :param module: Name of the module to load.
        :return: The loaded module.
        """
        Runtime._log.debug(f"Loading module '{module}'")
        return import_module(module)

    @staticmethod
    def register(agent: Agent):
        """
        Registers an agent in the runtime.
        :param agent: The agent to register.
        """
        if not Runtime._agents.get(agent.name):
            Runtime._log.debug(f"Registering agent '{agent.name}'")
            Runtime._agents[agent.name] = agent
        else:
            Runtime._log.warning(f"Agent with name '{agent.name}' is already registered.")

    @staticmethod
    def agents() -> dict[str, Agent]:
        """
        Returns the list of registered agents.
        :return: List of agents.
        """
        return Runtime._agents

    @staticmethod
    async def run(agent: Agent, session: Session, prompt: Any) -> Any:
        """
        Runs the specified agent with the given prompt.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        Runtime._log.debug(f"Running agent '{agent.name}' with prompt: {prompt}")
        return await agent.runner.run(agent, session, prompt)
