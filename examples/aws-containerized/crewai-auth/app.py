from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule
from agentkernel.secret import SecretManager
from crewai import LLM, Agent
from fastapi import APIRouter

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the CrewAI LLM in memory; it is never written back to os.environ.
openai_key = SecretManager.current().get("OPENAI_API_KEY")

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
    llm=LLM(model="openai/gpt-4.1-mini", api_key=openai_key),
)

history_agent = Agent(
    role="history",
    goal="Specialist agent for historical questions",
    backstory="You provide assistance with historical queries. Explain important events and context clearly.",
    verbose=False,
    llm=LLM(model="openai/gpt-4.1-mini", api_key=openai_key),
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
