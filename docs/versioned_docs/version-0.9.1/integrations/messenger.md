# Messenger

Deploy your Agent Kernel agents as Facebook Messenger bots that can respond to messages in real-time. This integration connects your AI agents directly to Facebook Messenger, enabling natural conversations with users through one of the world's most popular messaging platforms.

## Overview

The `AgentMessengerRequestHandler` provides a seamless bridge between your Agent Kernel agents and Facebook Messenger. When users message your Facebook Page, their messages are automatically routed to your AI agent, which processes them and sends intelligent responses back through Messenger.

**How it works:**

1. **User sends a message** to your Facebook Page through Messenger
2. **Message is verified** using Facebook's security protocols
3. **Visual feedback** is sent (message marked as seen, typing indicator appears)
4. **Agent processes** the message and generates a response
5. **Response is delivered** back to the user in Messenger

The integration handles all the complexity of the Messenger Platform API, including webhook verification, signature validation, and message formatting.

## Key Features

- 🔐 **Secure Communication**: HMAC-SHA256 signature verification ensures all messages are authentic
- 💬 **Rich Messaging**: Support for text messages, postbacks, attachments, and interactive elements
- ⚡ **Real-time Feedback**: Automatic "seen" receipts and typing indicators for better user experience
- 🔄 **Session Management**: Maintains conversation context using Messenger's Page-Scoped IDs
- 📊 **Message Splitting**: Automatically handles long responses by splitting them into multiple messages
- 🎯 **Event Handling**: Processes various Messenger events including messages, postbacks, and delivery receipts

## Quick Start

### Prerequisites

Before you begin, you'll need:

- A [Facebook Developer account](https://developers.facebook.com/)
- A Facebook Page (this will be your bot's identity)
- A Facebook App with Messenger product added
- A publicly accessible HTTPS endpoint (for webhook)

### 1. Set Up Your Facebook App

**Create your app:**

1. Visit the [Facebook Developers Portal](https://developers.facebook.com/apps)
2. Click "Create App" and select "Business" as the app type
3. Fill in your app details and create the app
4. From the left sidebar, click "Add Product" and select "Messenger"

**Link your Facebook Page:**

1. In your app dashboard, go to **Use cases** → **Engage with customers on Messenger from Meta** → **Customise**
2. Click **Messenger API settings**
3. Under "Access Tokens", click **Add or remove Pages**
4. Select the Facebook Page that will represent your bot

### 2. Get Your Credentials

**Generate a Page Access Token:**

1. In **Messenger API settings**, find "Access Tokens"
2. Click **Generate Access Tokens** for your page
3. Copy and save this token securely - you'll need it as `AK_MESSENGER__ACCESS_TOKEN`

**Get your App Secret (recommended):**

1. Go to **App Settings** → **Basic** in the left sidebar
2. Click **Show** next to "App Secret"
3. Copy and save this secret - you'll use it as `AK_MESSENGER__APP_SECRET`

**Create a Verify Token:**

This is a random string you create yourself for webhook verification. Choose something secure like:

```bash
openssl rand -hex 32
```

Save this as `AK_MESSENGER__VERIFY_TOKEN`

### 3. Configure Environment Variables

Set these environment variables before starting your application:

```bash
export AK_MESSENGER__VERIFY_TOKEN="your_random_verify_token"
export AK_MESSENGER__ACCESS_TOKEN="your_page_access_token"
export AK_MESSENGER__APP_SECRET="your_app_secret"  # Optional but recommended
export AK_MESSENGER__API_VERSION="v21.0"  # Optional, defaults to v21.0
```

**Multimodal Configuration (for image and document support):**

```bash
export AK_MULTIMODAL__ENABLED=true              # Enable multimodal support (default: true)
export AK_MULTIMODAL__MAX_ATTACHMENTS=5         # Keep last N files in session (default: 5)
```

### 4. Set Up Your Webhook

**For local development**, use a tunneling service to expose your local server:

```bash
# Using ngrok
ngrok http 8000

# Using pinggy
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

**Configure the webhook in Facebook:**

1. In **Messenger API settings**, click **Add Callback URL**
2. Enter your webhook URL: `https://your-domain.com/messenger/webhook`
3. Enter your verify token (the one you created above)
4. Click **Verify and Save**

**Subscribe to webhook events:**

Still in **Messenger API settings**, under "Webhooks", subscribe to:

- `messages` - To receive user messages
- `messaging_postbacks` - To handle button clicks
- `messaging_optins` - To receive opt-in events

**Subscribe your page:**

1. Go to **Access Tokens** → **Webhook Subscriptions**
2. Select the events: `messages`, `messaging_postbacks`, `messaging_optins`
3. Click **Subscribe**

## Implementation

### Basic Setup

Here's a complete example to get your Messenger bot running:

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.messenger import AgentMessengerRequestHandler

# Create your AI agent
customer_service_agent = OpenAIAgent(
    name="customer_service",
    handoff_description="Helpful customer service agent",
    instructions="""You are a friendly customer service assistant on Facebook Messenger.
    - Keep responses concise and mobile-friendly
    - Use emojis sparingly to maintain professionalism
    - Break long explanations into short paragraphs
    - Be conversational and helpful"""
)

# Initialize the module with your agent
OpenAIModule([customer_service_agent])

# Start the server with Messenger integration
if __name__ == "__main__":
    handler = AgentMessengerRequestHandler()
    RESTAPI.run([handler])
```

> **Note:** When `AK_MULTIMODAL__ENABLED=true`, the `analyze_attachments` tool is automatically attached to all agents by Agent Kernel at startup. You do not need to add it manually.

### Configuration File

Optionally configure your agent and API settings in `config.yaml`:

```yaml
messenger:
  agent: "customer_service"  # Which agent handles Messenger messages
  api_version: "v21.0"  # Facebook Graph API version. 24 is the default. Only set if you want a different version
```

**Security Note:** Never store tokens or secrets in configuration files. Always use environment variables for sensitive credentials.

## Testing Your Integration

### Test from Facebook Developer Portal

The easiest way to test during development:

1. Go to your app's **Messenger API settings**
2. Click **API integration helper**
3. Your page will be auto-selected if you've added the access token
4. Select a recipient (you can test with yourself)
5. Type a test message and click **Send message**
6. Check your server logs to see the message being processed
7. You should receive a response in Messenger

### Test from Messenger

Once your webhook is configured:

1. Open Facebook Messenger (mobile app or web)
2. Search for your Facebook Page
3. Send a message
4. Watch for the "Seen" indicator and typing animation
5. Receive your agent's response

**Note:** Initially, only you (the app developer) and page administrators can message your bot. To allow others, you'll need to complete Facebook's app review process.

## Advanced Usage

### Custom Message Handling

Extend the handler to add custom logic, commands, or preprocessing:

```python
from agentkernel.messenger import AgentMessengerRequestHandler

class CustomMessengerHandler(AgentMessengerRequestHandler):
    async def _handle_message(self, messaging_event: dict):
        message = messaging_event.get("message", {})
        message_text = message.get("text", "").strip()
        sender_id = messaging_event.get("sender", {}).get("id")

        # Handle special commands
        if message_text.startswith("/"):
            await self._handle_command(message_text, sender_id)
            return

        # Preprocess messages before sending to agent
        processed_text = self._preprocess_message(message_text)

        # Continue with normal processing
        await super()._handle_message(messaging_event)

    async def _handle_command(self, command: str, sender_id: str):
        """Handle custom commands"""
        await self._mark_seen(sender_id)
        await self._send_typing_indicator(sender_id, True)

        if command == "/help":
            help_text = """🤖 Available Commands:

/help - Show this help message
/start - Start a new conversation

Just send any message to chat with me!"""
            await self._send_message(sender_id, help_text)
        elif command == "/start":
            await self._send_message(
                sender_id, 
                "👋 Hi! I'm here to help. What can I do for you today?"
            )
        else:
            await self._send_message(
                sender_id,
                f"Unknown command. Try /help for available commands."
            )

        await self._send_typing_indicator(sender_id, False)

    def _preprocess_message(self, text: str) -> str:
        """Clean up or enhance user messages"""
        # Expand common abbreviations
        replacements = {
            "pls": "please",
            "thx": "thanks",
            "u": "you"
        }
        words = text.split()
        return " ".join(replacements.get(word.lower(), word) for word in words)

# Use your custom handler
if __name__ == "__main__":
    handler = CustomMessengerHandler()
    RESTAPI.run([handler])
```

### Multi-Agent Setup

Route different types of conversations to specialized agents:

```python
from agentkernel.messenger import AgentMessengerRequestHandler

# Create specialized agents
sales_agent = OpenAIAgent(
    name="sales",
    handoff_description="Sales and product inquiries",
    instructions="Help customers with product information and purchase decisions."
)

support_agent = OpenAIAgent(
    name="support", 
    handoff_description="Technical support and troubleshooting",
    instructions="Provide technical assistance and resolve customer issues."
)

general_agent = OpenAIAgent(
    name="general",
    handoff_description="General questions and conversation",
    instructions="Handle general inquiries in a friendly manner."
)

OpenAIModule([sales_agent, support_agent, general_agent])

# The agent specified in config.yaml will be used by default
```

## Supported Message Types

### Text Messages

Standard text messages are fully supported with automatic context management.

### Postbacks

Handle button clicks and quick reply selections. Postbacks are processed as text using the button title or payload.

### Multi-Modal: Images and Files 

The integration provides full support for images and file attachments with AI analysis:

**Supported Formats:**

- **Images**: JPEG, PNG, GIF, WebP (detected automatically)
- **Documents**: PDF (.pdf)

**How It Works:**

1. **Detection**: When user sends message with attachment, handler identifies type
2. **Download**: File is downloaded from Messenger's servers
3. **Validation**: File size checked against limit (default 20 MB)
4. **Encoding**: File converted to base64 for transmission
5. **Processing**: Agent receives file and can analyze it
6. **Response**: Agent provides insights or answers about the content

**File Size Limits:**

- **Default**: 20 MB per file (20,971,520 bytes)
- **Base64 Overhead**: ~33% increase in size
- **Effective Size**: ~15 MB usable after base64 encoding
- **Configurable**: Set `api.max_file_size` in config.yaml

**Example User Interactions:**

```bash
User: "What's in this photo?" [sends image]
Agent: [analyzes image] "This appears to be..."

User: "Extract the text from this PDF" [sends PDF]
Agent: [processes PDF] "The document contains..."

User: "Can you read this note?" [sends image]
Agent: [uses OCR] "The note says..."
```

### Delivery and Read Receipts

Automatically logged for monitoring and debugging purposes.

## Troubleshooting

### Webhook Verification Issues

**Problem:** "Webhook verification failed" error when configuring callback URL

**Solutions:**

- Ensure your verify token in the environment variable exactly matches what you enter in Facebook
- Verify your server is running and accessible via HTTPS
- Check that your webhook URL path is `/messenger/webhook`
- Review server logs for the incoming verification request
- Make sure the handler returns the challenge as an integer

### No Messages Received

**Problem:** Webhook is verified but messages aren't reaching your agent

**Solutions:**

- Check that webhook subscriptions include `messages` and are active
- Verify your page is subscribed to the webhook (in Webhook Subscriptions)
- Ensure your access token hasn't expired
- Check server logs for incoming webhook requests
- Verify the app isn't in development mode with restricted access

### Message Sending Failures

**Problem:** Agent processes messages but responses don't appear in Messenger

**Solutions:**

- Confirm you're using a **page access token**, not a user access token
- Verify the token has `pages_messaging` permission
- Check that you're responding within the 24-hour messaging window
- Review error logs for specific API error codes
- Test the access token using Facebook's [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)

### Authentication Errors

**Problem:** "Invalid signature" or authentication-related errors

**Solutions:**

- Verify `AK_MESSENGER__APP_SECRET` matches your app's actual secret
- Ensure the app secret hasn't been regenerated in Facebook
- Check that webhook payloads haven't been modified in transit
- Review server logs for signature validation details

### Enable Debug Logging

For detailed troubleshooting information:

Agent Kernel auto-configures logging on import. To enable debug logging, use environment variables or configuration files:

**Using environment variables:**
```bash
export AK_LOGGING__AK__LEVEL=DEBUG  # Agent Kernel logger level
export AK_LOGGING__SYSTEM__LEVEL=DEBUG  # System/root logger level
```

**Using config.yaml:**
```yaml
logging:
  ak:
    level: DEBUG
  system:
    level: DEBUG
```

This will show:

- Incoming webhook requests
- Signature verification steps
- Agent processing details
- Outgoing API calls
- Error stack traces

## API Rate Limits

Facebook Messenger enforces rate limits to ensure platform stability:

### Message Limits

- **Standard tier**: ~10,000 messages per day per page
- **Rate**: Varies by tier and page quality score
- **Best practice**: Implement queuing for high-volume scenarios

### Response Window

- You must respond to user messages within **24 hours**
- After 24 hours, you need special permissions (Message Tags)
- To send messages outside this window, apply for advanced messaging features

### Handling Rate Limits

```python
import asyncio
from asyncio import Queue

class RateLimitedMessengerHandler(AgentMessengerRequestHandler):
    def __init__(self):
        super().__init__()
        self.message_queue = Queue()
      
    async def _send_message(self, recipient_id: str, text: str):
        # Add delay to respect rate limits
        await asyncio.sleep(0.1)  # 10 messages per second
        await super()._send_message(recipient_id, text)
```

## Production Deployment

### Pre-Launch Checklist

Before deploying to production:

1. ✅ **Complete Facebook App Review**

   - Request `pages_messaging` permission
   - Submit app for review with clear use case documentation
   - Provide test credentials and instructions
   - Typical approval time: 3-5 business days
2. ✅ **Security Measures**

   - Use environment variables for all secrets
   - Enable app secret verification (`AK_MESSENGER__APP_SECRET`)
   - Implement HTTPS with valid SSL certificate
   - Use secure secret management (AWS Secrets Manager, HashiCorp Vault)
3. ✅ **Infrastructure**

   - Deploy behind a reverse proxy (nginx, Apache)
   - Set up load balancing for high traffic
   - Implement health checks and monitoring
   - Configure auto-scaling if using cloud services
4. ✅ **Monitoring & Logging**

   - Set up centralized logging (CloudWatch, Datadog, ELK)
   - Configure alerts for errors and anomalies
   - Track conversation metrics and performance
   - Monitor API rate limits
5. ✅ **Error Handling**

   - Implement retry logic with exponential backoff
   - Handle network failures gracefully
   - Provide fallback responses for errors
   - Log errors for debugging
6. ✅ **Compliance**

   - Review Facebook Platform Policies
   - Ensure GDPR/CCPA compliance for user data
   - Implement data retention policies
   - Provide data deletion capabilities

### Deployment Architecture

For production deployments, consider:

**Serverless (AWS Lambda):**

- Cost-effective for low-to-medium traffic
- Auto-scaling built-in
- See `examples/aws-serverless` for reference

**Containerized (Docker/Kubernetes):**

- Better for high traffic and complex workflows
- Full control over environment
- See `examples/aws-containerized` for reference

**Traditional Server:**

- Simple deployment for small-scale applications
- Use systemd or supervisor for process management
- Configure nginx as reverse proxy

## Messenger Platform Capabilities

### Rich Message Templates

Extend the integration to send structured content:

**Quick Replies:**

```python
async def send_with_quick_replies(self, recipient_id: str, text: str):
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "text": text,
            "quick_replies": [
                {"content_type": "text", "title": "Yes", "payload": "YES"},
                {"content_type": "text", "title": "No", "payload": "NO"}
            ]
        }
    }
    # Send via API...
```

**Button Templates:**

```python
async def send_button_template(self, recipient_id: str):
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "How can I help you?",
                    "buttons": [
                        {"type": "postback", "title": "Sales", "payload": "SALES"},
                        {"type": "postback", "title": "Support", "payload": "SUPPORT"}
                    ]
                }
            }
        }
    }
    # Send via API...
```

### Persistent Menu

Add a persistent menu that appears in the composer:

```python
async def setup_persistent_menu(self):
    """Configure persistent menu for the bot"""
    url = f"{self._base_url}/me/messenger_profile"
    payload = {
        "persistent_menu": [{
            "locale": "default",
            "composer_input_disabled": False,
            "call_to_actions": [
                {"type": "postback", "title": "Help", "payload": "HELP"},
                {"type": "postback", "title": "Start Over", "payload": "START"}
            ]
        }]
    }
    # Send configuration...
```

## Messenger vs WhatsApp Comparison

| Feature                        | Facebook Messenger                | WhatsApp                      |
| ------------------------------ | --------------------------------- | ----------------------------- |
| **Message Limit**        | 2,000 characters                  | 4,096 characters              |
| **User Identifier**      | Page-Scoped ID (PSID)             | Phone number                  |
| **Visual Feedback**      | Typing indicators, seen receipts  | Read receipts                 |
| **Interactive Elements** | Buttons, quick replies, templates | Interactive messages, buttons |
| **Authentication**       | Page access token                 | Phone number ID + token       |
| **App Review**           | Required for public access        | Required for production       |
| **Rich Media**           | Extensive template support        | Limited to media messages     |

## Example Projects

Complete working examples with different configurations:

- **Basic Example**: \
`examples/api/messenger/server.py`
`examples/api/messenger/server_adk.py`
- **Custom Handler**: `examples/api/messenger/example_custom_handler.py`

## Additional Resources

- [Facebook Messenger Platform Documentation](https://developers.facebook.com/docs/messenger-platform)
- [Send API Reference](https://developers.facebook.com/docs/messenger-platform/reference/send-api)
- [Webhook Events Reference](https://developers.facebook.com/docs/messenger-platform/webhooks)
- [Platform Policy Guidelines](https://developers.facebook.com/docs/messenger-platform/policy-overview)
- [App Review Process](https://developers.facebook.com/docs/app-review)
- [Facebook for Developers](https://developers.facebook.com/)

## Getting Help

If you encounter issues:

1. Check the [troubleshooting section](#troubleshooting) above
2. Enable debug logging to see detailed request/response information
3. Review the Facebook Messenger Platform documentation
4. Check the [Agent Kernel GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
5. Visit the [Facebook Developer Community](https://developers.facebook.com/community/)