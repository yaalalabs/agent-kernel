"""Request-handler Lambda: the chat route plus Slack's Events API webhook.

LambdaWebhookHost hosts the same WebhookRESTRequestHandler an app passes to the pipeline's
IOHandler.run. It verifies the Slack signature, acknowledges the message ("thinking..."), and
enqueues it with its return address; the agent runs behind the Input Queue, so Slack gets its 200
well inside its 3-second deadline.

Building the host runs its checks on cold start: rest_sync/rest_async mode, the sqs transport, the
API_BASE_PATH/API_VERSION/AGENT_ENDPOINT variables Terraform sets, and the adapter's verification
secret. A deployment that could not work fails its init instead of dropping deliveries.
"""

from agentkernel.aws import Lambda, LambdaWebhookHost
from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.slack import SlackInboundAdapter

slack = LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter()))


@Lambda.register("/slack/events", method="POST")
def slack_events(event, context):
    return slack.handle(event, context)


handler = Lambda.handler
