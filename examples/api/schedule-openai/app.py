from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

assistant_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
)

# Nothing here mentions scheduling: the `schedule` block in config.yaml is what enables the
# capability, and Agent Kernel injects the scheduling tools and their guidance into every agent's
# system prompt. The agent can therefore defer work on its own (create_schedule and friends),
# while a client can defer a chat request directly by sending a `schedule` block with it.
OpenAIModule([assistant_agent])

if __name__ == "__main__":
    # config.yaml selects the in_memory queue transport, so this single call boots the whole
    # single-process pipeline — and, because a `schedule` block is present, it also mounts the
    # schedule management routes (GET/PUT/DELETE /api/v1/schedules). To protect those routes with
    # your own Authoriser, call IOHandler.run(authoriser=MyAuthoriser()) instead.
    RESTAPI.run()
