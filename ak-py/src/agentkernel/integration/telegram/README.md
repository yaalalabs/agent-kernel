# Telegram Integration

Telegram Bot API integration for Agent Kernel using webhooks.

The `AgentTelegramRequestHandler` class handles conversations with agents via Telegram Bot API webhooks. This integration uses the official Telegram Bot API (https://core.telegram.org/bots/api) without requiring third-party libraries beyond standard HTTP clients.

## How It Works

1. When a message is received from Telegram, it's processed by the webhook handler
2. The message text is extracted and passed to your chosen Agent
3. The Agent response is sent back as a Telegram message
4. Long messages are automatically split to respect Telegram's character limits (4096 characters)

## Telegram Bot Setup

### Prerequisites

1. A Telegram account
2. A bot created via [@BotFather](https://t.me/botfather)

### Configuration Steps

1. **Create a Telegram Bot**

   - Open Telegram and search for [@BotFather](https://t.me/botfather)
   - Send `/newbot` command
   - Follow the prompts to name your bot
   - Save the bot token provided
2. **Get Your Credentials**

   - **Bot Token**: Provided by BotFather when you create the bot
   - **Bot Username**: The username you chose (ending in `bot`)
3. **Configure Webhook**

   - The webhook is automatically set when your server starts
   - Or manually set via: `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/telegram/webhook`

### Required Environment Variables

```bash
export AK_TELEGRAM__BOT_TOKEN="your_bot_token_from_botfather"
export AK_TELEGRAM__WEBHOOK_SECRET="your_secret_token"  # Optional, for webhook security
export OPENAI_API_KEY="your_openai_api_key"
```

### Webhook Verification

Telegram doesn't require webhook verification like Meta platforms. The webhook URL just needs to be HTTPS and accessible.

## Simple Telegram Integration Code

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.telegram import AgentTelegramRequestHandler

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

# Initialize module with agent
OpenAIModule([general_agent])

if __name__ == "__main__":
    handler = AgentTelegramRequestHandler()
    RESTAPI.run([handler])
```

## Configuration Options

### config.yaml

```yaml
telegram:
  agent: "general"  # Name of the agent to handle Telegram messages
```

It is strongly recommended not to keep secrets and keys in the config file. Set them as environment variables.

## Features

### Supported Message Types

- **Text Messages**: Standard text messages
- **Images**: Photos sent directly to the bot
- **Documents**: Files including PDFs, TXT, CSV, DOCX, and other document formats
- **Commands**: Bot commands starting with `/`
- **Replies**: Reply to bot messages

### Multi-Modal Support

The Telegram integration **fully supports** sending images and documents to agents. When a user sends a message with attachments:

1. **Images**: Photos are extracted, base64-encoded, and sent to the agent as `AgentRequestImage`
2. **Documents**: Files are downloaded, base64-encoded, and sent to the agent as `AgentRequestFile`
3. **Combined**: A message can include both text and files/images which are all processed together

**Status:** ✅ **FULLY IMPLEMENTED AND WORKING**

- ✅ File/image detection and download infrastructure
- ✅ Base64 encoding of files/images
- ✅ Multi-modal requests forwarding (`service.run_multi()`)
- ✅ Session memory for follow-up questions with context
- ✅ Works with **OpenAI SDK** and **Google ADK** agents

**Supported file types:**

- **Images**: JPEG, PNG, GIF, WebP, and other image formats
- **Documents**: PDF, TXT, CSV, DOC, DOCX, and other document formats

**Limitations:**

- Maximum file size: ~20MB (Telegram API limit, may vary by file type)
- Processing time: Large files may take 30-60 seconds to download and analyze
- Session context: Cleared on server restart (can be persisted with external storage)
- Model requirements: Agent must support multimodal (OpenAI GPT-4o, Google ADK, etc.)

### Message Handling

- **Automatic Message Splitting**: Messages longer than 4096 characters are automatically split
- **Session Management**: Uses chat ID as session ID to maintain conversation context
- **Typing Indicator**: Shows typing status while processing
- **Markdown Support**: Responses support Telegram's Markdown formatting
- **File Handling**: Supports images (JPEG, PNG, GIF, WebP) and documents (PDF, TXT, CSV, DOC, DOCX, etc.)

### Security

- **HTTPS Required**: Telegram requires webhook URLs to use HTTPS
- **Token Authentication**: Bot token authenticates all API calls

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

Update your webhook URL with the tunnel URL.

### Set Webhook Manually

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-ngrok-url.ngrok.io/telegram/webhook"
```

### Testing Steps

1. Start your local server
2. Set up the tunnel
3. Configure webhook with tunnel URL
4. Send a test message to your bot
5. Check logs for request/response flow

## Troubleshooting

### Common Issues

**Webhook not receiving messages:**

- Ensure webhook URL is HTTPS
- Verify the URL is publicly accessible
- Check bot token is correct
- Use `getWebhookInfo` to debug: `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`

**Messages not sending:**

- Verify bot token is correct
- Check bot hasn't been blocked by user
- Ensure chat_id is valid

**Bot not responding:**

- Check server logs for errors
- Verify agent is properly configured
- Ensure OpenAI API key is set

**Files/Images not being processed:**

- Verify your agent supports images/files (OpenAI SDK or Google ADK)
- Check the file size isn't too large
- Ensure `max_file_size` configuration allows the file
- Check logs for download errors from Telegram servers

### Debug Logging

Enable debug logging to troubleshoot:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## API Rate Limits

Telegram Bot API has rate limits:

- **Messages to same chat**: 1 message per second
- **Bulk messages**: 30 messages per second to different chats
- **Group messages**: 20 messages per minute per group
- **File downloads**: Files are downloaded on-demand when received

## File Size Considerations

- **Downloaded files**: Automatically downloaded and base64-encoded
- **Encoding overhead**: Base64 encoding increases size by ~33%
- **Agent framework limits**: OpenAI and Google ADK have their own file size limits
- **Performance**: Large files may take longer to download and process

## References

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [Telegram Bot API Media Types](https://core.telegram.org/bots/api#mediagroupmessage)
- [BotFather](https://t.me/botfather)