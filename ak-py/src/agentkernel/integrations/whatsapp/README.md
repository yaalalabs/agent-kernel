# WhatsApp Integration

WhatsApp Business API integration for Agent Kernel using webhooks.

The `AgentWhatsAppRequestHandler` class handles conversations with agents via WhatsApp Business API webhooks. This integration uses the WhatsApp Cloud API (https://developers.facebook.com/docs/whatsapp/cloud-api) without requiring third-party libraries beyond standard HTTP clients.

## How It Works

1. When a message is received from WhatsApp, it's verified and authenticated
2. An optional acknowledgement message is sent to the user
3. The question is extracted and passed to your chosen Agent
4. The Agent response is sent back as a WhatsApp message
5. Long messages are automatically split to respect WhatsApp's character limits

## WhatsApp Business API Setup

### Prerequisites
Please follow the steps in here ( https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)

### Configuration Steps

1. **Create a WhatsApp Business App**
   - Login to whats app developer account
   - Create a new app and select "Business" type
   - Add WhatsApp product to your app

2. **Get Your Credentials**
   - **Phone Number ID**: This is the test number you are given or it could be an actual business phone number you have setup. Test number can be found in WhatsApp > Getting Started
   - **Access Token**: Generate a permanent token in WhatsApp > Getting Started
   - **App Secret**: Found in App Settings > Basic
   - **Verify Token**: Create your own secure random string for webhook verification

3. **Configure Webhook**
   - Go to WhatsApp > Configuration
   - Edit webhook
   - Set callback URL: `https://your-domain.com/whatsapp/webhook`
   - Set verify token: Your chosen verify token
   - Subscribe to `messages` webhook field

### Required Environment Variables

```bash
export AK_WHATSAPP_VERIFY_TOKEN="your_verify_token"
export AK_WHATSAPP_ACCESS_TOKEN="your_permanent_access_token"
export AK_WHATSAPP_APP_SECRET="your_app_secret"
export AK_WHATSAPP_PHONE_NUMBER_ID="your test or business whats app phone number"
export AK_WHATSAPP_API_VERSION="v21.0"  # Optional, defaults to v21.0
```

### Webhook Verification

The handler automatically responds to WhatsApp's webhook verification challenge. When you configure the webhook URL in Meta's developer portal, WhatsApp will send a GET request to verify the endpoint. The handler processes this automatically.

## Simple WhatsApp Integration Code

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.integrations.whatsapp import AgentWhatsAppRequestHandler

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

# Initialize module with agent
OpenAIModule([general_agent])

if __name__ == "__main__":
    handler = AgentWhatsAppRequestHandler()
    RESTAPI.run(handler=handler)
```

## Configuration Options

### config.yaml

```yaml
whatsapp:
  agent: "general"  # Name of the agent to handle WhatsApp messages
  agent_acknowledgement: "Processing your request..."  # Optional acknowledgement message
  verify_token: "${AK_WHATSAPP_VERIFY_TOKEN}"
  access_token: "${AK_WHATSAPP_ACCESS_TOKEN}"
  app_secret: "${AK_WHATSAPP_APP_SECRET}"
  phone_number_id: "${AK_WHATSAPP_PHONE_NUMBER_ID}"
  api_version: "v21.0"  # Optional
```

## Features

### Supported Message Types

- **Text Messages**: Standard text messages
- **Interactive Messages**: Button and list replies
- **Media Messages**: Image, video, audio, and document (basic support)

### Message Handling

- **Automatic Message Splitting**: Messages longer than 4096 characters are automatically split
- **Session Management**: Uses phone number as session ID to maintain conversation context
- **Reply Threading**: Replies are threaded to original messages
- **Signature Verification**: Validates webhook requests using app secret

### Security

- **Webhook Signature Verification**: All incoming webhooks are verified using HMAC-SHA256
- **Token Authentication**: Uses verify token for webhook setup
- **Secure API Calls**: All API calls use Bearer token authentication

## Testing

### Local Development

For local testing, use a tunneling service to expose your local server:

**Using ngrok:**
```bash
ngrok http 8000
```

**Using pinggy:**
```bash
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

Update your WhatsApp webhook URL with the tunnel URL.

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
from agentkernel.integrations.whatsapp import AgentWhatsAppRequestHandler

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

### Multi-Agent Routing

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule
from agentkernel.integrations.whatsapp import AgentWhatsAppRequestHandler

support_agent = OpenAIAgent(
    name="support",
    handoff_description="Technical support agent",
    instructions="Provide technical support and troubleshooting help."
)

sales_agent = OpenAIAgent(
    name="sales",
    handoff_description="Sales and product inquiries",
    instructions="Help with product information and sales questions."
)

general_agent = OpenAIAgent(
    name="general",
    handoff_description="General inquiries",
    instructions="Handle general questions and route to specialized agents when needed."
)

OpenAIModule([general_agent, support_agent, sales_agent])

if __name__ == "__main__":
    handler = AgentWhatsAppRequestHandler()
    RESTAPI.run(handler=handler)
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

Enable debug logging to troubleshoot:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## API Rate Limits

WhatsApp Cloud API has rate limits:
- **Messaging**: Based on your business tier (80-250 messages/second)
- **Business Initiated Conversations**: Limited per 24-hour window
- **Webhooks**: No specific limit but must respond within 20 seconds

## Production Considerations

### Scaling
- Use async processing for long-running agent operations
- Implement request queuing for high message volumes
- Consider multiple webhook endpoints with load balancing

### Monitoring
- Monitor webhook delivery success rates
- Track agent response times
- Log failed message deliveries
- Monitor API quota usage

### Security
- Always verify webhook signatures
- Use environment variables for sensitive data
- Rotate access tokens periodically
- Implement rate limiting on your endpoints

## References

- [WhatsApp Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Webhook Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks)
- [Message Templates](https://developers.facebook.com/docs/whatsapp/message-templates)
