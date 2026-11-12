from agentkernel.aws import AWSWebsocketAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Do not provide reasoning or step-by-step explanations. Just give the final answer. \
         If prompted for anything else, refuse to answer.",
    model="openai/gpt-4.1-mini",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
    model="openai/gpt-4.1-mini",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    model="openai/gpt-4.1-mini",
    handoffs=[history_agent, math_agent],
)

OpenAIModule([triage_agent, math_agent, history_agent])


# Custom routes receive the frame's raw body and the connection's principal: the identity the
# $connect handshake authenticated through the identity provider in config.yaml.
@AWSWebsocketAPI.register("status")  # Terraform: ws_routes = [{ route = "status" }]
async def status(ctx: dict) -> dict:
    return {"status": "OK", "subject": ctx["principal"].subject}


@AWSWebsocketAPI.register("echo")  # Terraform: ws_routes = [{ route = "echo" }]
async def echo(ctx: dict) -> dict:
    return {"message": ctx["message"], "principal": ctx["principal"].model_dump(mode="json", exclude_none=True)}


def main():
    # The $connect handshake validates its `?token=` query parameter through the identity block
    # in config.yaml; without that block the WebSocket API refuses to start.
    AWSWebsocketAPI.run()


if __name__ == "__main__":
    main()
