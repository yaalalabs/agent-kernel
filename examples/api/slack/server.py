"""A Slack bot whose one risky tool has to be approved from the channel.

``needs_approval=True`` is the whole of the human-in-the-loop setup: the tool builder forwards it
to the OpenAI SDK, which stops before running the tool and hands the pending call back. Agent
Kernel turns that into a paused reply, and the Slack adapter posts it with an Approve and a Deny
button. The tool body runs only once somebody presses Approve.

Slack sends button presses to Interactivity & Shortcuts, not to Event Subscriptions. Point both at
the same ``/slack/events`` URL or the buttons will render and do nothing.
"""

from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.pipeline import IOHandler
from agentkernel.slack import SlackInboundAdapter
from agents import Agent as OpenAIAgent


def restart_service(name: str) -> str:
    """
    Restart a service.

    :param name: The service to restart, e.g. "checkout-api".
    :return: Confirmation of the restart.
    """
    return f"{name} was restarted."


general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions=(
        "You provide assistance with general queries. Give short and clear answers. "
        "You can also restart a service when someone asks you to."
    ),
    tools=OpenAIToolBuilder.bind([restart_service], needs_approval=True),
    model="openai/gpt-4.1-mini",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter())])
