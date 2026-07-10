from typing import Optional

from agentkernel.api import AgentRESTRequestHandler, RESTAPI, ThreadRESTRequestHandler
from agentkernel.core.thread import Authoriser
from agentkernel.openai import OpenAIModule
from agents import Agent

assistant_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
)


class DemoAuthoriser(Authoriser):
    """
    Demo Authoriser protecting the thread read endpoints (GET /threads*).

    A real subclass would validate the Bearer token against your own authentication
    provider (e.g. verify a JWT signature) and return the subject's user_id, or None
    to reject the request. Here a static token map stands in for that provider.
    """

    _TOKENS = {
        "alice-token": "alice",
        "bob-token": "bob",
    }

    def authorise(self, token: str) -> Optional[str]:
        return self._TOKENS.get(token)


OpenAIModule([assistant_agent])

if __name__ == "__main__":
    # Passing a ThreadRESTRequestHandler explicitly replaces the default open
    # (unauthorised) thread routes that Agent Kernel would otherwise mount
    # automatically when a `thread` block is present in config.yaml.
    RESTAPI.run(handlers=[AgentRESTRequestHandler(), ThreadRESTRequestHandler(authoriser=DemoAuthoriser())])
