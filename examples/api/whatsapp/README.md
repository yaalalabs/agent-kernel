# WhatsApp Integration Example

This example demonstrates how to create a WhatsApp Business API integration with Agent Kernel.

## Prerequisites

1. Meta Business Account
2. WhatsApp Business App with verified phone number
3. Webhook configured in Meta Developer Portal
4. Required credentials (see below)

## Setup

### 1. Get WhatsApp Business API Credentials

Follow the setup guide in [AgentWhatsAppRequestHandler](../../../ak-py/src/agentkernel/integrations/whatsapp/README.md)

You'll need:
- Phone Number ID
- Access Token
- App Secret  
- Verify Token (you create this)

### 2. Configure Environment Variables

Create a `.env` file or export these variables:

```bash
export AK_WHATSAPP__VERIFY_TOKEN="your_secure_verify_token"
export AK_WHATSAPP__ACCESS_TOKEN="your_permanent_access_token"
export AK_WHATSAPP__APP_SECRET="your_app_secret"
export AK_WHATSAPP__PHONE_NUMBER_ID="123456789012345"
export AK_WHATSAPP__API_VERSION="v21.0"  # Optional

# OpenAI API Key for the agent
export OPENAI_API_KEY="your_openai_api_key"

# Multimodal Configuration (Optional)
export AK_MULTIMODAL__ENABLED=true
export AK_MULTIMODAL__MAX_ATTACHMENTS=5
```

### 3. Create Configuration File

Create `config.yaml`:

```yaml
whatsapp:
  agent: "general"
  agent_acknowledgement: "Processing your message..."
  api_version: "<your preferred version>"
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

Copy the HTTPS URL and configure it in your WhatsApp webhook settings.

## Configure WhatsApp Webhook

1. Go to https://developers.facebook.com/apps
2. Select your app
3. Go to WhatsApp > Configuration
4. Click "Edit" on webhook
5. Enter:
   - **Callback URL**: `https://your-tunnel-url.com/whatsapp/webhook`
   - **Verify Token**: Same as `AK_WHATSAPP_VERIFY_TOKEN`
6. Subscribe to `messages` webhook field

## Testing

1. Send a message to your WhatsApp Business number
2. The bot should respond with an acknowledgement
3. After processing, you'll receive the agent's response
4. Check server logs to see the request/response flow

### Test Message Examples

```
Hello
What services do you offer?
Can you help me with a technical issue?
```

**Multimodal Messages (with attachments):**
```bash
"What's in this photo?" [attach image]
"Can you analyze this document?" [attach PDF]
```

**Multimodal Messages (with attachments):**
```bash
"What's in this photo?" [attach image]
"Can you analyze this document?" [attach PDF]
```

## Advanced Examples

### Multi-Agent Setup

See `example_multi_agent.py` for a setup with multiple specialized agents.

### Custom Handler

See `example_custom_handler.py` for extending the handler with custom logic.

## Troubleshooting

### Webhook Verification Fails

- Ensure verify token matches in both config and Meta portal
- Check that your endpoint returns 200 status
- Verify URL is accessible via HTTPS

### No Messages Received

- Check webhook subscription is active
- Verify phone number is added to allowed list during testing
- Review Meta Business Suite for delivery status
- Check server logs for errors

### Agent Not Responding

- Verify OpenAI API key is set
- Check agent configuration in config.yaml
- Review server logs for agent errors

### Rate Limiting

If you hit rate limits:
- Implement message queuing
- Add retry logic with exponential backoff
- Consider upgrading your WhatsApp Business tier

## Production Deployment

For production deployment:

1. **Use HTTPS**: Deploy behind nginx or similar with SSL
2. **Environment Variables**: Use secure secret management
3. **Monitoring**: Add logging and alerting
4. **Scaling**: Use containerization and orchestration
5. **Error Handling**: Implement robust error handling and retries

See deployment documentation for AWS and other platforms.

## Resources

- [WhatsApp Cloud API Docs](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Agent Kernel Documentation](../../../docs/)
- [WhatsApp Integration Guide](../../../ak-py/src/agentkernel/integrations/whatsapp/README.md)
