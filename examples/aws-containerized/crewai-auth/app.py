from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule
from crewai import Agent
from fastapi import APIRouter

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
    llm="openai/gpt-4.1-mini",
)

history_agent = Agent(
    role="history",
    goal="Specialist agent for historical questions",
    backstory="You provide assistance with historical queries. Explain important events and context clearly.",
    verbose=False,
    llm="openai/gpt-4.1-mini",
)

router = APIRouter()


# Adding a custom route
# Example custom route to support application-specific endpoints.
# All custom routes are prefixed with "/custom" by default. Refer to the config documentation for more details.
# Custom routes run the identity dependency too: a token, if sent, must be valid (a refused one is a
# 401); without one the route runs as the anonymous principal.
@router.get("/version")
def get_app_name():
    return {"name": "my_custom_app", "version": "1.0.0"}


RESTAPI.add(router)


CrewAIModule([math_agent, history_agent])


def main():
    # Authentication is configuration, not code: the `identity` block in config.yaml names the
    # provider every route authenticates the bearer token with (the static provider here; swap it
    # for oidc, cognito, entra or firebase to validate real tokens).
    RESTAPI.run()


if __name__ == "__main__":
    main()
