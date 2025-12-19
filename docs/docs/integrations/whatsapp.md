# WhatsApp

The WhatsApp integration allows you to deploy Agent Kernel agents as WhatsApp bots that can respond to messages via the WhatsApp Business API. This integration uses the WhatsApp Cloud API webhooks to provide real-time conversational AI capabilities.

## Overview

The `AgentWhatsAppRequestHandler` class handles conversations with agents via WhatsApp Business API webhooks. This integration uses the WhatsApp Cloud API without requiring third-party libraries beyond standard HTTP clients.

## How It Works

1. When a message is received from WhatsApp, it's verified and authenticated
2. An optional acknowledgement message is sent to the user
3. The question is extracted and passed to your chosen Agent
4. The Agent response is sent back as a WhatsApp message
5. Long messages are automatically split to respect WhatsApp's character limits

## Features

### Supported Message Types

- **Text Messages**: Standard text messages
- **Interactive Messages**: Button and list replies
- **Media Messages**: Image, documents

:::info Current Limitation
Currently, passed images and files are not added to the chat history. So all questions have to be asked with the caption sent along with the attachments. Follow up questions, which require re-analysis of the file/image cannot be answered by the LLM.

Please read the [following](https://github.com/yaalalabs/agent-kernel/tree/develop/docs/docs/api/rest-api.md) on how to handle this properly without exhausting the token limits.
:::

### Message Handling

- **Automatic Message Splitting**: Messages longer than 4096 characters are automatically split
- **Session Management**: Uses phone number as session ID to maintain conversation context
- **Reply Threading**: Replies are threaded to original messages
- **Signature Verification**: Validates webhook requests using app secret
- **File Size Validation**: Automatic validation and rejection of oversized files

### Security

- **Webhook Signature Verification**: All incoming webhooks are verified using HMAC-SHA256
- **Token Authentication**: Uses verify token for webhook setup
- **Secure API Calls**: All API calls use Bearer token authentication

## WhatsApp Business API Setup

### Prerequisites

Please follow the steps at [WhatsApp Cloud API Get Started Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)

### Configuration Steps

1. **Create a WhatsApp Business App**
   - Login to WhatsApp developer account
   - Create a new app and select "Business" type
   - Add WhatsApp product to your app

2. **Get Your Credentials**
   - **Phone Number ID**: This is the test number you are given or it could be an actual business phone number you have set up. Test number can be found in WhatsApp > Getting Started
   - **Access Token**: Generate a permanent token in WhatsApp > Getting Started
   - **App Secret**: A token is an optional validation to verify that the webhook is called from WhatsApp. This is recommended, but the handler will work without setting this
   - **Verify Token**: Create your own secure random string for webhook verification

3. **Configure Webhook**
   - Go to WhatsApp > Configuration
   - Edit webhook
   - Set callback URL: `https://your-domain.com/whatsapp/webhook`
   - Set verify token: Your chosen verify token
   - Subscribe to `messages` webhook field

### Required Environment Variables

```bash
export AK_WHATSAPP__VERIFY_TOKEN="your_verify_token"  # Used when verification of the webhook URL is required
export AK_WHATSAPP__ACCESS_TOKEN="your_permanent_access_token"
export AK_WHATSAPP__APP_SECRET="your_app_secret"  # Optional
export AK_WHATSAPP__PHONE_NUMBER_ID="your test or business whatsapp phone number"
export AK_WHATSAPP__API_VERSION="v21.0"  # Optional, defaults to v24.0
```

### Webhook Verification

The handler automatically responds to WhatsApp's webhook verification challenge via `<hosted URL>/whatsapp/webhook` (e.g., `http://localhost:8000/whatsapp/webhook`). When you configure the webhook URL in Meta's developer portal, WhatsApp will send a GET request to verify the endpoint. The handler processes this automatically.

## Implementation

### Basic Integration

Here's a simple example of setting up a WhatsApp integration:

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.whatsapp import AgentWhatsAppRequestHandler

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

# Initialize the OpenAI module with your agent
OpenAIModule([general_agent])

# Create and run the server with WhatsApp handler
if __name__ == "__main__":
    handler = AgentWhatsAppRequestHandler()
    RESTAPI.run(handler=handler)
```

## Configuration Options

### config.yaml

```yaml
whatsapp:
  agent: "general"  # Name of the agent to handle WhatsApp messages
  agent_acknowledgement: "Processing your request..."  # Optional acknowledgement message before answering the query
  api_version: "v21.0"  # Optional
```

It is strongly recommended not to keep secrets and keys in the config file. Set them as environment variables.

## Testing

### Local Development

The `AgentWhatsAppRequestHandler` listens on `/whatsapp/webhook`, hence you need to set up the webhook URL as `https://<your-domain-or-ip>:<port>/whatsapp/webhook`

During URL registration, WhatsApp sends a challenge to the URL before enabling. The `AgentWhatsAppRequestHandler` handles this, hence you don't need any separate code to activate.

You can use https://pinggy.io/ or similar for local testing (e.g., `ssh -p 443 -R0:localhost:8000 a.pinggy.io`). [How to use pinggy to test Slack](https://pinggy.io/blog/how_to_get_slack_webhook/)

**Using ngrok:**
```bash
ngrok http 8000
```

**Using pinggy:**
```bash
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

A detailed example is provided in the examples section.

### Testing Steps

1. Start your local server
2. Set up the tunnel
3. Configure WhatsApp webhook with tunnel URL
4. Send a test message to your WhatsApp Business number
5. Check logs for request/response flow

## Advanced Usage

### Custom Message Handling

You can extend the handler for custom behavior:

```python
from agentkernel.whatsapp import AgentWhatsAppRequestHandler

class CustomWhatsAppHandler(AgentWhatsAppRequestHandler):
    async def _handle_message(self, message: dict, value: dict):
        # Add custom preprocessing
        message_text = message.get("text", {}).get("body", "")

        # Custom logic here
        if message_text.startswith("/help"):
            await self._send_message(
                message["from"],
                "Available commands: ...",
                message["id"]
            )
            return

        # Call parent handler
        await super()._handle_message(message, value)
```

## Troubleshooting

### Common Issues

**Webhook verification fails:**
- Ensure verify token in config matches what you set in Meta developer portal
- Check that your endpoint is accessible via HTTPS
- Verify the callback URL is correct

**Messages not being received:**
- Check webhook subscription is active
- Verify phone number is added to WhatsApp Business
- Check app secret and access token are correct
- Review server logs for errors

**Authentication errors:**
- Ensure access token is a permanent token, not temporary
- Verify phone number ID is correct
- Check token hasn't expired

**Messages not sending:**
- Verify access token has correct permissions
- Check phone number is verified and active
- Ensure recipient number is in correct format (no + or spaces)
- Review Meta Business Suite for any restrictions

### Debug Logging

## Example Projects

Complete working examples are available in the **examples/api/whatsapp** directory.

## References

- [WhatsApp Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Getting Started Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
- [Webhook Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks)
- [Message Templates](https://developers.facebook.com/docs/whatsapp/message-templates)
- [Meta for Developers](https://developers.facebook.com/)