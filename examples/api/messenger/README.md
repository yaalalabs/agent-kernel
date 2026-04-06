# Facebook Messenger Integration Example

This example demonstrates how to create a Facebook Messenger Platform integration with Agent Kernel.

## Prerequisites

1. Facebook Developer Account
2. Facebook App with Messenger product added
3. Facebook Page linked to the app
4. Webhook configured in Facebook Developer Portal
5. Required credentials (see below)

## Setup

### 1. Get Facebook Messenger Credentials

Follow the setup guide in [AgentMessengerRequestHandler](../../../ak-py/src/agentkernel/integrations/messenger/README.md)

You'll need:
- Page Access Token
- App Secret (optional but recommended)
- Verify Token (you create this)

### 2. Configure Environment Variables

Create a `.env` file or export these variables:

```bash
export AK_MESSENGER__VERIFY_TOKEN="your_secure_verify_token"
export AK_MESSENGER__ACCESS_TOKEN="your_page_access_token"
export AK_MESSENGER__APP_SECRET="your_app_secret"
export AK_MESSENGER__API_VERSION="v21.0"  # Optional, defaults to v24.0. Only change if you want to move to a different version

# OpenAI API Key for the agent
export OPENAI_API_KEY="your_openai_api_key"

# Multimodal Configuration (Optional)
export AK_MULTIMODAL__ENABLED=true              # Enable multimodal support (default: false)
export AK_MULTIMODAL__MAX_ATTACHMENTS=5         # Keep last N files in session (default: 5)
```

### 3. Create Configuration File

Create `config.yaml`:

```yaml
messenger:
  agent: "general"
  api_version: "v21.0"
```

## Build

Install dependencies using:

```bash
./build.sh
```

For local development with Agent Kernel source:

```bash
./build.sh local
```

## Run

Start the server:

```bash
uv run server.py
```

The server will start on `http://localhost:8000` by default.

## Expose Local Server

For local testing, expose your server using a tunnel:

### Using ngrok:
```bash
ngrok http 8000
```

### Using pinggy:
```bash
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

Copy the HTTPS URL and configure it in your Facebook Messenger webhook settings.

## Configure Facebook Messenger Webhook

1. Go to https://developers.facebook.com/apps
2. Select your app
3. Go to Messenger > Settings
4. In the "Webhooks" section, click "Add Callback URL"
5. Enter:
   - **Callback URL**: `https://your-tunnel-url.com/messenger/webhook`
   - **Verify Token**: Same as `AK_MESSENGER__VERIFY_TOKEN`
6. Click "Verify and Save"
7. Subscribe to these webhook fields:
   - `messages`
   - `messaging_postbacks`
   - `message_deliveries` (optional)
   - `message_reads` (optional)
8. Subscribe your Facebook Page to the webhook

## Testing

1. Go to your Facebook Page
2. Click "Send Message" or use Messenger app
3. Send a message to your page
4. The bot should display a typing indicator
5. After processing, you'll receive the agent's response
6. Check server logs to see the request/response flow

### Test Message Examples

```
Hello
What can you help me with?
Tell me about your services
Can you answer technical questions?
```

## Advanced Examples

### Custom Message Handler

See `example_custom_handler.py` for extending the handler with custom logic:

```python
from agentkernel.messenger import AgentMessengerRequestHandler

class CustomMessengerHandler(AgentMessengerRequestHandler):
    async def _handle_message(self, messaging_event: dict):
        # Custom preprocessing
        message = messaging_event.get("message", {})
        text = message.get("text", "")
        sender_id = messaging_event["sender"]["id"]
        
        # Handle commands
        if text.startswith("/start"):
            await self._send_message(sender_id, "Welcome! How can I help you?")
            return
        
        # Default behavior
        await super()._handle_message(messaging_event)
```

### Multi-Agent Setup

```python
# Create specialized agents
support_agent = OpenAIAgent(
    name="support",
    handoff_description="Customer support agent",
    instructions="Provide helpful customer support responses."
)

sales_agent = OpenAIAgent(
    name="sales",
    handoff_description="Sales inquiry agent",
    instructions="Help with product information and sales inquiries."
)

# Initialize with multiple agents
OpenAIModule([support_agent, sales_agent])
```

## Troubleshooting

### Webhook Verification Fails

- Ensure verify token in config matches Facebook Developer Portal
- Check that your endpoint is accessible via HTTPS
- Verify the callback URL is correct
- Ensure server is running before verification

### No Messages Received

- Check webhook subscription is active
- Verify page is subscribed to webhook events
- Ensure the app is not restricted (check App Review status)
- Review server logs for errors
- Check webhook subscriptions in Facebook Developer Portal

### Agent Not Responding

- Verify OpenAI API key is set correctly
- Check agent configuration in config.yaml
- Review server logs for agent errors
- Ensure agent name matches configuration

### Messages Not Sending

- Verify access token is a **page access token**, not user token
- Check token has `pages_messaging` permission
- Ensure you're within 24-hour messaging window
- Review Facebook Business Suite for restrictions
- Check server logs for API errors

### Signature Verification Fails

- Ensure APP_SECRET is set correctly
- Verify the secret matches your Facebook app
- Check that the webhook payload hasn't been modified in transit

### Rate Limiting

If you hit rate limits:
- Implement message queuing
- Add retry logic with exponential backoff
- Monitor rate limit headers in API responses
- Consider applying for higher tier access

## Production Deployment

For production deployment:

1. **Use HTTPS**: Deploy behind nginx or similar with SSL certificate
2. **Environment Variables**: Use secure secret management (AWS Secrets Manager, HashiCorp Vault, etc.)
3. **Monitoring**: Add comprehensive logging and alerting (CloudWatch, Datadog, etc.)
4. **Scaling**: Use containerization and orchestration (Docker, Kubernetes)
5. **Error Handling**: Implement robust error handling and retries
6. **Rate Limiting**: Implement rate limiting and message queuing
7. **Get App Reviewed**: Complete Facebook app review before going live
8. **Database**: Use persistent storage for conversation history
9. **Load Balancing**: Distribute traffic across multiple instances
10. **Health Checks**: Implement health check endpoints

### Facebook App Review

Before going live with your app:

1. **Complete Platform Policy Review**
   - Review Facebook Platform Policies
   - Review Messenger Platform Policies
   - Ensure compliance with data handling requirements

2. **Submit for Review**
   - Request `pages_messaging` permission
   - Provide test credentials and detailed instructions
   - Submit screencast demonstrating functionality
   - Wait for approval (typically 3-5 business days)

3. **Switch to Live Mode**
   - After approval, switch app from development to live mode
   - Update webhook URLs if needed
   - Monitor for issues

### Deployment Architectures

See deployment documentation for:
- AWS Lambda + API Gateway (serverless)
- AWS ECS/EKS (containerized)
- Google Cloud Run
- Azure Container Apps

## Features to Implement

Extend this example with:

- **Rich Messages**: Buttons, quick replies, templates
- **Persistent Menu**: Add a persistent menu to your bot
- **Getting Started Button**: Customize the initial experience
- **Natural Language Processing**: Add intent recognition
- **Multi-language Support**: Detect and respond in user's language
- **Analytics**: Track conversation metrics
- **Handoff Protocol**: Transfer to human agents when needed

## Resources

- [Facebook Messenger Platform Documentation](https://developers.facebook.com/docs/messenger-platform)
- [Send API Reference](https://developers.facebook.com/docs/messenger-platform/reference/send-api)
- [Webhook Reference](https://developers.facebook.com/docs/messenger-platform/webhooks)
- [Platform Policy](https://developers.facebook.com/docs/messenger-platform/policy-overview)
- [Agent Kernel Documentation](../../../docs/)
- [Facebook Messenger Integration Guide](../../../ak-py/src/agentkernel/integrations/messenger/README.md)

## Support

For issues and questions:
- Check the [troubleshooting section](#troubleshooting)
- Review server logs for detailed error messages
- Consult Facebook Developer Community
- Review Agent Kernel documentation
