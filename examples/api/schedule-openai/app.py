from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agentkernel.schedule import ScheduleRESTRequestHandler
from agents import Agent

assistant_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
)

# The agent itself says nothing about scheduling: the `schedule` block in config.yaml is what
# enables the capability, and Agent Kernel injects the scheduling tools and their guidance into
# every agent's system prompt. The agent can therefore defer work on its own (create_schedule and
# friends), while a client can defer a chat request directly by sending a `schedule` block with it.
OpenAIModule([assistant_agent])

if __name__ == "__main__":
    # config.yaml selects the in_memory queue transport, so this call boots the whole
    # single-process pipeline. The schedule management routes (GET/PUT/DELETE /api/v1/schedules)
    # are mounted by the app, the way a Slack handler is: pass
    # ScheduleRESTRequestHandler(authoriser=MyAuthoriser()) to protect them with your own
    # Authoriser. Deferring and the agent tools work without mounting anything.
    IOHandler.run(handlers=[ScheduleRESTRequestHandler()])
