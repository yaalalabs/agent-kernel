"""A Slack bot whose risky tool has to be approved from the channel.

``requires_approval=True`` is the gate: Pydantic AI stops before running the tool and hands the
pending call back as a ``DeferredToolRequests`` output, which is why the agent has to declare that
among its output types. Agent Kernel turns it into a paused reply and the Slack adapter posts each
question with its own Approve and Deny buttons.

Pydantic AI will not resume a run that leaves any gated call unanswered, so a turn gating several
calls is posted as questions plus one *Review all* button, which opens a modal collecting every
answer under one Submit. Ask to restart two services to see that path.

Slack sends button presses and modal submissions to Interactivity & Shortcuts, not to Event
Subscriptions. Point both at the same ``/slack/events`` URL or they will render and do nothing.
"""

from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.pipeline import IOHandler
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder
from agentkernel.slack import SlackInboundAdapter
from pydantic_ai import Agent, DeferredToolRequests


def restart_service(name: str) -> str:
    """
    Restart a service.

    :param name: The service to restart, e.g. "checkout-api".
    :return: Confirmation of the restart.
    """
    return f"{name} was restarted (simulated)."


MODEL = "openai:gpt-4.1-mini"

general_agent = Agent(
    model=MODEL,
    name="general",
    description="Agent for general questions",
    output_type=[str, DeferredToolRequests],
    instructions=(
        "You provide assistance with general queries. Give short and clear answers. You can also "
        "restart services. When someone names more than one service, call the restart tool once "
        "for each of them in the same turn, so they are all approved together."
    ),
    tools=PydanticAIToolBuilder.bind([restart_service], requires_approval=True),
)

PydanticAIModule([general_agent])


if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter())])
