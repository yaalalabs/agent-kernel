# Telegram Integration

Deploy your Agent Kernel agents as Telegram bots that can respond to messages in real-time. This integration connects your AI agents directly to Telegram, enabling natural conversations with users through one of the world's most popular messaging platforms.

## Overview

The `AgentTelegramRequestHandler` provides a seamless bridge between your Agent Kernel agents and Telegram. When users message your bot, their messages are automatically routed to your AI agent, which processes them and sends intelligent responses back through Telegram.

### How it works:

1. User sends a message to your Telegram bot 
2. Telegram delivers the message to your webhook endpoint 
3. Agent Kernel verifies and processes the message
4. Visual feedback is sent (typing indicator, etc.)
5. Agent generates a response and sends it back to the user

The integration handles all the complexity of the Telegram Bot API, including webhook setup, security, message formatting, and session management.

## Quick Start

### Prerequisites

- Telegram account
- Bot created via [@BotFather](https://t.me/botfather)
- Bot token from BotFather
- Public HTTPS endpoint (use ngrok or pinggy for local development)

### 1. Create Your Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow instructions
3. Save your bot token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Get Your Credentials

- Bot Token: From BotFather
- Webhook Secret: Optional, any secure random string

### 3. Configure Environment Variables

Set these before starting your application:

```bash
export AK_TELEGRAM__BOT_TOKEN="your_bot_token"
export AK_TELEGRAM__WEBHOOK_SECRET="your_secure_random_string"  # Optional
export OPENAI_API_KEY="your_openai_api_key"
```

### 4. Expose Local Server

Use a tunneling service for webhook delivery:

**ngrok:**
```bash
ngrok http 8000
```

**pinggy:**
```bash
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

Copy the HTTPS URL for webhook setup.

### 5. Configure Telegram Webhook

Set your webhook using curl:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-tunnel-url.com/telegram/webhook",
    "secret_token": "your_secure_random_string"
  }'
```

Or with Python:

```python
import requests

BOT_TOKEN = "your_bot_token"
WEBHOOK_URL = "https://your-tunnel-url.com/telegram/webhook"
SECRET_TOKEN = "your_secure_random_string"

response = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    json={
        "url": WEBHOOK_URL,
        "secret_token": SECRET_TOKEN,
    }
)
print(response.json())
```

Verify webhook:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

## Features

- Text message and command handling  
- AI-powered responses via Agent Kernel  
- Typing indicator  
- Inline keyboards  
- Markdown formatting  
- Session management (per chat)  
- Automatic message splitting for long responses  

## Advanced Usage

### Custom Command Handler

```python
from agentkernel.telegram import AgentTelegramRequestHandler

class CustomTelegramHandler(AgentTelegramRequestHandler):
    async def _handle_command(self, chat_id: int, command: str):
        if command == "/status":
            await self._send_message(chat_id, "✅ Bot is running!")
        elif command == "/about":
            await self._send_message(chat_id, "I'm powered by Agent Kernel and OpenAI")
        else:
            await super()._handle_command(chat_id, command)
```

### Multi-Agent Setup (Telegram)

```python
support_agent = OpenAIAgent(
    name="support",
    handoff_description="Customer support agent",
    instructions="Provide helpful customer support. Be concise for Telegram.",
)

sales_agent = OpenAIAgent(
    name="sales",
    handoff_description="Sales inquiry agent",
    instructions="Help with product questions. Keep responses brief.",
)

OpenAIModule([support_agent, sales_agent])
```

### Inline Keyboards

```python
async def _send_message_with_keyboard(self, chat_id: int, text: str):
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Option 1", "callback_data": "opt1"},
                {"text": "Option 2", "callback_data": "opt2"}
            ],
            [{"text": "Help", "callback_data": "help"}]
        ]
    }
    await self._send_message(chat_id, text, reply_markup=reply_markup)
```

### Markdown Formatting

```python
await self._send_message(
    chat_id,
    "*Bold text*\n_Italic text_\n`Code`",
    parse_mode="Markdown"
)
```


## Supported Message Types

- Text messages
- Commands (e.g., /start, /help)
- Inline keyboards and callback queries
- Attachments (basic support)
- Session management per chat

## Troubleshooting

### Webhook Verification Issues

**Problem:** Webhook setup fails or Telegram can't reach your endpoint

**Solutions:**
- Ensure your bot token is correct
- Webhook URL must be HTTPS and publicly accessible
- Check webhook info: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
- Review server logs for errors
- Verify agent configuration and OpenAI API key

### No Messages Received

**Problem:** Webhook is set but messages aren't reaching your agent

**Solutions:**
- Verify your server is running and accessible
- Check that your webhook URL path is `/telegram/webhook`
- Review server logs for incoming webhook requests

### Message Sending Failures

**Problem:** Agent processes messages but responses don't appear in Telegram

**Solutions:**
- Confirm you're using a valid bot token
- Check for API error codes in logs
- Ensure you are not exceeding rate limits

### Authentication Errors

**Problem:** "Invalid secret token" or authentication-related errors

**Solutions:**
- Verify `AK_TELEGRAM__WEBHOOK_SECRET` matches what you set in Telegram
- Ensure the secret hasn't been changed
- Check server logs for validation details

### Enable Debug Logging

For detailed troubleshooting information:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## API Rate Limits

Telegram Bot API enforces rate limits:
- **Messages to same chat:** 1 message per second
- **Bulk messages:** 30 messages per second to different chats
- **Group messages:** 20 messages per minute per group

Best practice: Implement queuing for high-volume scenarios.

## Production Deployment

### Pre-Launch Checklist

✅ Use environment variables for all secrets \
✅ Deploy behind a reverse proxy (nginx, Apache) \
✅ Set up health checks and monitoring \
✅ Implement error handling and retry logic \
✅ Review Telegram Bot API documentation for compliance 

### Deployment Architecture

- **Serverless (AWS Lambda):** Cost-effective for low-to-medium traffic, auto-scaling built-in
- **Containerized (Docker/Kubernetes):** Better for high traffic and complex workflows
- **Traditional Server:** Simple deployment for small-scale applications

## Telegram vs Messenger Comparison

| Feature                | Telegram                | Facebook Messenger         |
|------------------------|-------------------------|---------------------------|
| Message Limit          | 4096 characters         | 2000 characters           |
| User Identifier        | Chat ID                 | Page-Scoped ID (PSID)     |
| Visual Feedback        | Typing indicators       | Typing, seen receipts     |
| Interactive Elements   | Inline keyboards        | Buttons, quick replies    |
| Authentication         | Bot token + secret      | Page access token + secret|
| App Review             | Not required            | Required for public access|
| Rich Media             | Media, basic attachments| Extensive template support|

## Example Projects

- Basic Example: `examples/api/telegram/server.py`

## References

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [BotFather](https://t.me/botfather)

***
