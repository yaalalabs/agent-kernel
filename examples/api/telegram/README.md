# Telegram Bot Integration Example

This example demonstrates how to create a Telegram Bot integration with Agent Kernel.

## Prerequisites

1. Telegram account
2. Bot created via BotFather
3. Bot token from BotFather
4. Webhook endpoint (ngrok or similar for local development)

## Setup

### 1. Create Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` command
3. Follow instructions to create your bot
4. Copy the **Bot Token** (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Configure Environment Variables

Create a `.env` file or export these variables:

```bash
# Telegram Bot Token from BotFather
export AK_TELEGRAM__BOT_TOKEN="your_bot_token_here"

# Optional: Secret token for webhook security
export AK_TELEGRAM__WEBHOOK_SECRET="your_secure_random_string"

# OpenAI API Key for the agent
export OPENAI_API_KEY="your_openai_api_key"
```

### 3. Create Configuration File

Create `config.yaml`:

```yaml
telegram:
  agent: "general"
  api_version: "bot"
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

The server will start on `http://0.0.0.0:8000` by default.

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

Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`)

## Configure Telegram Webhook

### Option 1: Using curl
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-tunnel-url.com/telegram/webhook",
    "secret_token": "your_secure_random_string"
  }'
```

### Option 2: Using Python script
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

### Verify Webhook

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

## Testing

1. Open Telegram and find your bot (by username you set in BotFather)
2. Send `/start` to begin conversation
3. Send any message
4. The bot should:
   - Show typing indicator
   - Respond with AI-generated message
5. Check server logs to see the request/response flow

### Test Message Examples

```
/start
Hello
What can you help me with?
Tell me about your services
Can you answer technical questions?
```

## Bot Commands

Built-in commands:
- `/start` - Start conversation with the bot
- `/help` - Show help message

You can customize these in `server.py` by modifying the `_handle_command` method.

## Advanced Examples

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

### Multi-Agent Setup

```python
# Create specialized agents
support_agent = OpenAIAgent(
    name="support",
    handoff_description="Customer support agent",
    instructions="Provide helpful customer support. Be concise for Telegram."
)

sales_agent = OpenAIAgent(
    name="sales",
    handoff_description="Sales inquiry agent",
    instructions="Help with product questions. Keep responses brief."
)

# Initialize with multiple agents
OpenAIModule([support_agent, sales_agent])
```

### Send Inline Keyboards

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

### Use Markdown Formatting

```python
await self._send_message(
    chat_id,
    "*Bold text*\n_Italic text_\n`Code`",
    parse_mode="Markdown"
)
```

## Troubleshooting

### Webhook Not Working

- Verify bot token is correct
- Ensure webhook URL is HTTPS (required by Telegram)
- Check webhook info: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
- Make sure server is running and accessible
- Verify firewall/network settings

### Bot Not Responding

- Check OpenAI API key is set correctly
- Review server logs for errors
- Verify agent configuration in `config.yaml`
- Test webhook manually with curl

### Invalid Token Error

- Double-check bot token from BotFather
- Ensure no spaces or extra characters in token
- Token format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### Secret Token Mismatch

- Ensure `AK_TELEGRAM__WEBHOOK_SECRET` matches what you set in webhook
- Remove secret token temporarily for testing: `unset AK_TELEGRAM__WEBHOOK_SECRET`


## Resources

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [BotFather Commands](https://core.telegram.org/bots#botfather-commands)
- [Telegram Bot Examples](https://core.telegram.org/bots/samples)
- [Agent Kernel Documentation](../../../docs/)

