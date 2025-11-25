# Facebook Messenger Integration

Facebook Messenger Platform integration for Agent Kernel using webhooks.

The `AgentMessengerRequestHandler` class handles conversations with agents via Facebook Messenger Platform webhooks. This integration uses the Messenger Send API (https://developers.facebook.com/docs/messenger-platform) without requiring third-party libraries beyond standard HTTP clients.

## How It Works

1. When a message is received from Messenger, it's verified and authenticated
2. A typing indicator is displayed to show the bot is processing
3. The message is extracted and passed to your chosen Agent
4. The Agent response is sent back as a Messenger message
5. Long messages are automatically split to respect Messenger's character limits

## Facebook Messenger Setup

### Prerequisites
Please follow the steps in the [Messenger Platform Getting Started Guide](https://developers.facebook.com/docs/messenger-platform/getting-started)

### Configuration Steps

1. **Create a Facebook App**
   - Go to https://developers.facebook.com/apps
   - Create a new app and select "Business" type
   - Add Messenger product to your app

2. **Create or Link a Facebook Page**
   - You need a Facebook Page to use Messenger Platform
   - Link your page to the app in Messenger Settings

3. **Get Your Credentials**
   - **Page Access Token**:  App > Left side panel > Select 'Use cases' > Select 'Engage with customers on messenger from Meta' > Select 'Customise'
          - Click on 'Messenger API settings' > Select "Generate Access Tokens" and do the needful

   - **App Secret**: [Optional but recommended for security]. App > App Setting > Basic
         
   - **Verify Token**: Create your own secure random string for webhook verification

4. **Configure Webhook**
   - Go to 'Messenger API settings' (described above) > Select "Config Webhooks"
   - click "Add Callback URL". Set callback URL: `https://your-domain.com/messenger/webhook`
   - Set verify token: Your chosen verify token. Click "Verify and Save"
   - Subscribe to these webhook fields:
     - `messages` - To receive messages
     - `messaging_optins` - To receive messages
     - `messaging_postbacks` - To handle button clicks
     - `message_deliveries` - For delivery confirmations (optional)
     - `message_reads` - For read receipts (optional)

5. **Subscribe Your Page**
   * After webhook verification, subscribe your page to receive events. To do that go back to "Generate Access Token" > "Webhook Subcription"
    * Subscribe to these webhook fields:
      * `messages` - To receive messages
      * `messaging_optins` - To receive messages
      * `messaging_postbacks` - To handle button clicks

6. **Testing**
  * See the  Testing steps at the bottom
  * You need to get the approval for the FB page to enable message flow from the page to the Agent.
    * From 'Messenger API settings' > 'Complete App Review' section > Select 'Request Permission'

### Required Environment Variables

```bash
export AK_MESSENGER__VERIFY_TOKEN="your_verify_token"  # Required for webhook verification
export AK_MESSENGER__ACCESS_TOKEN="your_page_access_token"  # Required
export AK_MESSENGER__APP_SECRET="your_app_secret"  # Optional, but strongly recommended
export AK_MESSENGER__API_VERSION="v21.0"  # Optional, defaults to v24.0. Only change if you want to move to a different version
```

### Webhook Verification
The handler automatically responds to Facebook's webhook verification challenge via `<hosted URL>/messenger/webhook` (e.g., `http://localhost:8000/messenger/webhook`). When you configure the webhook URL in Facebook's developer portal, Facebook will send a GET request to verify the endpoint. The handler processes this automatically.

## Simple Facebook Messenger Integration Code

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.messenger import AgentMessengerRequestHandler

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers suitable for messaging.",
)

# Initialize module with agent
OpenAIModule([general_agent])

if __name__ == "__main__":
    handler = AgentMessengerRequestHandler()
    RESTAPI.run([handler])
```

## Configuration Options

### config.yaml

```yaml
messenger:
  agent: "general"  # Name of the agent to handle Messenger messages
  api_version: "v21.0"  # Optional, defaults to v24.0
```
It is strongly recommended not to keep secrets and keys in the config file. Set them as environment variables.

## Features

### Supported Event Types

- **Text Messages**: Standard text messages
- **Postbacks**: Button clicks and quick reply selections
- **Attachments**: Images, videos, audio, files (basic detection)
- **Delivery Receipts**: Message delivery confirmations
- **Read Receipts**: Message read notifications

### Message Handling

- **Automatic Message Splitting**: Messages longer than 2000 characters are automatically split
- **Session Management**: Uses sender ID as session ID to maintain conversation context
- **Typing Indicators**: Shows typing indicator while processing
- **Message Threading**: Maintains conversation flow

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

Update your Facebook webhook URL with the tunnel URL.

### Testing Steps
This assumes that you have successfully verified the Webhook URL and correct subscriptions are enabled.

1. App > Left side panel > Select 'Use cases' > Select 'Engage with customers on messenger from Meta' > Select 'Customise'
          - Click on 'Messenger API settings' > Select "API integration helper"
2. In the API integration helper, insert your page access token and the page will automatically get selected.
3. From there select a recipient, insert the test message and click on "Send message"

## Advanced Usage

### Custom Message Handling

You can extend the handler for custom behavior:

```python
from agentkernel.messenger import AgentMessengerRequestHandler

class CustomMessengerHandler(AgentMessengerRequestHandler):
    async def _handle_message(self, messaging_event: dict):
        # Add custom preprocessing
        message = messaging_event.get("message", {})
        message_text = message.get("text", "")
        
        # Custom logic here
        if message_text.startswith("/help"):
            sender_id = messaging_event["sender"]["id"]
            await self._send_message(
                sender_id,
                "Available commands: ..."
            )
            return
        
        # Call parent handler
        await super()._handle_message(messaging_event)
```

### Sending Rich Messages

You can extend the handler to send structured messages:

```python
async def _send_quick_replies(self, recipient_id: str, text: str, quick_replies: list):
    """Send a message with quick reply buttons."""
    url = f"{self._base_url}/me/messages"
    headers = {
        "Authorization": f"Bearer {self._access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "text": text,
            "quick_replies": quick_replies
        },
        "messaging_type": "RESPONSE"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
```

## Troubleshooting

### Common Issues

**Webhook verification fails:**
- Ensure verify token in config matches what you set in Facebook developer portal
- Check that your endpoint is accessible via HTTPS
- Verify the callback URL is correct
- Make sure the handler returns the challenge as an integer

**No Messages Received:**
- Check webhook subscription is active
- Verify page is subscribed to webhook events
- Check app secret and access token are correct
- Review server logs for errors
- Ensure the app is not in development mode restrictions

**Agent Not Responding:**
- Verify access token has correct permissions
- Check agent configuration in config.yaml
- Review server logs for agent errors
- Ensure the page access token hasn't expired

**Messages Not Sending:**
- Verify access token is a page access token, not user token
- Check token permissions include `pages_messaging`
- Ensure recipient has messaged your page first (24-hour window rule)
- Review Facebook Business Suite for any restrictions

### Debug Logging

Enable debug logging to troubleshoot:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## API Rate Limits

Facebook Messenger API has rate limits:
- **Standard Messaging**: 10,000 messages per day per page (varies by tier)
- **Broadcast Messages**: Requires approval and different messaging type
- **Response Time**: Must respond to user messages within 24 hours

For higher limits, apply for standard messaging access.

## Messenger Platform Features

### Message Types

The platform supports three messaging types:
- **RESPONSE**: Reply to user messages (default, used in this integration)
- **UPDATE**: Send proactive notifications (requires approval)
- **MESSAGE_TAG**: Send messages outside 24-hour window with approved tags

### Quick Replies

Quick replies provide predefined response options to users. Extend the handler to add this functionality.

### Buttons and Templates

Messenger supports rich templates like:
- Button template
- Generic template (cards)
- List template
- Media template

These can be added by extending the `_send_message` method.

## Privacy and Compliance

### User Data
- Store user data securely
- Implement data retention policies
- Provide data deletion capabilities
- Follow GDPR/CCPA requirements

### Facebook Policies
- Review Facebook Platform Policy
- Ensure compliance with Messenger Platform Policy
- Get required permissions before going live
- Implement proper error handling

## Production Deployment

For production deployment:

1. **Use HTTPS**: Deploy behind nginx or similar with SSL certificate
2. **Environment Variables**: Use secure secret management (AWS Secrets Manager, etc.)
3. **Monitoring**: Add comprehensive logging and alerting
4. **Scaling**: Use containerization and orchestration (Docker, Kubernetes)
5. **Error Handling**: Implement robust error handling and retries
6. **Rate Limiting**: Implement rate limiting and queuing
7. **Get App Reviewed**: Submit your app for review to remove development mode restrictions

### App Review
Before going live:
1. Complete app review process
2. Request `pages_messaging` permission
3. Provide test credentials and instructions
4. Wait for approval (typically 3-5 business days)

See deployment documentation for AWS and other platforms.

## Differences from WhatsApp Integration

Key differences between Messenger and WhatsApp integrations:

1. **Message Limits**: Messenger has 2000 char limit vs WhatsApp's 4096
2. **Typing Indicators**: Messenger has built-in typing indicator support
3. **Event Types**: Messenger has postbacks, WhatsApp has interactive messages
4. **Authentication**: Different token/auth mechanisms
5. **User IDs**: Messenger uses PSID (Page-Scoped ID) vs phone numbers

## Resources

- [Messenger Platform Documentation](https://developers.facebook.com/docs/messenger-platform)
- [Send API Reference](https://developers.facebook.com/docs/messenger-platform/reference/send-api)
- [Webhook Reference](https://developers.facebook.com/docs/messenger-platform/webhooks)
- [Platform Policy](https://developers.facebook.com/docs/messenger-platform/policy-overview)
- [Agent Kernel Documentation](../../../docs/)
