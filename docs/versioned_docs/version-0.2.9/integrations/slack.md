# Slack

The Slack integration allows you to deploy Agent Kernel agents as Slack bots that can respond to mentions and direct messages within Slack workspaces. This integration uses the Slack Events HTTP API to provide real-time conversational AI capabilities.

## Overview

The `AgentSlackRequestHandler` class handles simple conversations with agents of your choice in API deployments. The integration provides the following workflow:

1. **Message Reception**: When a message is received from Slack addressed to the bot, it first acknowledges with a configurable message and processing emoji
2. **Question Processing**: The question is extracted and passed to your chosen agent
3. **Response Update**: Once the agent response is ready, the previously posted acknowledgment message is modified
4. **Thread Response**: The final response is posted to the conversation thread

## Features

- **Real-time Responses**: Immediate acknowledgment with processing indicators
- **Thread Support**: Responses are posted in organized conversation threads
- **Flexible Agent Routing**: Route different types of questions to specialized agents
- **Emoji Indicators**: Visual feedback during processing
- **Webhook Challenge Handling**: Automatic handling of Slack's URL verification process

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

### 3. Configure OAuth Scopes

The following OAuth scopes are required for the bot to function properly:

**Bot Token Scopes:**
- `chat:write` - Post messages as the bot
- `im:write` - Write direct messages
- `channels:read` - Read channel information
- `groups:read` - Read private channel information
- `im:read` - Read direct message history
- `mpim:read` - Read multi-party direct messages

Additional scopes may be automatically added when you subscribe to events.

### 4. Install App to Workspace

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

The `AgentSlackRequestHandler` listens on the `/slack/events` endpoint. Configure your Slack app's Event Request URL as:

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
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.slack import AgentSlackRequestHandler

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
    handler = AgentSlackRequestHandler()
    RESTAPI.run(handler=handler)
```

## Configuration Options

### Custom Acknowledgment Messages and Agent
You can configure which Agent will answer the Slack integration in a multi agent mode.
You can customize the acknowledgment message and processing emoji through configuration:

```python
# Custom configuration in config.yaml
slack:
  agent_acknowledgement: "🤖 Processing your request..."
  agent: "general"
```


## Custom Request Handler

For more advanced Slack integrations, you can extend the `RESTRequestHandler` class. Please study the **AgentSlackRequestHandler** implementation.


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

**Event delivery issues:**
- Check your webhook URL is accessible from the internet
- Verify the signing secret is correctly set
- Monitor server logs for incoming requests


## Example Projects

Complete working examples are available in the **examples/api/slack** directory.