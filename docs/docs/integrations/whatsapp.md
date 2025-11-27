# WhatsApp

The WhatsApp integration allows you to deploy Agent Kernel agents as WhatsApp bots that can respond to messages via the WhatsApp Business API. This integration uses the WhatsApp Cloud API webhooks to provide real-time conversational AI capabilities.

## Overview

The `AgentWhatsAppRequestHandler` class handles conversations with agents via WhatsApp Business API webhooks. The integration provides the following workflow:

1. **Message Reception**: When a message is received from WhatsApp, it's verified and authenticated
2. **Acknowledgment**: An optional acknowledgment message is sent to the user
3. **Question Processing**: The question is extracted and passed to your chosen agent
4. **Response Delivery**: The agent response is sent back as a WhatsApp message
5. **Message Splitting**: Long messages are automatically split to respect WhatsApp's character limits

## Features

- **Multiple Message Types**: Support for text only. Later additional media files will be supported
- **Automatic Message Splitting**: Messages longer than 4096 characters are split automatically
- **Session Management**: Uses phone number as session ID to maintain conversation context. In future, we will add support to clear the history and start a new conversation
- **Security**: Webhook signature verification using HMAC-SHA256

## WhatsApp Business API Setup

### 1. Create a WhatsApp Business App

1. Go to [Meta for Developers](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
2. Create a new app and select "Business" type
3. Add WhatsApp product to your app

### 2. Get Your Credentials

From your WhatsApp Business app dashboard:

- **Phone Number ID**: Found in WhatsApp > Getting Started (test number or verified business number)
- **Access Token**: Generate a permanent token in WhatsApp > Getting Started
- **App Secret**: Optional token for webhook verification (recommended)
- **Verify Token**: Create your own secure random string for webhook verification

### 3. Configure Webhook

1. Go to WhatsApp > Configuration
2. Edit webhook settings
3. Set callback URL: `https://your-domain.com/whatsapp/webhook`
4. Set verify token: Your chosen verify token
5. Subscribe to `messages` webhook field

## Environment Configuration

Set the following environment variables for the integration:

```bash
export AK_WHATSAPP__VERIFY_TOKEN="your_verify_token"  # Optional
export AK_WHATSAPP__ACCESS_TOKEN="your_permanent_access_token"
export AK_WHATSAPP__APP_SECRET="your_app_secret"  # Optional, recommended
export AK_WHATSAPP__PHONE_NUMBER_ID="your_phone_number_id"
export AK_WHATSAPP__API_VERSION="v21.0"  # Optional, defaults to v24.0
```

### Getting Credentials

- **Access Token**: Found under WhatsApp > Getting Started → "Temporary access token" (generate permanent)
- **App Secret**: Found in app settings under "Basic Information" → "App Secret"
- **Phone Number ID**: Listed in WhatsApp > Getting Started → "Phone numbers"

## Webhook URL Setup

The integration automatically handles WhatsApp's URL verification challenge. The `AgentWhatsAppRequestHandler` listens on the `/whatsapp/webhook` endpoint. Configure your webhook URL as:

```
https://your-domain.com/whatsapp/webhook
```

### Local Development

For local testing, you can use tunneling services:

**Using ngrok:**
```bash
ngrok http 8000
```

**Using pinggy:**
```bash
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

Then use the provided HTTPS URL in your WhatsApp webhook configuration.

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

### Custom Acknowledgment Messages and Agent

You can configure which agent will handle WhatsApp messages and customize acknowledgment messages:

```yaml
# Configuration in config.yaml
whatsapp:
  agent: "general"  # Name of the agent to handle messages
  agent_acknowledgement: "🤖 Processing your request..."  # Optional
  api_version: "v21.0"  # Optional
```

**Note**: It's strongly recommended to set credentials as environment variables rather than in config files.

## Supported Message Types

- **Text Messages**: Standard text messages with full conversation support
- **Interactive Messages**: Button and list replies for enhanced user experience  
- **Media Messages**: Basic support for images, videos, audio, and documents

## Custom Request Handler

For advanced WhatsApp integrations, you can extend the base handler:

```python
from agentkernel.whatsapp import AgentWhatsAppRequestHandler

class CustomWhatsAppHandler(AgentWhatsAppRequestHandler):
    async def _handle_message(self, message: dict, value: dict):
        message_text = message.get("text", {}).get("body", "")
        
        # Custom command handling
        if message_text.startswith("/help"):
            await self._send_message(
                message["from"],
                "Available commands: /help, /status",
                message["id"]
            )
            return
        
        # Call parent handler for normal processing
        await super()._handle_message(message, value)
```

## Troubleshooting

### Common Issues

**Webhook verification fails:**
- Ensure verify token matches what you set in Meta developer portal
- Check that your endpoint is accessible via HTTPS
- Verify the callback URL format is correct

**Messages not being received:**
- Check webhook subscription is active for 'messages'
- Verify phone number is properly configured in WhatsApp Business
- Ensure access token and app secret are correct
- Review server logs for incoming webhook requests

**Authentication errors:**
- Verify access token is permanent, not temporary
- Check phone number ID is correct
- Ensure token hasn't expired or been revoked

**Messages not sending:**
- Verify access token has messaging permissions
- Check recipient phone number format (no + or spaces)
- Review [Meta Business Suite](https://business.facebook.com/) for restrictions
- Check API rate limits haven't been exceeded

### Debug Logging

Enable debug logging for troubleshooting:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## API Rate Limits

WhatsApp Cloud API has the following rate limits:

- **Messaging**: 80-250 messages/second (based on business tier)
- **Business Initiated Conversations**: Limited per 24-hour window
- **Webhooks**: Must respond within 20 seconds

## Example Projects

Complete working examples are available in the **examples/api/whatsapp** directory.

## References

- [WhatsApp Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Getting Started Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
- [Webhook Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks)
- [Message Templates](https://developers.facebook.com/docs/whatsapp/message-templates)
- [Meta for Developers](https://developers.facebook.com/)