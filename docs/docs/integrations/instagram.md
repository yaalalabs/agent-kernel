# Instagram

Deploy your Agent Kernel agents as Instagram Business bots that can respond to Direct Messages in real-time. This integration connects your AI agents directly to Instagram DMs, enabling natural conversations with users through one of the world's most popular social platforms.

## Overview

The `AgentInstagramRequestHandler` provides a seamless bridge between your Agent Kernel agents and Instagram Messaging. When users send a Direct Message to your Instagram Professional account (Business or Creator), their messages are automatically routed to your AI agent, which processes them and sends intelligent responses back through Instagram DMs.

**How it works:**

1. **User sends a DM** to your Instagram Professional account
2. **Message is verified** using Instagram's security protocols
3. **Visual feedback** is sent (typing indicator appears)
4. **Agent processes** the message and generates a response
5. **Response is delivered** back to the user as a DM

This integration uses the **Instagram API with Business Login for Instagram** (without Facebook Login), allowing Professional accounts to connect directly without requiring a Facebook Page.

## Key Features

- 🔐 **Secure Communication**: HMAC-SHA256 signature verification ensures all messages are authentic
- 💬 **Direct Messaging**: Full support for Instagram DM conversations
- ⚡ **Real-time Feedback**: Automatic typing indicators for better user experience
- 🔄 **Session Management**: Maintains conversation context using Instagram-Scoped IDs
- 📊 **Message Splitting**: Automatically handles long responses by splitting them into multiple messages (1000 char limit)
- 🎯 **Event Handling**: Processes various Instagram events including messages, postbacks, and reactions
- 📸 **Professional Accounts**: Works with both Business and Creator accounts

## Quick Start

### Prerequisites

Before you begin, you'll need:

- A [Meta Developer account](https://developers.facebook.com/)
- An Instagram Professional account (Business or Creator)
- A Meta App with Instagram API product added
- Business Login for Instagram configured
- A publicly accessible HTTPS endpoint (for webhook)

### 1. Set Up Your Meta App

**Create your app:**

1. Visit the [Meta Developers Portal](https://developers.facebook.com/apps)
2. Click "Create App" and select "Business" as the app type
3. Fill in your app details and create the app
4. From the left sidebar, click "Add Product" and select "Instagram API"

**Configure Instagram Business Login:**

1. In your app dashboard, go to **Use Cases** → select "Instagram Business"
2. Click **API setup with Instagram login**
3. Add required permissions:
   - `instagram_business_basic`
   - `instagram_business_manage_messages`

### 2. Get Your Credentials

**Generate an Access Token:**

1. In the "Generate access tokens" section, click **Add account**
2. Connect your Instagram Professional account
3. Generate a token with the required permissions
4. Copy and save this token securely - it starts with `IGAA...`
5. This will be your `AK_INSTAGRAM__ACCESS_TOKEN`

**Get your App Secret (recommended):**

1. Go to **App Settings** → **Basic** in the left sidebar
2. Click **Show** next to "App Secret"
3. Copy and save this secret - you'll use it as `AK_INSTAGRAM__APP_SECRET`

**Create a Verify Token:**

This is a random string you create yourself for webhook verification. Choose something secure like:

```bash
openssl rand -hex 32
```

Save this as `AK_INSTAGRAM__VERIFY_TOKEN`

### 3. Configure Environment Variables

Set these environment variables before starting your application:

```bash
export AK_INSTAGRAM__VERIFY_TOKEN="your_random_verify_token"
export AK_INSTAGRAM__ACCESS_TOKEN="IGAA..."  # Instagram User Access Token
export AK_INSTAGRAM__APP_SECRET="your_app_secret"  # Optional but recommended
export AK_INSTAGRAM__API_VERSION="v21.0"  # Optional, defaults to v21.0
```

### 4. Set Up Your Webhook

**For local development**, use a tunneling service to expose your local server:

```bash
# Using ngrok
ngrok http 8000

# Using pinggy
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

**Configure the webhook in Meta Developer Portal:**

1. In **Instagram API** settings, go to "Configure webhooks"
2. Enter your webhook URL: `https://your-domain.com/instagram/webhook`
3. Enter your verify token (the one you created above)
4. Click **Verify and Save**

**Subscribe to webhook events:**

In the webhook configuration, subscribe to:

- `messages` - To receive user messages

**Enable the webhook:**

Toggle the webhook subscription to "On" to start receiving events.

## Implementation

### Basic Setup

Here's a complete example to get your Instagram bot running:

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.instagram import AgentInstagramRequestHandler

# Create your AI agent
instagram_agent = OpenAIAgent(
    name="general",
    handoff_description="Helpful Instagram assistant",
    instructions="""You are a friendly assistant on Instagram DMs.
    - Keep responses concise and mobile-friendly
    - Use emojis sparingly to maintain professionalism
    - Break long explanations into short paragraphs
    - Be conversational and helpful
    - Remember: Instagram DMs have a 1000 character limit per message"""
)

# Initialize the module with your agent
OpenAIModule([instagram_agent])

# Start the server with Instagram integration
if __name__ == "__main__":
    handler = AgentInstagramRequestHandler()
    RESTAPI.run([handler])
```

### Configuration File

Optionally configure your agent and API settings in `config.yaml`:

```yaml
instagram:
  agent: "general"  # Which agent handles Instagram messages
  api_version: "v21.0"  # Instagram Graph API version
```

**Security Note:** Never store tokens or secrets in configuration files. Always use environment variables for sensitive credentials.

## Testing Your Integration

### Test from Meta Developer Portal

The easiest way to test during development:

1. Go to your app's **Instagram API** settings
2. Use the API testing tools to send test messages
3. Check your server logs to see the message being processed
4. You should receive a response in Instagram DMs

### Test from Instagram

Once your webhook is configured:

1. Open Instagram app on your phone or Instagram web
2. Go to the DMs of your Business/Creator account
3. Have another account (or test account) send a Direct Message
4. Watch for the typing indicator
5. Receive your agent's response

**Note:** If you are someone developing an app for others (Instagram business account is not owned by you), you'll need to complete Meta's app review process.

## Advanced Usage

### Custom Message Handling

Extend the handler to add custom logic, commands, or preprocessing:

```python
from agentkernel.instagram import AgentInstagramRequestHandler

class CustomInstagramHandler(AgentInstagramRequestHandler):
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
    handler = CustomInstagramHandler()
    RESTAPI.run([handler])
```

### Multi-Agent Setup

Route different types of conversations to specialized agents:

```python
from agentkernel.instagram import AgentInstagramRequestHandler

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
- **Documents**: PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), Text files
- **Media**: Audio and video files

**How It Works:**

1. **Detection**: When user sends message with attachment, handler identifies type
2. **Download**: File is downloaded from Instagram's servers
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

### Reactions

Message reactions are logged with extensibility for custom handling.

### Read Receipts

Read receipts are automatically logged for debugging purposes.

## Character Limits

Instagram DM messages have a **1000 character limit**. Long responses from your agent are automatically split into multiple messages to ensure delivery.

## API Endpoint

This integration uses the Instagram Graph API directly:

```
POST https://graph.instagram.com/{api_version}/me/messages
```

This requires an **Instagram User Access Token** (starts with `IGAA...`), not a Facebook Page Access Token.

## Troubleshooting

### 401 Unauthorized / Cannot Parse Access Token

**Problem:** API calls fail with authentication errors

**This is the most common issue.** It occurs when:

- Using a Facebook Page Access Token instead of Instagram User Access Token
- Token has expired (tokens are valid for 60 days)
- Token doesn't have required permissions

**Solutions:**

- Generate a new token from Business Login for Instagram
- The token should start with `IGAA...`
- Do NOT use tokens starting with `EAAG...` (Facebook Page tokens)
- Verify token using [Meta Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)

### Webhook Verification Issues

**Problem:** "Webhook verification failed" error when configuring callback URL

**Solutions:**

- Ensure your verify token in the environment variable exactly matches what you enter in Meta portal
- Verify your server is running and accessible via HTTPS
- Check that your webhook URL path is `/instagram/webhook`
- Review server logs for the incoming verification request
- Make sure the handler returns the challenge as an integer

### No Messages Received

**Problem:** Webhook is verified but messages aren't reaching your agent

**Solutions:**

- Check that webhook subscriptions include `messages` and are active
- Verify Instagram account is a Professional account (Business or Creator)
- Ensure app has `instagram_business_manage_messages` permission
- Check server logs for incoming webhook requests
- Verify the webhook toggle is enabled

### Permission Errors (Error 10)

**Problem:** API returns permission denied errors

**Solutions:**

- Ensure all required permissions are granted:
  - `instagram_business_basic`
  - `instagram_business_manage_messages`
- Re-generate access token with all permissions
- Check that Instagram account is properly connected in the app settings

### Message Sending Failures

**Problem:** Agent processes messages but responses don't appear in Instagram

**Solutions:**

- Confirm you're using an **Instagram User Access Token** (starts with `IGAA...`)
- Verify the token has required permissions
- Check that you're responding within a reasonable time
- Review error logs for specific API error codes
- Test the access token using Meta's Access Token Debugger

### Enable Debug Logging

For detailed troubleshooting information:

```python
import logging

# Enable debug logging before starting the server
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

This will show:

- Incoming webhook requests
- Signature verification steps
- Agent processing details
- Outgoing API calls
- Error stack traces

## API Rate Limits

Instagram enforces rate limits to ensure platform stability:

### Message Limits

- Rate limits vary by account type and quality score
- **Best practice**: Implement queuing for high-volume scenarios

### Handling Rate Limits

```python
import asyncio
from asyncio import Queue

class RateLimitedInstagramHandler(AgentInstagramRequestHandler):
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

1. ✅ **Complete Meta App Review**

   - Request `instagram_business_manage_messages` permission
   - Submit app for review with clear use case documentation
   - Provide test credentials and instructions
   - Typical approval time: 3-5 business days
2. ✅ **Security Measures**

   - Use environment variables for all secrets
   - Enable app secret verification (`AK_INSTAGRAM__APP_SECRET`)
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
6. ✅ **Token Management**

   - Instagram User Access Tokens expire in 60 days
   - Implement token refresh before expiration
   - Set up alerts for token expiration
7. ✅ **Compliance**

   - Review Meta Platform Policies
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

## Instagram vs Messenger vs WhatsApp Comparison

| Feature                          | Instagram                       | Facebook Messenger               | WhatsApp                |
| -------------------------------- | ------------------------------- | -------------------------------- | ----------------------- |
| **Message Limit**          | 1,000 characters                | 2,000 characters                 | 4,096 characters        |
| **User Identifier**        | Instagram-Scoped ID             | Page-Scoped ID (PSID)            | Phone number            |
| **Visual Feedback**        | Typing indicators               | Typing indicators, seen receipts | Read receipts           |
| **Authentication**         | Instagram User Token (IGAA)     | Page access token                | Phone number ID + token |
| **Facebook Page Required** | No (with Business Login)        | Yes                              | No                      |
| **Account Type**           | Professional (Business/Creator) | Facebook Page                    | WhatsApp Business       |
| **App Review**             | Required for production         | Required for public access       | Required for production |

## Example Projects

Complete working examples with different configurations:

- **Basic Example**: \
`examples/api/instagram/server.py`\
`examples/api/instagram/server_adk.py`
- **Integration Guide**: \
`ak-py/src/agentkernel/integration/instagram/README.md`

## Additional Resources

- [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)
- [Instagram Messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api)
- [Webhook Setup Guide](https://developers.facebook.com/docs/instagram-platform/webhooks)
- [Meta Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)
- [Meta Platform Policies](https://developers.facebook.com/docs/instagram-platform/overview)
- [Meta for Developers](https://developers.facebook.com/)

## Getting Help

If you encounter issues:

1. Check the [troubleshooting section](#troubleshooting) above
2. Enable debug logging to see detailed request/response information
3. Review the Instagram Platform documentation
4. Check the [Agent Kernel GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
5. Visit the [Meta Developer Community](https://developers.facebook.com/community/)