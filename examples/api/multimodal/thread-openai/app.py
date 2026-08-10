from typing import Optional

from agentkernel.api import RESTAPI
from agentkernel.core.thread import Authoriser
from agentkernel.thread import AgentThreadRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent

general_agent = Agent(
    name="general",
    instructions="You provide assistance with general queries. Give short and clear answers",
)


class DemoAuthoriser(Authoriser):
    """
    Demo Authoriser protecting the thread read endpoints (GET /api/v1/threads*).

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


OpenAIModule([general_agent])

if __name__ == "__main__":
    # Mounting AgentThreadRequestHandler (instead of the default handler) is what
    # enables Conversation Thread Support: it serves the standard chat routes with
    # thread recording plus the thread read routes. The `thread` block in
    # config.yaml only selects the store backend and naming.
    RESTAPI.run(handlers=[AgentThreadRequestHandler(authoriser=DemoAuthoriser())])
