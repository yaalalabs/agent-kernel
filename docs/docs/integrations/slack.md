# Slack

The Slack integration allows you to deploy Agent Kernel agents as Slack bots that can respond to mentions and direct messages within Slack workspaces. This integration uses the Slack Events HTTP API to provide real-time conversational AI capabilities.

## Overview

The `SlackInboundAdapter` class handles simple conversations with agents of your choice in API deployments. The integration provides the following workflow:

1. **Message Reception**: When a message is received from Slack addressed to the bot, it will first acknowledge with a message ("agent_acknowledgement") and processing emoji, if it's defined in the config
2. **Question Processing**: The question is extracted and passed to your chosen agent
3. **Response Update**: Once the agent response is ready, the previously posted message is modified
4. **Thread Response**: The response is posted to the thread

## Features

- **Real-time Responses**: Immediate acknowledgment with processing indicators
- **Thread Support**: Responses are posted in organized conversation threads
- **File and Image Support**: Process text messages, images, and document files
- **File Size Validation**: Automatic validation and rejection of oversized files
- **Media Type Filtering**: Rejects audio/video files that cannot be processed
- **Webhook Challenge Handling**: Automatic handling of Slack's URL verification process
- **Approvals in the Channel**: A run that pauses for a human arrives as a message with Approve and Deny buttons

:::info Current Limitation
Currently, passed images and files are not added to the chat history. So all questions have to be asked with the message sent along with the attachments. Follow up questions, which require re-analysis of the file/image cannot be answered by the LLM.

Please read the [following](https://github.com/yaalalabs/agent-kernel/tree/develop/docs/docs/api/rest-api.md) on how to handle this properly without exhausting the token limits.
:::

## Slack App Setup

### 1. Create a Slack App

1. Go to [Slack API Apps](https://api.slack.com/apps/)
2. Click "Create New App"
3. Choose "From scratch" and provide an app name and workspace

### 2. Configure Event Subscriptions

Enable the following event subscriptions in your Slack app:

- `message.im` - Direct messages to the bot
- `message.channels` - Channel messages mentioning the bot  
- `app_mention` - When the bot is mentioned with @

### 3. Enable Interactivity

Button presses do not arrive over Event Subscriptions. If you want
[approvals in the channel](#approving-a-paused-run), turn on **Interactivity & Shortcuts** and set
its Request URL to the **same** URL as your event subscription:

```
https://your-domain.com:port/slack/events
```

One endpoint serves both: Slack's Bolt SDK dispatches events and interactivity payloads through the
same handler, so there is no second route to mount and no extra scope to grant. Leave this off and a
pause still renders — the buttons appear and nothing happens when they are pressed.

### 4. Configure OAuth Scopes

When you subscribe to events, some OAuth scopes are automatically added. In addition to that, these minimum scopes need to be added for the bot to function. These can be set up in "OAuth & Permissions":

**Bot Token Scopes:**
- `chat:write` - Post messages as the bot
- `im:write` - Write direct messages
- `files:read` - Read uploaded files
- `app_mentions:read` - Read app mentions

### 5. Install App to Workspace

After configuring scopes and events, install the app to your workspace to generate the bot token.

## Environment Configuration

Set the following environment variables for the integration:

```bash
export SLACK_SIGNING_SECRET=your_slack_signing_secret
export SLACK_BOT_TOKEN=xoxb-your-bot-token
```

### Getting Credentials

- **Signing Secret**: Found in your Slack app settings under "Basic Information" → "App Credentials"
- **Bot Token**: Found under "OAuth & Permissions" → "Bot User OAuth Token" (starts with `xoxb-`)

## Webhook URL Setup
The integration automatically handles Slack's URL verification challenge. When you first configure the webhook URL, Slack will send a verification request that the handler processes automatically.

The `SlackInboundAdapter` listens on the `/slack/events` endpoint. Configure your Slack app's Event Request URL as:

```
https://your-domain.com:port/slack/events
```

### Local Development

For local testing, you can use tunneling services like [pinggy.io](https://pinggy.io/):

```bash
# Example using pinggy
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

Then use the provided URL in your Slack app configuration. See [How to use pinggy to test Slack](https://pinggy.io/blog/how_to_get_slack_webhook/) for detailed instructions.

## Implementation

### Basic Integration

Here's a simple example of setting up a Slack integration:

```python
from agents import Agent as OpenAIAgent
from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.pipeline import IOHandler
from agentkernel.openai import OpenAIModule
from agentkernel.slack import SlackInboundAdapter

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

# Initialize the OpenAI module with your agent
OpenAIModule([general_agent])

# Create and run the server with Slack handler
if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter())])
```


:::note Mounting
Integrations run on the queue execution pipeline, so they are mounted with `IOHandler.run(...)`
rather than `RESTAPI.run(...)`. The webhook answers as soon as the message is queued; the agent
runs behind it, so a slow model call can no longer become a platform delivery timeout.
:::

:::caution Attachments need multimodal storage
Attachment bytes are stored before the request is queued, so a message carrying an image or a file
requires `multimodal.enabled: true` with a shared `storage_type` (`in_memory`, `redis` or
`dynamodb`). `session_cache` is rejected: the agent runs in a different process and would never
see it.
:::

## Approving a Paused Run

When an agent stops to ask a human — a gated tool, a confirmation — the pause is posted to the same
conversation with a row of buttons per question that needs a yes or no:

```
⏸ Approval needed

refund_order
  order_id: A-10294

[ Approve ]  [ Deny ]

refund_order
  order_id: B-20571

[ Approve ]  [ Deny ]

This run is paused until someone approves it.
```

Each question carries its own controls, directly beneath it, so there is nothing to match up by
eye and nothing to number.

**Deny opens a modal** that asks for an optional reason, which reaches the agent as the decision's
message, so the model can tell the customer *why* rather than just *no*. Approve sends straight
through.

Nothing is configured for this. A press parses into exactly the decision a REST client would send
and travels the same queue, so the agent cannot tell the two apart. See
[Human in the Loop](../advanced/human-in-the-loop.md) for the full picture, including the one kind of question that gets no buttons: one asking for a value rather than a verdict.

:::caution Anyone who can see the message can press it
Agent Kernel ships no approver policy. Channel membership is not an approval list — if it matters
who decides, enforce it yourself: the presser's Slack user id reaches the run as `acting_user_id`,
and a `PreHook` is where you check it.
:::

The buttons stay on the message after a decision. Pressing the same one again is deduplicated and
changes nothing; pressing one on a pause that has already been answered gets the usual error reply.

## Configuration Options

### Custom Acknowledgment Messages and Agent

You can configure which agent will handle Slack messages and customize the acknowledgment message:

```yaml
# Configuration in config.yaml
slack:
  agent: "general"  # Name of the agent to handle messages
  agent_acknowledgement: "🤖 Processing your request..."  # Optional
```

**Note**: It's strongly recommended to set credentials as environment variables rather than in config files.

## Custom Request Handler

For more advanced Slack integrations, you can extend the `RESTRequestHandler` class. Please study the **SlackInboundAdapter** implementation.


## Troubleshooting

### Common Issues

**Bot not responding to messages:**
- Verify your bot token is correct and starts with `xoxb-`
- Check that the bot is added to the channel or workspace
- Ensure required OAuth scopes are granted

**SSL/HTTPS errors:**
- Slack requires HTTPS endpoints for production
- Use a reverse proxy like nginx for SSL termination
- For development, use tunneling services that provide HTTPS

**Buttons appear but pressing them does nothing:**
- Enable **Interactivity & Shortcuts** and set its Request URL to your `/slack/events` URL
- Check the server logs: an interactivity payload reaching the endpoint is logged like any event

**Event delivery issues:**
- Check your webhook URL is accessible from the internet
- Verify the signing secret is correctly set
- Monitor server logs for incoming requests


## Example Projects

Complete working examples are available in the **examples/api/slack** directory.